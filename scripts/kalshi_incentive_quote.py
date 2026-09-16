#!/usr/bin/env python3
"""Quote the Kalshi Liquidity Incentive Program. DRY RUN unless forced live.

    python scripts/kalshi_incentive_quote.py --capital 250                # dry run
    python scripts/kalshi_incentive_quote.py --capital 250 --live         # sends
    python scripts/kalshi_incentive_quote.py --cancel-all --live          # flatten quotes

WHAT IT DOES. Finds active liquidity programs, computes each book's Reference
Price (walk down from the best bid until cumulative resting size reaches
Target Size / 5), and rests post_only bids AT that price on both sides. An
order at or better than the Reference Price scores size x 1.0; k ticks below
scores size x DiscountFactor**k, which at 0.5 is worthless within a few ticks.
A snapshot pays NOBODY unless both sides hold >= Target Size, so markets where
our size cannot get the book over that line are skipped rather than funded.

SAFETY, in the order it is enforced:
  1. dry run unless --live AND env KALSHI_LIVE=1 AND no state/KILL_SWITCH_KALSHI;
  2. the kill switch is re-checked immediately before EVERY order, not once;
  3. post_only on every order -- a maker order that crosses gets taker-filled,
     which is 4x the fee and breaks the whole thesis;
  4. never bid above the Reference Price, so we never lift anyone's offer;
  5. hard caps on total capital and per-market capital, checked before each send;
  6. broker state is read FIRST and our existing resting orders count against
     the caps -- the Ops rule is that the broker is truth, not our own log;
  7. client_order_id is a deterministic hash of (ticker, side, price, day), so
     a retry after an ambiguous response cannot double the position.

WHAT IT DOES NOT DO. It does not chase the Reference Price tick by tick. That
price re-derives every second and the fee rounds UP per order, so requoting
hard is a known way to pay real fees for imaginary score. It quotes, and
--cancel-stale retires quotes that have fallen more than `--max-ticks-below`
under the current reference.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.client import KalshiClient          # noqa: E402
from quantfirm.kalshi.halt import kill_switch_tripped     # noqa: E402

# This book arms SEPARATELY from the 15m desk. KALSHI_LIVE is shared, so if we
# keyed off it alone, turning the metals desk on would silently start quoting
# $257 of incentive book too. This file must exist, and it is tracked, so git
# blame shows who armed it and when.
ARM = os.path.join(REPO, "state", "INCENTIVE_LIVE")

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROGRAMS = "https://external-api.kalshi.com/trade-api/v2/incentive_programs"
LOG = os.path.join(REPO, "state", "kalshi_incentive_orders.jsonl")


def _get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_programs():
    out, cursor = [], ""
    while True:
        d = _get(f"{PROGRAMS}?status=active&limit=1000" + (f"&cursor={cursor}" if cursor else ""), 60)
        page = d.get("incentive_programs", [])
        out += page
        cursor = d.get("next_cursor") or ""
        if not cursor or not page:
            return out


def reference_price(levels, target_size):
    """Walk DOWN from the best bid until cumulative size reaches target/5."""
    cum = 0.0
    for price, size in sorted(levels, key=lambda z: -z[0]):
        cum += size
        if cum >= target_size / 5:
            return price
    return None


def discounted_score(levels, ref, discount):
    total = 0.0
    for price, size in levels:
        ticks = round((ref - price) * 100)
        total += size * (discount ** ticks) if ticks > 0 else size
    return total


def assess(prog, now, min_hours):
    """Price one market. Returns None when it is not worth funding."""
    ticker = prog["market_ticker"]
    dur_h = (_ts(prog["end_date"]) - _ts(prog["start_date"])).total_seconds() / 3600.0
    left_h = (_ts(prog["end_date"]) - now).total_seconds() / 3600.0
    if dur_h <= 0 or left_h < min_hours:
        return None
    try:
        ob = _get(f"{BASE}/markets/{ticker}/orderbook?depth=100")["orderbook_fp"]
    except Exception:
        return None
    yes = [(_f(a), _f(b)) for a, b in (ob.get("yes_dollars") or [])]
    no = [(_f(a), _f(b)) for a, b in (ob.get("no_dollars") or [])]
    if not yes or not no:
        return None
    target = _f(prog["target_size_fp"])
    discount = (prog.get("discount_factor_bps") or 0) / 10000.0
    yes_ref = reference_price(yes, target)
    no_ref = reference_price(no, target)
    if yes_ref is None or no_ref is None or yes_ref <= 0 or no_ref <= 0:
        return None
    return dict(
        ticker=ticker, target=target, discount=discount,
        yes_ref=yes_ref, no_ref=no_ref, unit=yes_ref + no_ref,
        yes_depth=sum(s for _, s in yes), no_depth=sum(s for _, s in no),
        yes_score=discounted_score(yes, yes_ref, discount),
        no_score=discounted_score(no, no_ref, discount),
        pool=prog["period_reward"] / 10000.0, dur_h=dur_h, left_h=left_h,
    )


def plan_market(m, budget):
    """Sizes for one market, or None if the snapshot could never qualify."""
    # Split the budget across the two legs in proportion to their prices, so
    # both legs carry the same contract count -- the exclusion rule is about
    # CONTRACTS on each side, not dollars.
    size = budget / m["unit"]
    size = float(int(size))               # whole contracts, and round DOWN so the
                                          # cap below is computed on what we actually send
    if size < 1:
        return None
    if m["yes_depth"] + size < m["target"] or m["no_depth"] + size < m["target"]:
        return None                       # snapshot would be excluded: pays nobody
    pool_share = 0.5 * (size / (size + m["yes_score"]) + size / (size + m["no_score"]))
    expected = m["pool"] * pool_share * min(1.0, m["left_h"] / m["dur_h"])
    if expected < 1.0:                    # under the $1 minimum payout: never paid
        return None
    return dict(size=size, yes_cost=size * m["yes_ref"], no_cost=size * m["no_ref"],
                share=pool_share, expected=expected)


def coid(ticker, side, price):
    """Deterministic per (market, side, price, UTC day) so retries can't double."""
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    raw = f"lip|{ticker}|{side}|{price:.4f}|{day}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")



def reconcile(client, live, progs_by_ticker, now, max_ticks_below, args):
    """Cancel quotes that stopped earning; return (kept_capital, kept_tickers).

    The board rotates -- roughly 200+ new programs an hour, and every program
    ends. So each pass has to retire dead quotes before funding new ones. Three
    reasons to cancel, and nothing else:

      * the program ended or vanished  -> the market pays nothing now;
      * our price fell >max_ticks_below the current Reference Price -> score is
        DiscountFactor**k, so at 0.5 we are earning a rounding error;
      * the book fell under Target Size on either side -> the snapshot is
        excluded and pays NOBODY, so our capital sits there earning zero.

    Everything else is left alone on purpose. Requoting costs a fee that rounds
    UP per order, so churning a quote that is still scoring is how you pay real
    money for imaginary improvement.
    """
    try:
        resting = (client.orders(status="resting").get("orders") or [])
    except Exception as e:
        print(f"reconcile: cannot read resting orders ({type(e).__name__}) — not cancelling")
        return 0.0, set(), 0
    kept_cap, kept, cancelled = 0.0, set(), 0
    # price each ticker once, not once per order
    tickers = {o.get("ticker") for o in resting if o.get("ticker")}
    books = {}
    with ThreadPoolExecutor(16) as ex:
        for tk, m in zip(tickers, ex.map(
                lambda t: assess(progs_by_ticker[t], now, 0.0) if t in progs_by_ticker else None,
                tickers)):
            books[tk] = m
    for o in resting:
        tk = o.get("ticker")
        oid = o.get("order_id") or o.get("id")
        px = _f(o.get("price_dollars") or o.get("yes_price_dollars"))
        ct = _f(o.get("remaining_count") or o.get("count"))
        side = o.get("side")
        m = books.get(tk)
        why = None
        if tk not in progs_by_ticker:
            why = "program ended"
        elif m is None:
            why = "book unreadable"
        else:
            # our YES bid is px; our NO bid is (1 - px) because the API prices
            # every order as the YES price
            ours = px if side == "bid" else round(1.0 - px, 2)
            ref = m["yes_ref"] if side == "bid" else m["no_ref"]
            ticks = round((ref - ours) * 100)
            if ticks > max_ticks_below:
                why = f"{ticks} ticks below ref ({m['discount'] ** ticks:.3f}x credit)"
            elif m["yes_depth"] < m["target"] or m["no_depth"] < m["target"]:
                why = "book under Target Size — snapshots excluded, pays nobody"
        if why:
            print(f"  cancel {tk} {side} @{px:.2f} x{ct:.0f} — {why}")
            if live and oid:
                try:
                    client.cancel_order(oid)
                    log({"ts": now.isoformat(), "action": "cancel", "order_id": oid,
                         "ticker": tk, "reason": why})
                    cancelled += 1
                except Exception as e:
                    print(f"    cancel failed: {type(e).__name__}")
                    kept_cap += px * ct
                    kept.add(tk)
        else:
            kept_cap += px * ct
            kept.add(tk)
    return kept_cap, kept, cancelled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=250.0, help="total $ across all markets")
    ap.add_argument("--max-per-market", type=float, default=40.0)
    ap.add_argument("--markets", type=int, default=8)
    ap.add_argument("--min-hours-left", type=float, default=48.0,
                    help="skip programs ending sooner than this; long programs need no chasing")
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--live", action="store_true", help="actually send orders")
    ap.add_argument("--cancel-all", action="store_true", help="cancel every resting LIP order")
    ap.add_argument("--max-ticks-below", type=int, default=2,
                    help="cancel a quote once it sits this many ticks under the current "
                         "Reference Price; at discount 0.5 three ticks is already 0.125x")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    client = KalshiClient(env="prod")

    # ---- gate 1: may we trade at all? -----------------------------------
    killed = kill_switch_tripped()
    env_live = os.environ.get("KALSHI_LIVE") == "1"
    armed = os.path.exists(ARM)
    live = args.live and env_live and armed and not killed and client.can_trade
    print("gate:")
    print(f"  --live passed        {args.live}")
    print(f"  KALSHI_LIVE=1        {env_live}")
    print(f"  state/INCENTIVE_LIVE {armed}"
          + ("" if armed else "  <- this book is not armed"))
    print(f"  credentials present  {client.can_trade}")
    print(f"  kill switch clear    {not killed}"
          + ("" if not killed else "  <- state/KILL_SWITCH_KALSHI is present"))
    print(f"  => {'LIVE, ORDERS WILL BE SENT' if live else 'DRY RUN, nothing will be sent'}\n")

    # ---- gate 2: broker state is truth ----------------------------------
    resting, committed, held = [], 0.0, set()
    progs_all = [p for p in fetch_programs()
                 if p["incentive_type"] == "liquidity" and _ts(p["end_date"]) > now]
    progs_by_ticker = {p["market_ticker"]: p for p in progs_all}
    if client.can_trade:
        try:
            print(f"broker: balance ${client.balance()}")
            resting = (client.orders(status="resting").get("orders") or [])
            print(f"broker: {len(resting)} resting orders")
        except Exception as e:
            print(f"broker: could not read state ({type(e).__name__}) — refusing to send")
            live = False
        if not args.cancel_all:
            print("\nreconcile (the board rotates; retire dead quotes before funding new):")
            committed, held, n = reconcile(client, live, progs_by_ticker, now,
                                           args.max_ticks_below, args)
            print(f"  kept ${committed:.2f} across {len(held)} markets, "
                  f"{'cancelled' if live else 'would cancel'} {n}")
    else:
        print("broker: no credentials, cannot read account state")

    if args.cancel_all:
        print(f"\ncancelling {len(resting)} resting orders")
        for o in resting:
            oid = o.get("order_id") or o.get("id")
            if live and oid:
                client.cancel_order(oid)
                log({"ts": now.isoformat(), "action": "cancel", "order_id": oid})
            print(f"  {'CANCELLED' if live else 'would cancel'} {oid}")
        return 0

    # ---- select ----------------------------------------------------------
    import random
    random.seed()
    fresh = [p for p in progs_all if p["market_ticker"] not in held]
    pick = random.sample(fresh, min(args.sample, len(fresh)))
    with ThreadPoolExecutor(24) as ex:
        scored = [m for m in ex.map(lambda p: assess(p, now, args.min_hours_left), pick) if m]

    budget = min(args.max_per_market, args.capital / max(args.markets, 1))
    cands = []
    for m in scored:
        pl = plan_market(m, budget)
        if pl:
            cands.append((pl["expected"] / (pl["yes_cost"] + pl["no_cost"]), m, pl))
    cands.sort(reverse=True, key=lambda z: z[0])

    print(f"\npriced {len(scored)} programs with >{args.min_hours_left:.0f}h left; "
          f"{len(cands)} can qualify at ${budget:.0f}/market\n")
    if not cands:
        print("nothing fundable this pass")
        return 0

    headroom = args.capital - committed
    print(f"{'ticker':<36}{'size':>7}{'yes@':>7}{'no@':>6}{'cost$':>8}{'share':>7}{'exp$':>7}")
    spent = 0.0
    sent = 0
    for _, m, pl in cands[:args.markets]:
        cost = pl["yes_cost"] + pl["no_cost"]
        if spent + cost > headroom:
            continue
        print(f"{m['ticker']:<36}{pl['size']:>7.0f}{m['yes_ref']:>7.2f}{m['no_ref']:>6.2f}"
              f"{cost:>8.2f}{pl['share']*100:>6.1f}%{pl['expected']:>7.2f}")
        for side, price in (("yes", m["yes_ref"]), ("no", m["no_ref"])):
            # Kalshi prices every order as the YES price: a NO bid at q is an
            # ask at 1-q. side 'bid' buys YES, 'ask' buys NO.
            api_side = "bid" if side == "yes" else "ask"
            api_price = price if side == "yes" else round(1.0 - price, 2)
            intent = {"ts": now.isoformat(), "action": "place", "ticker": m["ticker"],
                      "leg": side, "api_side": api_side, "price": api_price,
                      "count": int(pl["size"]), "post_only": True,
                      "client_order_id": coid(m["ticker"], side, api_price),
                      "live": bool(live)}
            log(intent)                                   # log BEFORE sending
            if not live:
                continue
            if kill_switch_tripped():                     # re-check every order
                print("  kill switch tripped mid-run — stopping")
                return 1
            try:
                r = client.create_order(
                    ticker=m["ticker"], side=api_side, count=Decimal(int(pl["size"])),
                    price=Decimal(str(api_price)), time_in_force="good_till_cancelled",
                    post_only=True, client_order_id=intent["client_order_id"])
                log({**intent, "result": "ok", "order_id": (r.get("order") or {}).get("order_id")})
                sent += 1
            except Exception as e:
                log({**intent, "result": "error", "error": f"{type(e).__name__}: {e}"})
                print(f"  order failed on {m['ticker']} {side}: {type(e).__name__} — stopping")
                return 1
        spent += cost

    print(f"\n{'sent' if live else 'would send'}: ${spent:.2f} of ${args.capital:.0f} "
          f"across {min(len(cands), args.markets)} markets"
          + (f", {sent} orders placed" if live else ""))
    print(f"intents logged to {os.path.relpath(LOG, REPO)}")
    if not live:
        print("\nDRY RUN — nothing was sent. To go live you need all of:")
        print("  1. KALSHI_PROD_KEY_ID and KALSHI_PROD_PRIVATE_KEY in the environment")
        print("  2. KALSHI_LIVE=1")
        print("  3. touch state/INCENTIVE_LIVE   (arms THIS book only)")
        print("  4. rm state/KILL_SWITCH_KALSHI")
        print("  5. --live on the command line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
