#!/usr/bin/env python3
"""Stress-test the Kalshi LIP farming strategy. Public endpoints, no credentials.

Answers five questions the ranking scan cannot:

  1. DECAY         - does the edge survive program age?
  2. FILLS         - can the capital actually be lost?
  3. DILUTION      - what happens to our share as other farmers arrive?
  4. QUALIFYING    - how much does scoring only Target Size change competition?
  5. AGED + CHEAP  - does the 1-2c reference survive 12 hours?

    python scripts/kalshi_incentive_stress.py --per-bucket 45
"""
import argparse
import datetime as dt
import json
import os
import random
import statistics
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.incentive import (  # noqa: E402
    fetch_programs, price_many, share_for_size, ts as _ts,
)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
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


def earnings_per_day(m, capital, qual=True):
    """Gross subsidy/day for `capital` split across both sides at the T/5 ref."""
    if m["unit"] <= 0:
        return 0.0
    size = capital / m["unit"]
    ys = m["yes_score"] if qual else m["yes_full"]
    ns = m["no_score"] if qual else m["no_full"]
    return m["reward_per_hour"] * 24 * share_for_size(size, ys, ns)


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
    hits = sum(1 for p in prices if p <= our_price or p >= 1 - our_price)
    return dict(n=len(prices), hits=hits)


def _public(m):
    skip = {"yes_book", "no_book"}
    return {k: v for k, v in m.items() if k not in skip}


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

    priced = price_many([p for _, p in picks], now)
    by_ticker = {m["ticker"]: m for m in priced}
    rows = [(lbl, by_ticker[p["market_ticker"]])
            for lbl, p in picks if p["market_ticker"] in by_ticker]
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
        pool_day = m["reward_per_hour"] * 24
        print(f"  reference market {m['ticker']} (unit ${m['unit']:.2f}, "
              f"pool ${pool_day:.2f}/day)")
        print(f"  {'other farmers':<16}{'our share':>11}{'$/day':>9}")
        for k in (0, 1, 2, 5, 10, 25):
            ys = m["yes_score"] + k * size
            ns = m["no_score"] + k * size
            share = share_for_size(size, ys, ns)
            print(f"  {k:<16}{share * 100:>10.1f}%{pool_day * share:>9.2f}")
        print("  Each farmer our size roughly halves what is left.")

    print("\n=== 4. QUALIFYING vs FULL-BOOK SCORE ===")
    if rows:
        ratios = []
        for _, m in rows:
            full = m["yes_full"] + m["no_full"]
            qual = m["yes_score"] + m["no_score"]
            if full > 0:
                ratios.append(qual / full)
        if ratios:
            print(f"  median qualifying/full score: {statistics.median(ratios):.2f} "
                  f"(1.00 means the whole book is inside Target Size)")
            print("  Production uses qualifying depth. Full-book scoring was the "
                  "old scan, and it overstated competition when discount is high.")

    print("\n=== 5. AGED + CHEAP: does the empty-room edge survive 12h? ===")
    aged_cheap = [m for _, m in rows if m["age_h"] >= 12 and m["unit"] <= 0.10]
    aged = [m for _, m in rows if m["age_h"] >= 12]
    print(f"  aged >=12h in this sample: {len(aged)}")
    print(f"  of those, unit <= $0.10: {len(aged_cheap)}")
    if aged:
        print(f"  median unit among aged: ${statistics.median([m['unit'] for m in aged]):.2f}")
        print(f"  median $/day per ${int(args.capital)} among aged: "
              f"${statistics.median([earnings_per_day(m, args.capital) for m in aged]):.2f}")
    if aged_cheap:
        print("  cheap structure that survived 12h (these are the only empty-room leftovers):")
        for m in sorted(aged_cheap, key=lambda z: -earnings_per_day(z, args.capital))[:8]:
            print(f"    {m['ticker']:<34} unit ${m['unit']:.2f}  "
                  f"age {m['age_h']:.1f}h  ${earnings_per_day(m, args.capital):.2f}/day")
    else:
        print("  none. After 12h the 1-2c reference is usually gone. "
              "Selecting on $/hour without an age floor is measuring freshness.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([_public(m) for _, m in rows], fh, indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
