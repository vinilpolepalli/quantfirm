#!/usr/bin/env python3
"""Sweep wait × favorite-bar (1¢) for independent BTC and ETH P&L.

Live-relevant: mixed 7-name book, lag-fill, $250. Names may disagree.
Tape is ~2 weeks of 15m crypto, not months.

    python3 scripts/kalshi_param_sweep.py
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

LAST7 = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
WAITS = (0, 60, 120, 180, 240, 300, 420)
BARS = tuple(round(x / 100, 2) for x in range(60, 81))  # 0.60 .. 0.80
TAU_MINS = (0, 60, 120)
PRICE_MAXS = (0.90, 0.92, 0.94)


def _fn(bar, wait, tau_min=None, price_max=None):
    def fn(**kw):
        extra = dict(price_min_ov=bar, wait_s=wait)
        if tau_min is not None:
            extra["tau_min_ov"] = tau_min
        if price_max is not None:
            extra["price_max_ov"] = price_max
        return desk_book(**kw, **extra)
    return fn


def _crypto(trades):
    out = defaultdict(lambda: {"n": 0, "pnl": 0.0, "hit": 0})
    for t in trades:
        if t.metal not in ("btc", "eth"):
            continue
        out[t.metal]["n"] += 1
        out[t.metal]["pnl"] += t.pnl
        if t.pnl > 0:
            out[t.metal]["hit"] += 1
    return out


def _weeks(trades):
    buckets = defaultdict(lambda: defaultdict(lambda: {"n": 0, "pnl": 0.0}))
    for t in trades:
        if t.metal not in ("btc", "eth"):
            continue
        w = datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).strftime("%G-W%V")
        buckets[w][t.metal]["n"] += 1
        buckets[w][t.metal]["pnl"] += t.pnl
    return buckets


def _row(label, trades):
    c = _crypto(trades)
    last = _crypto([t for t in trades if t.entry_ts >= LAST7])
    weeks = _weeks(trades)
    btc, eth = c["btc"], c["eth"]
    b7, e7 = last["btc"], last["eth"]
    both = btc["n"] > 0 and eth["n"] > 0 and btc["pnl"] > 0 and eth["pnl"] > 0
    both7 = b7["n"] > 0 and e7["n"] > 0 and b7["pnl"] > 0 and e7["pnl"] > 0
    week_both = 0
    week_bits = []
    for w in sorted(weeks):
        bp, ep = weeks[w]["btc"]["pnl"], weeks[w]["eth"]["pnl"]
        week_bits.append(f"{w} btc:{bp:+.0f} eth:{ep:+.0f}")
        if weeks[w]["btc"]["n"] and weeks[w]["eth"]["n"] and bp > 0 and ep > 0:
            week_both += 1
    return {
        "label": label,
        "btc_n": btc["n"], "btc": round(btc["pnl"], 2),
        "eth_n": eth["n"], "eth": round(eth["pnl"], 2),
        "min_name": round(min(btc["pnl"], eth["pnl"]), 2),
        "sum": round(btc["pnl"] + eth["pnl"], 2),
        "both": both, "both7": both7, "week_both": week_both,
        "btc7": round(b7["pnl"], 2), "eth7": round(e7["pnl"], 2),
        "weeks": "; ".join(week_bits),
    }


def _print(r):
    flag = ("BOTH" if r["both"] else "no") + ("+7d" if r["both7"] else "")
    print(
        f"{r['label']:<22} btc n={r['btc_n']:3} {r['btc']:+7.1f}  "
        f"eth n={r['eth_n']:3} {r['eth']:+7.1f}  min={r['min_name']:+7.1f}  "
        f"sum={r['sum']:+7.1f}  wboth={r['week_both']}  {flag}",
        flush=True,
    )


def main():
    params = next(s for s in registry() if s.name == "desk_book").params
    print("loading mixed 7-name book...", flush=True)
    bt = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=250)
    rows = []
    print(f"{'cfg':<22} {'btc':>16} {'eth':>16} {'min':>8} {'sum':>8} weeks both",
          flush=True)
    for wait in WAITS:
        print(f"-- wait {wait}s ---", flush=True)
        for bar in BARS:
            m = bt.run(params, decide_fn=_fn(bar, wait))
            r = _row(f"w{wait:03d}_{int(round(bar*100)):02d}", m["trades"])
            rows.append(r)
            if r["both"] or (wait == 180 and bar in (0.60, 0.68, 0.70, 0.72)):
                _print(r)
                print(f"{'':22} {r['weeks']}", flush=True)

    hits = [r for r in rows if r["both"] and r["both7"]]
    print(f"\n=== BOTH on ALL and last 7d: {len(hits)} ===", flush=True)
    hits.sort(key=lambda r: (r["week_both"], r["min_name"], r["sum"]),
              reverse=True)
    for r in hits[:20]:
        _print(r)
        print(f"{'':22} {r['weeks']}", flush=True)

    print("\n=== top 15 by min(BTC,ETH) even if not both-green ===", flush=True)
    rest = sorted(rows, key=lambda r: (r["min_name"], r["sum"]), reverse=True)
    for r in rest[:15]:
        _print(r)

    live = next(r for r in rows if r["label"] == "w180_68")
    print("\n=== vs live wait3+68 ===", flush=True)
    _print(live)
    better = [r for r in rows
              if r["both"] and r["both7"]
              and r["min_name"] > live["min_name"]
              and r["sum"] > live["sum"]]
    print(f"strictly better min+sum and both+7d: {len(better)}", flush=True)
    for r in better:
        _print(r)
        print(f"{'':22} {r['weeks']}", flush=True)

    if hits:
        best = hits[0]
        wait = int(best["label"].split("_")[0][1:])
        bar = int(best["label"].split("_")[1]) / 100
        print(f"\n=== extra tau_min / price_max on {best['label']} ===",
              flush=True)
        for tau in TAU_MINS:
            for pmax in PRICE_MAXS:
                m = bt.run(params, decide_fn=_fn(bar, wait, tau, pmax))
                r = _row(f"{best['label']}_t{tau}_x{int(pmax*100)}",
                         m["trades"])
                _print(r)


if __name__ == "__main__":
    main()
