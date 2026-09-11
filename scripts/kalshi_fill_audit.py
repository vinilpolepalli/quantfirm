#!/usr/bin/env python3
"""Audit how much of the shadow maker P&L survives pessimistic fill assumptions.

The live maker leg is a SHADOW: it never rests a real order, so it is granted
queue priority it would have to earn. `PaperEngine._maker_filled` decides a
fill from the public tape alone:

    return thru >= q.count or at >= 3 * q.count

That rule cannot see (a) how much size rests ahead of us at our own price,
(b) whether our cancel would have won the race against the taker who filled
us, or (c) how the book would have reacted to our quote actually being in it.
So the headline P&L is an UPPER BOUND, not an estimate.

This script quantifies how far the result is from zero under the stress that
matters — adverse selection — and prints the statistics that discriminate a
real edge from a fill-mechanics artifact.

    python3 scripts/kalshi_fill_audit.py [--adapter maker] [--trades PATH]

Exit status is 0 always; this is a report, not a gate.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import statistics as st
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES = os.path.join(REPO, "state", "kalshi_paper_trades.csv")


def tstat(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    sd = st.stdev(xs)
    return st.mean(xs) / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0


def window_of(ticker: str) -> str:
    """KXGOLD15M-26SEP111900-00 -> 26SEP111900-00 (shared across metals)."""
    return ticker.split("-", 1)[1] if "-" in ticker else ticker


def section(title: str):
    print(f"\n{title}\n" + "-" * len(title))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="maker", help="maker | shadow")
    ap.add_argument("--trades", default=TRADES)
    ap.add_argument("--boots", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    with open(a.trades) as f:
        rows = [r for r in csv.DictReader(f) if r["adapter"] == a.adapter]
    if not rows:
        print(f"no {a.adapter} fills in {a.trades}")
        return

    pnl = [float(r["pnl"]) for r in rows]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    n, Sw, Sl = len(pnl), sum(wins), sum(losses)

    section(f"SAMPLE ({a.adapter})")
    print(f"fills            {n}")
    print(f"net P&L          ${sum(pnl):+.2f}")
    print(f"hit rate         {len(wins)/n:.3f}")
    print(f"avg win / loss   ${st.mean(wins):.2f} / ${st.mean(losses):.2f}"
          if wins and losses else "")
    be = abs(st.mean(losses)) / (st.mean(wins) + abs(st.mean(losses))) \
        if wins and losses else float("nan")
    print(f"break-even hit   {be:.3f}   cushion {100*(len(wins)/n - be):+.2f}pp")
    print(f"sides taken      {dict(Counter(r['side'] for r in rows))}")

    # ---------------------------------------------------------- independence
    section("INDEPENDENCE (is the t-stat inflated by correlated windows?)")
    byw = defaultdict(list)
    for r in rows:
        byw[window_of(r["ticker"])].append(float(r["pnl"]))
    multi = [v for v in byw.values() if len(v) > 1]
    agree = sum(1 for v in multi
                if all(x > 0 for x in v) or all(x <= 0 for x in v))
    print(f"distinct windows {len(byw)}  ({n/len(byw):.2f} fills per window)")
    if multi:
        print(f"multi-leg windows {len(multi)}, legs agree {agree} "
              f"({agree/len(multi):.0%} — 50% would mean independent)")
    print(f"t per-fill       {tstat(pnl):.2f}")
    print(f"t per-window     {tstat([sum(v) for v in byw.values()]):.2f}"
          "   <- use this one if it is LOWER")

    # ------------------------------------------------- adverse selection
    section("ADVERSE-SELECTION STRESS (the assumption that actually matters)")
    print("A real resting order is filled preferentially when the taker has a")
    print("reason. Model that by deleting a fraction of the WINNING fills (the")
    print("ones that, in reality, nobody would have traded against) while")
    print("keeping every loss. How much phantom profit can this survive?")
    print()
    if Sw > 0:
        phi_star = 1.0 + Sl / Sw
        print(f"break-even haircut  {phi_star:6.1%} of winning fills may be "
              f"phantom before the edge is zero")
    print(f"{'haircut':>9} {'P&L':>11} {'hit':>7} {'t':>7}")
    for phi in (0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75):
        keep = int(round(len(wins) * (1 - phi)))
        rng = random.Random(a.seed)
        sub = rng.sample(wins, keep) + losses
        print(f"{phi:>8.0%} {sum(sub):>10.2f} "
              f"{keep/len(sub) if sub else 0:>7.3f} {tstat(sub):>7.2f}")

    # ------------------------------------------------------------ bootstrap
    section("BOOTSTRAP (sampling error on the observed result)")
    rng = random.Random(a.seed)
    tot = sorted(sum(rng.choices(pnl, k=n)) for _ in range(a.boots))
    lo, hi = tot[int(0.025 * a.boots)], tot[int(0.975 * a.boots)]
    print(f"95% CI on net P&L   ${lo:+.2f} .. ${hi:+.2f}")
    print(f"P(net P&L > 0)      {sum(1 for x in tot if x > 0)/a.boots:.1%}")

    # --------------------------------------------------------------- verdict
    section("VERDICT")
    t = tstat(pnl)
    if t < 1.96:
        print(f"t = {t:.2f} < 1.96 — NOT significant. The sample cannot yet")
        print("distinguish a real edge from zero, before any haircut is applied.")
    else:
        print(f"t = {t:.2f} >= 1.96 at face value, but see the haircut table:")
        print("the shadow fill rule is an upper bound, so treat this as the")
        print("optimistic end of a range, not a point estimate.")
    print()
    print("BLOCKER: state/kalshi_paper_decisions.jsonl logs quotes only, not the")
    print("trades tape, so _maker_filled cannot be replayed offline against a")
    print("stricter queue model. Persisting the tape is prerequisite to any")
    print("fill model better than the guesses above. See docs/HANDOFF.md.")


if __name__ == "__main__":
    main()
