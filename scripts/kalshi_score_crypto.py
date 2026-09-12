#!/usr/bin/env python3
"""Score BTC/ETH 15m favorite-takers vs last-minute locks.

Lag-fill is the headline. Crypto data on disk starts ~2026-08-29, after
SPLIT_TS, so TRAIN is empty — report ALL + last 7d, not a fake holdout.

A priori chill book (not a test-set fit):
  * same FLB as commodities (buy the favorite ≥60¢, hold to settle)
  * do NOT last-minute lock (one_pct touch last week: BTC −$55)
  * do NOT buy longshots or coin-flips (weekend 18–58¢ books sit out)
  * 4% stake vs 8% commodities, until close
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import favorite_blind, one_pct, registry
from quantfirm.kalshi.universe import BANKROLL, SERIES_COMPARE, SPLIT_TS

WEEK_TS = int(__import__("datetime").datetime.fromisoformat(
    "2026-09-05T00:00:00+00:00").timestamp())


def _row(name, split, m):
    by = m.get("by_metal") or {}
    metals = " ".join(
        f"{k}:{v['n']}/{v['pnl']:+.1f}/{v['hit']}"
        for k, v in sorted(by.items()))
    print(
        f"{name:<16} {split:<6} n={m['n_trades']:4} "
        f"pnl={m['net_pnl']:+8.2f} t={m['t_stat']:>6} "
        f"hit={m.get('hit_rate')} dd={m['max_drawdown_pct']}% "
        f"fill={m.get('avg_fill')} [{metals}]",
        flush=True)
    weeks = m.get("by_week") or {}
    if weeks:
        print("                 weeks " + " ".join(
            f"{w}:{v['pnl']:+.0f}/{v['n']}" for w, v in sorted(weeks.items())),
              flush=True)
    skip = m.get("skipped") or {}
    interesting = {k: v for k, v in skip.items()
                   if v and k in ("raced_out", "gapped_away", "no_quote",
                                  "no_underlying", "daily_stop", "corr_cap",
                                  "thin_depth")}
    if interesting:
        print(f"                 skip {interesting}", flush=True)


def main():
    specs = {s.name: s for s in registry()}
    print("loading BTC/ETH...", flush=True)
    bt = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=BANKROLL,
                   series=SERIES_COMPARE)
    print(f"markets btc={len(bt.markets.get('KXBTC15M', []))} "
          f"eth={len(bt.markets.get('KXETH15M', []))}", flush=True)

    rf = specs["rich_fav"]
    variants = []
    # What would happen if we dumped crypto into the commodity book.
    variants.append(("rich_fav_8pct", rf.params, favorite_blind))
    # Live overlay: every real-favorite window, chill size.
    variants.append((
        "live_60_4pct",
        replace(rf.params, price_min=0.60, price_max=0.92,
                max_stake_frac=0.04, kelly_mult=0.25,
                tau_min_s=0, tau_max_s=900),
        favorite_blind,
    ))
    # Prior ≥72¢ sleeve (fewer windows).
    variants.append((
        "crypto_fav_72",
        replace(rf.params, price_min=0.72, price_max=0.92,
                max_stake_frac=0.04, kelly_mult=0.25,
                tau_min_s=0, tau_max_s=900),
        favorite_blind,
    ))
    # A priori cautious crypto sleeve (72¢, skip last 2 min).
    variants.append((
        "crypto_fav",
        replace(rf.params, price_min=0.72, price_max=0.92,
                max_stake_frac=0.04, kelly_mult=0.25,
                tau_min_s=120, tau_max_s=780),
        favorite_blind,
    ))
    # Richer favorite, skip last 2 min.
    variants.append((
        "fav80_4pct",
        replace(rf.params, price_min=0.80, price_max=0.92,
                max_stake_frac=0.04, kelly_mult=0.25,
                tau_min_s=120, tau_max_s=780),
        favorite_blind,
    ))
    op = specs["one_pct"]
    variants.append(("one_pct_lock", op.params, one_pct))

    splits = [
        ("ALL", None, None),
        ("7d", WEEK_TS, None),
        ("TRAIN", None, SPLIT_TS),
    ]
    for name, params, fn in variants:
        for sname, lo, hi in splits:
            m = bt.run(params, start_ts=lo, end_ts=hi, decide_fn=fn)
            _row(name, sname, m)
        if name == "one_pct_lock":
            p = replace(op.params, fill_mode="touch")
            m = bt.run(p, start_ts=WEEK_TS, decide_fn=one_pct)
            _row("one_pct_touch", "7d", m)


if __name__ == "__main__":
    main()
