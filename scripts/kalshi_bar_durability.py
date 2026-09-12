#!/usr/bin/env python3
"""Lag-fill favorite-bar durability: weeks on disk, BTC and ETH independent.

Bar = each name's P&L > 0. Names may disagree. Not same-side agreement.

Crypto 15m on disk is ~2 weeks (2026-08-29 → 2026-09-12), not months.
Yahoo 1m underlying only covers ~30d, so we cannot honestly score months.

Does not change the live loop. Reproduce:

    python3 scripts/kalshi_bar_durability.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import desk_book, registry
from quantfirm.kalshi.universe import SERIES, SERIES_COMPARE, SPLIT_TS

BARS = (0.60, 0.68, 0.70, 0.72)
WAIT_S = 180
HALF_TS = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())


def _metal(m, name):
    by = m.get("by_metal") or {}
    row = by.get(name) or {"n": 0, "pnl": 0.0, "hit": 0}
    return row.get("n") or 0, float(row.get("pnl") or 0), row.get("hit")


def _weeks(m, names):
    settled = m.get("trades") or []
    buckets = defaultdict(lambda: defaultdict(lambda: {"n": 0, "pnl": 0.0}))
    for t in settled:
        if t.metal not in names:
            continue
        w = datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).strftime("%G-W%V")
        buckets[w][t.metal]["n"] += 1
        buckets[w][t.metal]["pnl"] += t.pnl
    return buckets


def _fn(bar: float, wait: int = WAIT_S):
    def fn(**kw):
        return desk_book(**kw, price_min_ov=bar, wait_s=wait)
    return fn


def _print_row(label, m, names):
    parts = []
    both = True
    for name in names:
        n, pnl, hit = _metal(m, name)
        parts.append(f"{name} n={n:3} {pnl:+7.1f} hit={hit}")
        both = both and n > 0 and pnl > 0
    print(
        f"{label:<22} n={m['n_trades']:4} pnl={m['net_pnl']:+8.1f} "
        f"t={str(m.get('t_stat')):>6}  {' | '.join(parts)}  "
        f"{'BOTH' if both else 'no'}",
        flush=True,
    )
    weeks = _weeks(m, names)
    for w in sorted(weeks):
        bits = " ".join(
            f"{name}:{weeks[w][name]['pnl']:+.1f}/{weeks[w][name]['n']}"
            for name in names if weeks[w][name]["n"]
        )
        print(f"{'':22} {w} {bits}", flush=True)


def main():
    specs = {s.name: s for s in registry()}
    params = specs["desk_book"].params

    print("=== crypto wait3, full tape (BTC+ETH independent) ===", flush=True)
    bt_c = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=250,
                    series=SERIES_COMPARE)
    print(f"btc markets={len(bt_c.markets.get('KXBTC15M', []))} "
          f"eth markets={len(bt_c.markets.get('KXETH15M', []))}", flush=True)
    for bar in BARS:
        m = bt_c.run(params, decide_fn=_fn(bar))
        _print_row(f"wait3_{int(bar*100)}", m, ("btc", "eth"))

    print("\n=== crypto wait3+68 halves (walk-forward on the 2w tape) ===",
          flush=True)
    for label, lo, hi in (("first_half", None, HALF_TS),
                          ("second_half", HALF_TS, None)):
        m = bt_c.run(params, start_ts=lo, end_ts=hi, decide_fn=_fn(0.68))
        _print_row(f"68_{label}", m, ("btc", "eth"))
        m60 = bt_c.run(params, start_ts=lo, end_ts=hi, decide_fn=_fn(0.60))
        _print_row(f"60_{label}", m60, ("btc", "eth"))

    print("\n=== commodities wait3 60 vs 68 (test = post 2026-08-27) ===",
          flush=True)
    bt_m = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=250,
                    series=SERIES)
    names = ("gold", "silver", "copper", "wti", "natgas")
    for bar in (0.60, 0.68):
        m = bt_m.run(params, start_ts=SPLIT_TS, decide_fn=_fn(bar))
        _print_row(f"cmdty{int(bar*100)}_test", m, names)


if __name__ == "__main__":
    main()
