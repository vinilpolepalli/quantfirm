#!/usr/bin/env python3
"""Measure the maker edge from the public tape, WITHOUT a queue model.

Why this exists
---------------
docs/KALSHI.md 3b says the shadow maker P&L rests on an unverified fill rule
(`_maker_filled`: trade THROUGH our price, or 3x our size AT it). The 3x is a
guess about queue position, and queue position is not observable from public
data. Open problem 2 in docs/HANDOFF.md asked for a better queue model.

This sidesteps the queue entirely. Every print on the public tape had a real
passive counterparty -- a resting maker order that actually filled, at a real
price, at a real moment, ahead of everyone behind it. So the tape IS the
population of achievable maker fills, and we can ask what that passive side
earned without assuming anything about our own queue position.

Passive P&L per contract, settle = 1 if YES resolved true else 0:
    taker bought YES at p  -> passive SOLD yes    -> pnl = p - settle
    taker bought NO        -> passive BOUGHT yes  -> pnl = settle - p
Makers pay no Kalshi fee, so that is the whole of it.

THE UNIT OF OBSERVATION IS THE MARKET, NOT THE PRINT
----------------------------------------------------
This is the entire methodological point of the script, and getting it wrong
produces spectacular nonsense. A 15-minute market carries ~1,000 prints that
all settle on ONE draw of the underlying. Their P&Ls are not 1,000
observations; they are one observation measured 1,000 times. Treating prints
as independent inflates t by roughly sqrt(prints per market) ~ 30x.

Measured on this tape, the difference is not academic:

    bucket            per-print t     per-market t
    underdog maker        +23.34           +0.38
    favorite maker        -12.98           -0.01

The per-print column says "resting on the underdog is a huge edge and resting
on the favorite bleeds." The per-market column -- the honest one -- says there
is no measurable edge on either side. Both columns come from the same rows.

So the script reports per-market as the headline and prints the per-print
number only in a block labelled as the trap it is.
"""
from __future__ import annotations

import bisect
import collections
import glob
import json
import math
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.client import KalshiClient  # noqa: E402

TAPE_GLOB = "state/kalshi_tape_*.jsonl"
DECISIONS = "state/kalshi_paper_decisions.jsonl"
SETTLE_CACHE = "state/kalshi_settlements.json"
LAG_S = 60.0


def load_tape() -> list[dict]:
    rows, seen = [], set()
    for f in sorted(glob.glob(TAPE_GLOB)):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            tid = r.get("trade_id")
            if tid in seen:
                continue
            seen.add(tid)
            rows.append(r)
    return rows


def load_settlements(tickers: list[str]) -> dict[str, int]:
    """ticker -> 1 if YES resolved, 0 if NO. Unsettled markets are omitted and
    retried next run rather than cached, so an open market never poisons it."""
    cache = {}
    if os.path.exists(SETTLE_CACHE):
        cache = json.load(open(SETTLE_CACHE))
    missing = [t for t in tickers if t not in cache]
    if missing:
        c = KalshiClient(env="prod")
        for t in missing:
            try:
                m = c.get_market(t)
            except Exception as e:
                print(f"  settle fetch failed {t}: {e}", file=sys.stderr)
                continue
            res = (m.get("result") or "").lower()
            if res in ("yes", "no"):
                cache[t] = 1 if res == "yes" else 0
        os.makedirs(os.path.dirname(SETTLE_CACHE), exist_ok=True)
        json.dump(cache, open(SETTLE_CACHE, "w"), indent=0, sort_keys=True)
    return {t: v for t, v in cache.items() if v in (0, 1)}


def verify_taker_semantics(tape: list[dict]) -> str:
    """Everything below flips sign if `taker_outcome_side` does not mean what
    we think. It is not documented unambiguously, and the joint distribution
    with `taker_book_side` is degenerate ('yes'->'bid', 'no'->'ask'), which
    reads backwards. So resolve it against books we recorded ourselves: a
    taker buying YES lifts the yes ask; a taker buying NO lifts the no ask,
    which is the yes bid. Prints should land accordingly."""
    if not os.path.exists(DECISIONS):
        return "  (no decisions log -- semantics UNVERIFIED on this machine)"
    snap = collections.defaultdict(list)
    for line in open(DECISIONS):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("bid") is None or d.get("ask") is None:
            continue
        snap[d["ticker"]].append((d["ts"], float(d["bid"]), float(d["ask"])))
    for v in snap.values():
        v.sort()
    keys = {k: [x[0] for x in v] for k, v in snap.items()}
    tab = collections.Counter()
    for r in tape:
        v = snap.get(r["ticker"])
        if not v:
            continue
        try:
            t = datetime.fromisoformat(
                r["created_time"].replace("Z", "+00:00")).timestamp()
            p = float(r["yes_price_dollars"])
        except Exception:
            continue
        ks = keys[r["ticker"]]
        i = bisect.bisect_left(ks, t)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(ks) and abs(ks[j] - t) <= 5:
                if best is None or abs(ks[j] - t) < abs(best[0] - t):
                    best = v[j]
        if best is None or best[1] >= best[2]:
            continue
        _, b, a = best
        side = r.get("taker_outcome_side") or r.get("taker_side")
        if abs(p - a) < 1e-9:
            tab[(side, "ask")] += 1
        elif abs(p - b) < 1e-9:
            tab[(side, "bid")] += 1
    ya, yb = tab[("yes", "ask")], tab[("yes", "bid")]
    na, nb = tab[("no", "ask")], tab[("no", "bid")]
    ok = ya > yb and nb > na
    return (f"  taker 'yes' at ask/bid = {ya}/{yb}   taker 'no' at ask/bid = "
            f"{na}/{nb}\n  -> mapping "
            f"{'CONFIRMED' if ok else 'CONTRADICTED -- every sign below is suspect'}")


def build(tape: list[dict], settle: dict[str, int]) -> list[dict]:
    by = collections.defaultdict(list)
    for r in tape:
        if r["ticker"] not in settle:
            continue
        try:
            t = datetime.fromisoformat(
                r["created_time"].replace("Z", "+00:00")).timestamp()
            p = float(r["yes_price_dollars"])
            c = float(r["count_fp"])
        except Exception:
            continue
        if c <= 0 or not (0.0 < p < 1.0):
            continue
        side = r.get("taker_outcome_side") or r.get("taker_side")
        if side not in ("yes", "no"):
            continue
        by[r["ticker"]].append((t, p, c, side))
    recs = []
    for tk, v in by.items():
        v.sort()
        s = settle[tk]
        ts = [x[0] for x in v]
        for t, p, c, side in v:
            if side == "yes":                 # passive sold yes -> long NO at 1-p
                pnl, ppx = p - s, 1.0 - p
            else:                             # passive bought yes at p
                pnl, ppx = s - p, p
            # Bucketing by a print's OWN price conditions on that print's noise:
            # with p = pi + eps, selecting p < 0.5 selects eps < 0 and manufactures
            # a positive edge. Bucket on a price at least LAG_S old instead -- it
            # cannot contain this print's noise. (On this tape the correction
            # barely moves the per-print numbers; the market clustering is what
            # actually kills them. Both checks are kept because either one alone
            # would have let a false result through.)
            j = bisect.bisect_right(ts, t - LAG_S) - 1
            lag = None
            if j >= 0:
                lp = v[j][1]
                lag = (1.0 - lp) if side == "yes" else lp
            recs.append({"pnl": pnl, "c": c, "ppx": ppx, "lag": lag,
                         "tkr": tk, "side": side, "metal": tk.split("-")[0]})
    return recs


def per_market(rs: list[dict]) -> tuple[int, float, float]:
    """Equal-weight mean over markets, and its t. One market = one settlement
    draw = one observation."""
    per = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rs:
        per[r["tkr"]][0] += r["pnl"] * r["c"]
        per[r["tkr"]][1] += r["c"]
    vals = [a / b for a, b in per.values() if b > 0]
    if len(vals) < 2:
        return len(vals), 0.0, 0.0
    mu = statistics.mean(vals)
    se = statistics.stdev(vals) / math.sqrt(len(vals))
    return len(vals), mu, (mu / se if se > 0 else 0.0)


def per_print_t(rs: list[dict]) -> float:
    n = len(rs)
    w = sum(r["c"] for r in rs)
    if n < 2 or w <= 0:
        return 0.0
    mu = sum(r["pnl"] * r["c"] for r in rs) / w
    var = sum(r["c"] * (r["pnl"] - mu) ** 2 for r in rs) / w
    return mu / math.sqrt(var / n) if var > 0 else 0.0


def markets_needed(mu: float, t_target: float = 3.0, have: int = 0,
                   t_have: float = 0.0) -> float:
    """How many markets to reach t_target if the observed effect is real."""
    if have < 2 or abs(t_have) < 1e-9:
        return float("inf")
    return have * (t_target / abs(t_have)) ** 2


def main() -> int:
    tape = load_tape()
    if not tape:
        print("no tape found -- run the paper engine first")
        return 1
    tickers = sorted({r["ticker"] for r in tape})
    settle = load_settlements(tickers)
    recs = build(tape, settle)
    if not recs:
        print("no settled prints")
        return 1

    print("=" * 74)
    print("PASSIVE (MAKER) EDGE FROM THE PUBLIC TAPE -- no queue model assumed")
    print("=" * 74)
    print(f"prints {len(tape):,}   markets {len(tickers)} "
          f"({len(settle)} settled, {len(tickers) - len(settle)} dropped)")
    print()
    print("taker-side semantics (everything flips if this is wrong):")
    print(verify_taker_semantics(tape))
    print()

    buckets = [
        ("ALL passive fills", lambda r: True),
        ("underdog  ppx 0.10-0.50", lambda r: r["lag"] is not None and 0.10 <= r["lag"] < 0.50),
        ("favorite  ppx 0.50-0.90", lambda r: r["lag"] is not None and 0.50 <= r["lag"] < 0.90),
        ("gold", lambda r: r["metal"] == "KXGOLD15M"),
        ("silver", lambda r: r["metal"] == "KXSILVER15M"),
    ]
    print("-" * 74)
    print("HEADLINE -- one observation per market (the honest unit)")
    print("-" * 74)
    print(f"  {'bucket':<26}{'markets':>9}{'c/contract':>13}{'t':>8}"
          f"{'markets for t=3':>18}")
    for name, sel in buckets:
        rs = [r for r in recs if sel(r)]
        if not rs:
            continue
        n, mu, t = per_market(rs)
        need = markets_needed(mu, 3.0, n, t)
        need_s = "n/a" if need == float("inf") else f"{need:,.0f}"
        print(f"  {name:<26}{n:>9}{100 * mu:>13.3f}{t:>8.2f}{need_s:>18}")
    print()
    print("  Nothing here clears the docs/FIRM.md gate of |t| >= 3. At ~192")
    print("  markets/day across gold+silver, the last column is roughly days of")
    print("  UNINTERRUPTED 24h tape needed -- divide by the duty cycle for the")
    print("  real wait (docs/HANDOFF.md 2b).")
    print()

    print("-" * 74)
    print("THE TRAP -- the same rows, counted per print")
    print("-" * 74)
    print(f"  {'bucket':<26}{'prints':>9}{'c/contract':>13}{'t':>8}")
    for name, sel in buckets:
        rs = [r for r in recs if sel(r)]
        if not rs:
            continue
        cc = sum(r["c"] for r in rs)
        pp = sum(r["pnl"] * r["c"] for r in rs)
        print(f"  {name:<26}{len(rs):>9,}{100 * pp / cc:>13.3f}"
              f"{per_print_t(rs):>8.2f}")
    print()
    print("  These t-stats are ~30x too large and mean nothing. Every print in a")
    print("  15-minute market settles on the SAME draw. Do not quote this block.")
    print()

    print("=" * 74)
    print("WHAT THIS SETTLES")
    print("=" * 74)
    print("""
1. The queue model was never the binding constraint. Even granting a maker
   PERFECT queue priority -- which is what the tape's passive side represents,
   since those orders really did fill -- the edge is not distinguishable from
   zero on this sample. Tuning `_maker_filled`'s 3x guess cannot rescue a
   strategy whose achievable fills have no measurable edge.
2. It does not show the maker thesis is WRONG. It shows this much tape cannot
   test it. The confidence interval is wide enough to contain a good business
   and a bad one; see the 'markets for t=3' column for the cost of finding out.
3. A maker who quoted everything is not our strategy, which rests one side at
   fair-minus-margin on a signal. This is the ceiling-shaped question ('is
   there anything to capture'), not the strategy question.
4. The per-print/per-market gap above is the fourth time in this project that
   instrumentation, not the market, produced the interesting number. Cluster
   first, believe later.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
