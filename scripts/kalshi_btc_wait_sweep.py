#!/usr/bin/env python3
"""BTC-only wait × favorite-bar sweep. Longer waits for open flicker.

Live stays wait-3 + 75¢ on the mixed book. This does not change it.

BTC 15m is jumpy in the first minutes. Question: sit longer on BTC
(4–12 min) at different bars, leave ETH/commodities on live wait-3+75.

Tape is ~2 weeks (2026-08-28 → 2026-09-12), not months.

    python3 scripts/kalshi_btc_wait_sweep.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import Backtest
from quantfirm.kalshi.strategies import desk_book, registry
from quantfirm.kalshi.universe import SERIES_COMPARE

LAST7 = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
# 0, 2 min, live 3 min, then 4–12 min (window is 15).
WAITS = (0, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660, 720)
BARS = tuple(round(x / 100, 2) for x in range(60, 83))  # 60–82¢
OUT_JSON = os.path.join(REPO, "research", "kalshi_btc_wait.json")
OUT_MD = os.path.join(REPO, "research", "kalshi_btc_wait.md")
LIVE = ("w180_75", 180, 0.75)


def _fn(bar, wait):
    def fn(**kw):
        return desk_book(**kw, price_min_ov=bar, wait_s=wait)
    return fn


def _btc_wait_fn(btc_wait, btc_bar, eth_wait=180, eth_bar=0.75):
    """Deployable overlay: only BTC wait/bar changes."""
    def fn(**kw):
        metal = kw.get("metal")
        if metal == "btc":
            return desk_book(**kw, wait_s=btc_wait, price_min_ov=btc_bar)
        if metal == "eth":
            return desk_book(**kw, wait_s=eth_wait, price_min_ov=eth_bar)
        return desk_book(**kw)
    return fn


def _weeks(trades, metal="btc"):
    buckets = defaultdict(lambda: {"n": 0, "pnl": 0.0, "hit": 0})
    for t in trades:
        if t.metal != metal:
            continue
        w = datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).strftime("%G-W%V")
        buckets[w]["n"] += 1
        buckets[w]["pnl"] += t.pnl
        if t.pnl > 0:
            buckets[w]["hit"] += 1
    return buckets


def _weekend(trades, metal="btc"):
    n = pnl = hit = 0
    for t in trades:
        if t.metal != metal:
            continue
        wd = datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).weekday()
        if wd >= 5:
            n += 1
            pnl += t.pnl
            if t.pnl > 0:
                hit += 1
    return {"n": n, "pnl": round(pnl, 2),
            "hit": round(hit / n, 3) if n else None}


def _btc_row(label, trades):
    btc = [t for t in trades if t.metal == "btc"]
    last = [t for t in btc if t.entry_ts >= LAST7]
    n = len(btc)
    pnl = sum(t.pnl for t in btc)
    hit = sum(1 for t in btc if t.pnl > 0)
    n7 = len(last)
    pnl7 = sum(t.pnl for t in last)
    hit7 = sum(1 for t in last if t.pnl > 0)
    weeks = _weeks(btc)
    week_bits = []
    week_green = 0
    for w in sorted(weeks):
        p = weeks[w]["pnl"]
        week_bits.append(f"{w}:{p:+.0f}/{weeks[w]['n']}")
        if weeks[w]["n"] and p > 0:
            week_green += 1
    we = _weekend(btc)
    avg = (pnl / n) if n else 0.0
    return {
        "label": label,
        "n": n,
        "pnl": round(pnl, 2),
        "hit": round(hit / n, 3) if n else None,
        "avg": round(avg, 3),
        "n7": n7,
        "pnl7": round(pnl7, 2),
        "hit7": round(hit7 / n7, 3) if n7 else None,
        "week_green": week_green,
        "weeks": "; ".join(week_bits),
        "weekend_n": we["n"],
        "weekend_pnl": we["pnl"],
        "weekend_hit": we["hit"],
        "green": n > 0 and pnl > 0,
        "green7": n7 > 0 and pnl7 > 0,
    }


def _print(r):
    h = "—" if r["hit"] is None else f"{r['hit']:.2f}"
    print(
        f"{r['label']:<12} n={r['n']:3} {r['pnl']:+7.1f} hit={h:>5}  "
        f"7d n={r['n7']:3} {r['pnl7']:+7.1f}  "
        f"wknd {r['weekend_pnl']:+6.1f} n={r['weekend_n']:3}  "
        f"wgreen={r['week_green']}  "
        f"{'GREEN' if r['green'] else 'red'}"
        f"{'+7d' if r['green7'] else ''}",
        flush=True,
    )


def _parse(label):
    # w180_75
    a, b = label.split("_")
    return int(a[1:]), int(b) / 100.0


def main():
    params = next(s for s in registry() if s.name == "desk_book").params
    print("loading BTC-only book...", flush=True)
    bt_b = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=250,
                    series={"KXBTC15M": "btc"})
    n_mkt = len(bt_b.markets.get("KXBTC15M") or [])
    print(f"btc markets={n_mkt} waits={len(WAITS)} bars={len(BARS)} "
          f"grid={len(WAITS)*len(BARS)}", flush=True)

    rows = []
    for wait in WAITS:
        print(f"-- BTC wait {wait}s ({wait/60:.0f} min) ---", flush=True)
        for bar in BARS:
            m = bt_b.run(params, decide_fn=_fn(bar, wait))
            r = _btc_row(f"w{wait:03d}_{int(round(bar*100)):02d}", m["trades"])
            rows.append(r)
            if (wait, bar) == (180, 0.75) or (r["green"] and r["green7"]
                                             and r["pnl"] >= 70):
                _print(r)

    live = next(r for r in rows if r["label"] == "w180_75")
    live60 = next(r for r in rows if r["label"] == "w180_60")
    print("\n=== live wait3+75 (BTC-only tape) ===", flush=True)
    _print(live)
    print("=== wait3+60 (old) ===", flush=True)
    _print(live60)

    both = [r for r in rows if r["green"] and r["green7"]]
    print(f"\n=== BTC green ALL + last 7d: {len(both)} / {len(rows)} ===",
          flush=True)
    both.sort(key=lambda r: (r["week_green"], r["pnl7"], r["pnl"]),
              reverse=True)
    for r in both[:15]:
        _print(r)
        print(f"{'':12} {r['weeks']}", flush=True)

    print("\n=== top 15 BTC P&L (any) ===", flush=True)
    for r in sorted(rows, key=lambda r: r["pnl"], reverse=True)[:15]:
        _print(r)

    print("\n=== best bar at each wait (by ALL P&L, require green) ===",
          flush=True)
    best_wait = []
    for wait in WAITS:
        chunk = [r for r in rows if r["label"].startswith(f"w{wait:03d}_")
                 and r["green"]]
        if not chunk:
            print(f"w{wait:03d}  no green bar", flush=True)
            continue
        best = max(chunk, key=lambda r: (r["green7"], r["pnl"], r["pnl7"]))
        best_wait.append(best)
        _print(best)

    better = [r for r in both
              if r["pnl"] > live["pnl"] and r["pnl7"] > live["pnl7"]]
    print(f"\n=== strictly better than wait3+75 on ALL and 7d: "
          f"{len(better)} ===", flush=True)
    for r in sorted(better, key=lambda r: r["pnl"], reverse=True)[:12]:
        _print(r)
        print(f"{'':12} {r['weeks']}", flush=True)

    # Confirm deployable overlay on mixed 7-name book: ETH/cmdty stay live.
    print("\nloading mixed 7-name book for overlay confirm...", flush=True)
    bt_m = Backtest(os.path.join(REPO, "data/kalshi"), bankroll=250)
    confirm_labels = ["w180_75", "w180_68", "w180_60"]
    seen = {"w180_75", "w180_68", "w180_60"}
    for r in both[:8] + better[:8] + best_wait:
        if r["label"] not in seen:
            confirm_labels.append(r["label"])
            seen.add(r["label"])
    mixed = []
    print(f"{'cfg':<16} {'btc':>10} {'eth':>10} {'cmd':>8} {'sum':>8}",
          flush=True)
    for lab in confirm_labels:
        wait, bar = _parse(lab)
        m = bt_m.run(params, decide_fn=_btc_wait_fn(wait, bar))
        by = m.get("by_metal") or {}
        btc = by.get("btc") or {"n": 0, "pnl": 0.0}
        eth = by.get("eth") or {"n": 0, "pnl": 0.0}
        cmd = sum((by.get(x) or {}).get("pnl") or 0
                  for x in ("gold", "silver", "copper", "wti", "natgas"))
        rec = {
            "label": lab,
            "wait": wait, "bar": bar,
            "btc_n": btc.get("n"), "btc": btc.get("pnl"),
            "eth_n": eth.get("n"), "eth": eth.get("pnl"),
            "cmd": round(cmd, 2),
            "sum": round((btc.get("pnl") or 0) + (eth.get("pnl") or 0) + cmd, 2),
            "both": (btc.get("n") or 0) > 0 and (eth.get("n") or 0) > 0
                    and (btc.get("pnl") or 0) > 0 and (eth.get("pnl") or 0) > 0,
        }
        mixed.append(rec)
        flag = "BOTH" if rec["both"] else "no"
        print(
            f"{lab:<16} btc {rec['btc']:+8.1f} eth {rec['eth']:+8.1f} "
            f"cmd {rec['cmd']:+7.1f} sum {rec['sum']:+7.1f} {flag}",
            flush=True,
        )

    payload = {
        "tape": "2026-08-28 → 2026-09-12 (~2 weeks, not months)",
        "fill": "lag",
        "bankroll": 250,
        "live": "desk_book wait3+75 mixed; this sweep does not change it",
        "btc_only": rows,
        "mixed_overlay": mixed,
        "live_btc_only": live,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1)

    _write_md(live, live60, both, better, best_wait, mixed, n_mkt)
    print(f"\nwrote {OUT_JSON}\nwrote {OUT_MD}", flush=True)


def _write_md(live, live60, both, better, best_wait, mixed, n_mkt):
    lines = [
        "# BTC wait × bar (longer sits) — 2026-09-12",
        "",
        "Live `desk_book` is unchanged: whole book wait 3 min + **≥75¢**.",
        "This page is lag-fill research on **BTC only**, then a mixed-book",
        "overlay confirm (ETH + commodities stay wait-3 + 75¢).",
        "",
        f"BTC markets on disk: **{n_mkt}**. Tape ~2 weeks, not months.",
        "Reproduce: `python3 scripts/kalshi_btc_wait_sweep.py`.",
        "",
        "## Why",
        "",
        "BTC 15m favorites whip in the first minutes. Longer wait = let",
        "the open flicker die, then clip a richer (or same) bar.",
        "",
        "## BTC-only tape vs live",
        "",
        "| cfg | n | BTC | hit | last 7d | weekend |",
        "|---|---:|---:|---:|---:|---:|",
        f"| wait3 + 60¢ (old) | {live60['n']} | {live60['pnl']:+.0f} | "
        f"{live60['hit']} | {live60['pnl7']:+.0f} | {live60['weekend_pnl']:+.0f} |",
        f"| **wait3 + 75¢ (live)** | {live['n']} | **{live['pnl']:+.0f}** | "
        f"{live['hit']} | **{live['pnl7']:+.0f}** | {live['weekend_pnl']:+.0f} |",
        "",
        "## Best bar at each wait (BTC-only, green ALL)",
        "",
        "| wait | bar | n | BTC | last 7d | weekend | weeks green |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in best_wait:
        wait, bar = _parse(r["label"])
        lines.append(
            f"| {wait//60:.0f} min ({wait}s) | {int(round(bar*100))}¢ | "
            f"{r['n']} | {r['pnl']:+.0f} | {r['pnl7']:+.0f} | "
            f"{r['weekend_pnl']:+.0f} | {r['week_green']} |"
        )
    lines += [
        "",
        "## Strictly better than wait3+75 (BTC ALL and last 7d)",
        "",
    ]
    if not better:
        lines.append("None on this tape. Keep live wait-3 + 75¢ on BTC.")
    else:
        lines += [
            "| cfg | n | BTC | last 7d | weekend |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for r in sorted(better, key=lambda r: r["pnl"], reverse=True)[:12]:
            wait, bar = _parse(r["label"])
            lines.append(
                f"| wait {wait//60:.0f} min + {int(round(bar*100))}¢ | "
                f"{r['n']} | {r['pnl']:+.0f} | {r['pnl7']:+.0f} | "
                f"{r['weekend_pnl']:+.0f} |"
            )
    lines += [
        "",
        "## Mixed 7-name overlay (ETH + cmdty stay wait-3 + 75¢)",
        "",
        "This is what we would actually run: only BTC's wait/bar moves.",
        "",
        "| BTC cfg | BTC | ETH | cmdty | both names |",
        "|---|---:|---:|---:|---|",
    ]
    for rec in mixed:
        wait, bar = rec["wait"], rec["bar"]
        flag = "yes" if rec["both"] else "no"
        lines.append(
            f"| wait {wait//60:.0f} min + {int(round(bar*100))}¢ | "
            f"{rec['btc']:+.0f} | {rec['eth']:+.0f} | {rec['cmd']:+.0f} | "
            f"{flag} |"
        )
    lines += [
        "",
        "## Verdict",
        "",
        "Do not bounce live off this page unless a longer BTC wait is",
        "green on BTC **and** last 7d **and** the mixed overlay still",
        "leaves ETH green. Two weeks of 15m crypto, not months.",
        "",
    ]
    with open(OUT_MD, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
