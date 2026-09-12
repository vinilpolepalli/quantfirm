#!/usr/bin/env python3
"""Score the risky/diverse book: did any week double $250?

Lag is the headline. Touch is reported for last-minute legs only (2s-poll
ceiling). A week "doubles" if net P&L >= $250 on a $250 start.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import registry
from quantfirm.kalshi.universe import BANKROLL, SPLIT_TS

WEEK_TS = int(__import__("datetime").datetime.fromisoformat(
    "2026-09-05T00:00:00+00:00").timestamp())
DOUBLE = BANKROLL  # +100% in a calendar week


def _fmt_weeks(by_week: dict) -> str:
    if not by_week:
        return "none"
    parts = []
    for w, v in sorted(by_week.items()):
        mark = " DOUBLE" if v["pnl"] >= DOUBLE else ""
        parts.append(f"{w}:{v['pnl']:+.0f}/{v['n']}{mark}")
    return " ".join(parts)


def main():
    specs = {s.name: s for s in registry()}
    names = ["rich_fav", "sprint", "yolo_lock", "nuke_lock", "longshot",
             "yolo_follow", "yolo_book"]
    print("loading 7-series...", flush=True)
    bt = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=BANKROLL)
    splits = [
        ("TRAIN", None, SPLIT_TS),
        ("TEST", SPLIT_TS, None),
        ("7d", WEEK_TS, None),
    ]
    print(f"{'name':<12} {'split':<6} {'fill':<5} n pnl t hit dd  "
          f"best_week  doubled?", flush=True)
    for name in names:
        spec = specs[name]
        for sname, lo, hi in splits:
            p = spec.params
            m = bt.run(p, start_ts=lo, end_ts=hi, decide_fn=spec.fn)
            weeks = m.get("by_week") or {}
            best = max((v["pnl"] for v in weeks.values()), default=0.0)
            n_dbl = sum(1 for v in weeks.values() if v["pnl"] >= DOUBLE)
            print(f"{name:<12} {sname:<6} lag   "
                  f"n={m['n_trades']:4} pnl={m['net_pnl']:+8.2f} "
                  f"t={m['t_stat']:>6} hit={m.get('hit_rate')} "
                  f"dd={m['max_drawdown_pct']}% "
                  f"best={best:+.0f} dbl_weeks={n_dbl}", flush=True)
            print(f"             weeks {_fmt_weeks(weeks)}", flush=True)
        # touch ceiling on TEST for speed legs
        if name in ("sprint", "yolo_book"):
            p = replace(spec.params, fill_mode="touch")
            m = bt.run(p, start_ts=SPLIT_TS, decide_fn=spec.fn)
            weeks = m.get("by_week") or {}
            best = max((v["pnl"] for v in weeks.values()), default=0.0)
            n_dbl = sum(1 for v in weeks.values() if v["pnl"] >= DOUBLE)
            print(f"{name:<12} TEST   touch "
                  f"n={m['n_trades']:4} pnl={m['net_pnl']:+8.2f} "
                  f"t={m['t_stat']:>6} hit={m.get('hit_rate')} "
                  f"dd={m['max_drawdown_pct']}% "
                  f"best={best:+.0f} dbl_weeks={n_dbl}", flush=True)
            print(f"             weeks {_fmt_weeks(weeks)}", flush=True)


if __name__ == "__main__":
    main()
