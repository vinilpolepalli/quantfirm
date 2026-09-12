#!/usr/bin/env python3
"""Score OSS / overlay takers vs desk_book. Bar: BTC AND ETH both green.

Does not change the live loop. Fill model is lag. Bankroll $250.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import registry
from quantfirm.kalshi.universe import SPLIT_TS

SINCE_7D = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())

NAMES = (
    "desk_book",
    "rich_fav",
    "crypto_fav",
    "favorite_div",
    "wait7_book",
    "persist_book",
    "tight_book",
    "late_sit_book",
    "richer_wait",
    "settle_ride",
    "longshot_no",
    "dir_zone",
    "same_side_book",
    "spot_desk",
    "no_eth_book",
)


def _row(name, split, m):
    by = m.get("by_metal") or {}
    btc = by.get("btc") or {"n": 0, "pnl": 0.0, "hit": 0}
    eth = by.get("eth") or {"n": 0, "pnl": 0.0, "hit": 0}
    cmd = sum((by.get(x) or {}).get("pnl") or 0
               for x in ("gold", "silver", "copper", "wti", "natgas"))
    both = (btc.get("n") or 0) > 0 and (eth.get("n") or 0) > 0 \
        and (btc.get("pnl") or 0) > 0 and (eth.get("pnl") or 0) > 0
    return {
        "name": name, "split": split, "n": m["n_trades"],
        "pnl": m["net_pnl"], "t": m.get("t_stat"), "hit": m.get("hit_rate"),
        "dd": m.get("max_drawdown_pct"),
        "btc_n": btc.get("n"), "btc": btc.get("pnl"), "btc_hit": btc.get("hit"),
        "eth_n": eth.get("n"), "eth": eth.get("pnl"), "eth_hit": eth.get("hit"),
        "cmd": round(cmd, 2), "both": both,
    }


def main():
    bt = Backtest("data/kalshi", bankroll=250)
    specs = {s.name: s for s in registry()}
    splits = (
        ("test", SPLIT_TS, None),
        ("last7d", SINCE_7D, None),
    )
    rows = []
    print(f"{'name':16} {'split':6} {'n':5} {'pnl':8} {'t':6} "
          f"{'btc_n':5} {'btc':8} {'eth_n':5} {'eth':8} {'cmd':8} both")
    for name in NAMES:
        spec = specs[name]
        for split, lo, hi in splits:
            m = bt.run(spec.params, start_ts=lo, end_ts=hi, decide_fn=spec.fn)
            r = _row(name, split, m)
            rows.append(r)
            flag = "YES" if r["both"] else "no"
            print(f"{name:16} {split:6} {r['n']:5} {r['pnl']:8.1f} {str(r['t']):6} "
                  f"{r['btc_n']:5} {r['btc']:8} {r['eth_n']:5} {r['eth']:8} "
                  f"{r['cmd']:8} {flag}", flush=True)

    print("\n=== both BTC and ETH green ===")
    hits = [r for r in rows if r["both"]]
    if not hits:
        print("NONE")
    for r in hits:
        print(r)
    return rows


if __name__ == "__main__":
    main()
