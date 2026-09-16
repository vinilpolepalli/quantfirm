#!/usr/bin/env python3
"""Stress-test the Kalshi LIP farming strategy. Public endpoints, no credentials.

Answers three questions the ranking scan in kalshi_incentive_scan.py cannot:

  1. DECAY    - does the edge survive? Prices every book bucketed by how long
                its program has been running. This is the one that matters:
                a thin book on a fresh program is not an inefficiency, it is
                an empty room that fills up.
  2. FILLS    - can the capital actually be lost? Walks the trade tape and
                counts prints that would have hit a resting bid at our price.
  3. DILUTION - what happens to our share as other farmers arrive.

    python scripts/kalshi_incentive_stress.py --per-bucket 45

Scoring mirrors the published LIP rules; see kalshi_incentive_scan.py for the
rule-by-rule notes. Scores are kept PER SIDE here, because payout is per side
and collapsing them understates competition by roughly 2x.
"""
import argparse
import datetime as dt
import json
import random
import statistics
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROGRAMS = "https://external-api.kalshi.com/trade-api/v2/incentive_programs"
BUCKETS = [(0, 2, "0-2h (brand new)"), (2, 12, "2-12h"), (12, 48, "12-48h"),
           (48, 168, "2-7d"), (168, 1e9, ">7d")]


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


def reference_score(levels, target_size, discount):
    """(reference price, discounted score) for ONE side. See LIP rules."""
    book = sorted(levels, key=lambda z: -z[0])
    cum, ref = 0.0, None
    for price, size in book:
        cum += size
        if cum >= target_size / 5:
            ref = price
            break
    if ref is None:
        return None, 0.0
    total = 0.0
    for price, size in book:
        ticks = round((ref - price) * 100)
        total += size * (discount ** ticks) if ticks > 0 else size
    return ref, total


def price_book(prog, now):
    ticker = prog["market_ticker"]
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
    yes_ref, yes_score = reference_score(yes, target, discount)
    no_ref, no_score = reference_score(no, target, discount)
    if yes_ref is None or no_ref is None:
        return None
    duration_h = (_ts(prog["end_date"]) - _ts(prog["start_date"])).total_seconds() / 3600.0
    if duration_h <= 0:
        return None
    return dict(
        ticker=ticker, yes_ref=yes_ref, no_ref=no_ref,
        yes_score=yes_score, no_score=no_score, target=target,
        unit=yes_ref + no_ref,
        age_h=(now - _ts(prog["start_date"])).total_seconds() / 3600.0,
        reward_per_day=(prog["period_reward"] / 10000.0) * 24 / duration_h,
    )


def earnings_per_day(m, capital):
    """Gross subsidy/day for `capital` split across both sides at the reference price.

    Payout is per side, each side worth half the pool, so score is compared
    side-by-side rather than against a pooled total.
    """
    if m["unit"] <= 0:
        return 0.0
    size = capital / m["unit"]          # contracts per side
    return m["reward_per_day"] * 0.5 * (
        size / (size + m["yes_score"]) + size / (size + m["no_score"]))


def fill_risk(ticker, our_price):
    """Count prints that would have hit a resting bid at our_price, either side."""
    try:
        trades = _get(f"{BASE}/markets/trades?ticker={ticker}&limit=1000").get("trades", [])
    except Exception:
        return None
    prices = []
    for t in trades:
        p = t.get("yes_price_dollars") or t.get("yes_price")
        if p is not None:
            prices.append(_f(p))
    if not prices:
        return dict(n=0, hits=0)
    # our YES bid fills on a print at or below it; our NO bid at (1 - our_price)
    # fills on a print at or above (1 - our_price).
    hits = sum(1 for p in prices if p <= our_price or p >= 1 - our_price)
    return dict(n=len(prices), hits=hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-bucket", type=int, default=45)
    ap.add_argument("--capital", type=float, default=100.0,
                    help="capital per market, for the per-bucket yield column")
    ap.add_argument("--seed", type=int, default=9)
    ap.add_argument("--json")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    live = [p for p in fetch_programs()
            if p["incentive_type"] == "liquidity" and _ts(p["end_date"]) > now]
    print(f"live liquidity programs: {len(live):,}\n")

    random.seed(args.seed)
    picks = []
    for lo, hi, label in BUCKETS:
        grp = [p for p in live
               if lo <= (now - _ts(p["start_date"])).total_seconds() / 3600.0 < hi]
        print(f"  {label:<18} population={len(grp):>5}")
        picks += [(label, p) for p in random.sample(grp, min(args.per_bucket, len(grp)))]

    with ThreadPoolExecutor(24) as ex:
        rows = [(lbl, m) for (lbl, m) in
                ((lbl, price_book(p, now)) for lbl, p in picks) if m]
    print(f"\npriced {len(rows)} books\n")

    print("=== 1. DECAY: does a fresh program's thin book survive? ===")
    print(f"{'program age':<18}{'n':>4}{'med unit$':>11}{'med yes-score':>15}"
          f"{'cheap<=4c':>11}{'$/day per $' + str(int(args.capital)):>17}")
    curve = {}
    for lo, hi, label in BUCKETS:
        g = [m for lbl, m in rows if lbl == label]
        if not g:
            continue
        yld = statistics.median([earnings_per_day(m, args.capital) for m in g])
        curve[label] = yld
        print(f"{label:<18}{len(g):>4}{statistics.median([m['unit'] for m in g]):>11.2f}"
              f"{statistics.median([m['yes_score'] for m in g]):>15,.0f}"
              f"{sum(1 for m in g if m['unit'] <= 0.04) / len(g) * 100:>10.0f}%"
              f"{yld:>17.2f}")
    if "0-2h (brand new)" in curve and ">7d" in curve and curve[">7d"] > 0:
        print(f"\n  decay from brand-new to >7d: "
              f"{curve['0-2h (brand new)'] / curve['>7d']:.0f}x")
    print("  A thin book on a fresh program is an empty room, not an edge.")

    print("\n=== 2. FILL RISK: can the capital actually be lost? ===")
    cheap = [m for _, m in rows if m["unit"] <= 0.10][:12]
    if not cheap:
        print("  no cheap-reference markets in this sample")
    else:
        tot_n = tot_hits = 0
        for m in cheap:
            fr = fill_risk(m["ticker"], m["yes_ref"])
            if fr:
                tot_n += fr["n"]
                tot_hits += fr["hits"]
        print(f"  {len(cheap)} cheap-reference markets: {tot_n} prints on the tape, "
              f"{tot_hits} would have hit a resting bid at our price")
        print("  Loss is bounded by what we paid: a 1c bid risks 1c/contract. "
              "Both legs filling is a WIN (YES+NO pair settles at $1).")

    print("\n=== 3. DILUTION: our share as other farmers arrive ===")
    base = [m for _, m in rows if m["unit"] <= 0.10]
    if base:
        m = min(base, key=lambda z: z["unit"])
        size = args.capital / m["unit"]
        print(f"  reference market {m['ticker']} (unit ${m['unit']:.2f}, "
              f"pool ${m['reward_per_day']:.2f}/day)")
        print(f"  {'other farmers':<16}{'our share':>11}{'$/day':>9}")
        for k in (0, 1, 2, 5, 10, 25):
            ys = m["yes_score"] + k * size
            ns = m["no_score"] + k * size
            share = 0.5 * (size / (size + ys) + size / (size + ns))
            print(f"  {k:<16}{share * 100:>10.1f}%{m['reward_per_day'] * share:>9.2f}")
        print("  Each farmer our size roughly halves what is left.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([m for _, m in rows], fh, indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
