#!/usr/bin/env python3
"""Score frozen lock strategies on train, then test, then last week.

Load once. Print a compact table. Train numbers must match the scan sign.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import registry
from quantfirm.kalshi.universe import BANKROLL, SERIES, SPLIT_TS

WEEK_TS = int(__import__("datetime").datetime.fromisoformat(
    "2026-09-05T00:00:00+00:00").timestamp())


def row(m):
    return (f"n={m['n_trades']:4} pnl={m['net_pnl']:+8.2f} t={m['t_stat']:>6} "
            f"hit={m.get('hit_rate')} dd={m['max_drawdown_pct']}% "
            f"by={m.get('by_metal')}")


def main():
    specs = {s.name: s for s in registry()}
    names = ["spot_lock", "offhours_lock", "model_fav", "favorite_blind",
             "favorite_div", "rich_fav", "late_lock"]
    universes = [
        ("7series", None),
        ("5cmdty", SERIES),
    ]
    splits = [
        ("TRAIN", None, SPLIT_TS),
        ("TEST", SPLIT_TS, None),
        ("7d", WEEK_TS, None),
    ]
    bts = {}
    for uname, series in universes:
        print(f"loading {uname}...", flush=True)
        bts[uname] = Backtest(os.path.join(REPO, "data/kalshi"),
                             bankroll=BANKROLL, series=series)
    for name in names:
        spec = specs[name]
        for uname, _ in universes:
            bt = bts[uname]
            for sname, lo, hi in splits:
                print(f"{name:16} {uname:7} {sname:5} lag ...", flush=True)
                m = bt.run(spec.params, start_ts=lo, end_ts=hi, decide_fn=spec.fn)
                print(f"  {row(m)}", flush=True)


if __name__ == "__main__":
    main()
