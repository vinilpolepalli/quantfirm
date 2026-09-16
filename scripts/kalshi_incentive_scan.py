#!/usr/bin/env python3
"""Rank Kalshi Liquidity Incentive Program (LIP) markets by subsidy per $ of capital.

Public endpoints only, no credentials. Answers one question: if we rested a
two-sided quote in each subsidised market, which ones pay the most per dollar
of collateral locked, after the competition already on the book?

    python scripts/kalshi_incentive_scan.py --sample 400 --capital 1000

Scoring mirrors Kalshi's published LIP rules (help.kalshi.com article 13823851):

  * order book snapshot once per second; a snapshot is EXCLUDED unless both
    sides carry >= Target Size, so the pool only pays on a two-sided book;
  * Reference Price = walk down from the best bid until cumulative resting
    size reaches Target Size / 5;
  * an order at or better than the Reference Price scores size x 1.0, an order
    k ticks below scores size x DiscountFactor**k  -- at df=0.50 a quote five
    ticks back is worth 3% of the same size at the touch, so "park 10k
    contracts at 1c" earns approximately nothing. You must be at the top;
  * your payout = your score / everyone's score, per side, each side worth
    half the market's pool.

CAVEAT, and it is the whole ballgame: this ranks GROSS subsidy. It does not
model fills. A resting two-sided quote gets hit, and one adverse fill in a
binary that settles at 0 costs more than weeks of subsidy. Treat the output
as a candidate list for the paper loop, never as P&L.
"""
import argparse
import datetime as dt
import json
import random
import statistics
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROGRAMS = "https://external-api.kalshi.com/trade-api/v2/incentive_programs"


def _get(url, timeout=25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def fetch_programs(status="active"):
    out, cursor = [], ""
    while True:
        url = f"{PROGRAMS}?status={status}&limit=1000" + (f"&cursor={cursor}" if cursor else "")
        d = _get(url, timeout=60)
        page = d.get("incentive_programs", [])
        out += page
        cursor = d.get("next_cursor") or ""
        if not cursor or not page:
            return out


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def reference_score(levels, target_size, discount):
    """Return (reference_price, total discounted score) for one side of a book.

    levels is [(price_dollars, size)]. Mirrors the LIP reference-price walk and
    the DiscountFactor**ticks penalty.
    """
    book = sorted(levels, key=lambda z: -z[0])
    cum, ref = 0.0, None
    for price, size in book:
        cum += size
        if cum >= target_size / 5:
            ref = price
            break
    if ref is None:
        return None, 0.0          # book too thin to even set a reference price
    total = 0.0
    for price, size in book:
        ticks = round((ref - price) * 100)
        total += size * (discount ** ticks) if ticks > 0 else size
    return ref, total


def score_market(prog, horizon_h, now):
    ticker = prog["market_ticker"]
    try:
        ob = _get(f"{BASE}/markets/{ticker}/orderbook?depth=100")["orderbook_fp"]
        mk = _get(f"{BASE}/markets/{ticker}")["market"]
    except Exception:
        return None
    yes = [(_f(p), _f(s)) for p, s in (ob.get("yes_dollars") or [])]
    no = [(_f(p), _f(s)) for p, s in (ob.get("no_dollars") or [])]
    if not yes or not no:
        return None

    target = _f(prog.get("target_size_fp"))
    discount = (prog.get("discount_factor_bps") or 0) / 10000.0
    if target <= 0:
        return None
    yes_ref, yes_score = reference_score(yes, target, discount)
    no_ref, no_score = reference_score(no, target, discount)
    if yes_ref is None or no_ref is None:
        return None

    start, end = _ts(prog["start_date"]), _ts(prog["end_date"])
    duration_h = (end - start).total_seconds() / 3600.0
    window_end = now + dt.timedelta(hours=horizon_h)
    overlap_h = max(0.0, (min(end, window_end) - max(start, now)).total_seconds() / 3600.0)
    if duration_h <= 0 or overlap_h <= 0:
        return None
    reward = prog["period_reward"] / 10000.0            # centi-cents -> dollars
    # Only the slice of the pool that actually accrues inside our horizon.
    pool = reward * (overlap_h / duration_h)

    return dict(
        ticker=ticker, pool=pool, reward=reward, target=target, discount=discount,
        yes_ref=yes_ref, no_ref=no_ref, yes_score=yes_score, no_score=no_score,
        duration_h=duration_h, overlap_h=overlap_h,
        vol24=_f(mk.get("volume_24h_fp")), oi=_f(mk.get("open_interest_fp")),
        title=(mk.get("title") or "")[:60],
    )


def expected_pay(m, size):
    """Gross subsidy for resting `size` contracts per side at the reference price."""
    return m["pool"] * 0.5 * (size / (size + m["yes_score"]) + size / (size + m["no_score"]))


def collateral(m, size):
    """Cash locked: YES at ref + NO at ref. Kalshi holds max loss on each leg."""
    return size * (m["yes_ref"] + m["no_ref"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400,
                    help="programs to price (0 = all; the board is ~3.7k and each costs 2 requests)")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--horizon", type=float, default=24.0, help="hours")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--untraded-only", action="store_true",
                    help="keep only markets with zero 24h volume (lowest fill risk)")
    ap.add_argument("--max-unit-cost", type=float, default=None,
                    help="only markets where yes_ref + no_ref is at or below this (dollars per "
                         "contract-pair). 0.04 isolates books whose reference price sits at 1-2c, "
                         "where credit is cheap and a fill can cost at most a cent or two.")
    ap.add_argument("--json", help="write ranked rows here")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    progs = [p for p in fetch_programs("active")
             if p["incentive_type"] == "liquidity" and _ts(p["end_date"]) > now]
    board = 0.0
    for p in progs:
        d = (_ts(p["end_date"]) - _ts(p["start_date"])).total_seconds() / 3600.0
        ov = max(0.0, (min(_ts(p["end_date"]), now + dt.timedelta(hours=args.horizon))
                       - max(_ts(p["start_date"]), now)).total_seconds() / 3600.0)
        if d > 0:
            board += (p["period_reward"] / 10000.0) * (ov / d)
    print(f"live liquidity programs: {len(progs):,}")
    print(f"pool accruing in the next {args.horizon:.0f}h, board-wide: ${board:,.0f}")

    chosen = progs
    if args.sample and args.sample < len(progs):
        random.seed(args.seed)
        chosen = random.sample(progs, args.sample)
    print(f"pricing {len(chosen):,} books ...", file=sys.stderr)
    with ThreadPoolExecutor(24) as ex:
        rows = [r for r in ex.map(lambda p: score_market(p, args.horizon, now), chosen) if r]
    if not rows:
        print("no markets priced")
        return
    untraded = sum(1 for r in rows if r["vol24"] == 0)
    print(f"priced {len(rows):,} markets; {untraded}/{len(rows)} "
          f"({untraded / len(rows) * 100:.0f}%) had zero 24h volume")

    pool = [r for r in rows if r["vol24"] == 0] if args.untraded_only else list(rows)
    if args.max_unit_cost is not None:
        pool = [r for r in pool if r["yes_ref"] + r["no_ref"] <= args.max_unit_cost]
        print(f"{len(pool)} markets with a reference price at or under "
              f"${args.max_unit_cost:.2f} per contract-pair")

    # Pick the split of capital across N markets that maximises gross subsidy.
    best = None
    for n in (3, 5, 10, 20, 40, 80, 150, 250):
        if n > len(pool):
            break
        per = args.capital / n
        scored = []
        for m in pool:
            unit = m["yes_ref"] + m["no_ref"]
            if unit <= 0:
                continue
            size = per / unit
            if size < 25:            # sub-25-lot quotes are noise, and rewards under $1 are not paid
                continue
            scored.append((expected_pay(m, size), size, m))
        scored.sort(reverse=True, key=lambda z: z[0])
        take = scored[:n]
        if len(take) < n:
            continue
        total = sum(p for p, _, _ in take)
        if best is None or total > best[0]:
            best = (total, n, take)

    if best:
        total, n, take = best
        print(f"\nbest split of ${args.capital:,.0f}: {n} markets, "
              f"${args.capital / n:,.0f} each")
        print(f"gross subsidy over {args.horizon:.0f}h: ${total:,.2f} "
              f"= {total / args.capital * 100:.2f}% of capital")
        print(f"{'ticker':<34}{'size':>7}{'unit':>6}{'cap$':>7}{'pool$':>8}{'ours$':>8}{'%':>7}  title")
        for pay, size, m in take[:args.top]:
            cap = collateral(m, size)
            unit = m["yes_ref"] + m["no_ref"]
            flag = "" if pay >= 1.0 else "  <$1 NOT PAID"
            print(f"{m['ticker']:<34}{size:>7.0f}{unit:>6.2f}{cap:>7.0f}{m['pool']:>8.2f}"
                  f"{pay:>8.2f}{pay / cap * 100:>6.0f}%  {m['title']}{flag}")

    med = statistics.median([r["pool"] for r in rows])
    print(f"\nmedian pool per market over the horizon: ${med:.2f} "
          f"(rewards under $1.00 are not paid at all)")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rows, fh, indent=1)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
