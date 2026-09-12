#!/usr/bin/env python3
"""Hourly / 15-minute check-in for the Kalshi paper desk.

Safe to run unattended:
  * restarts the supervisor if the PID is dead
  * writes state/kalshi_desk_status.json (the committed heartbeat)
  * tallies new settled fills into research/kalshi_backtest.md
  * commits only the durable files (not the growing tape)

Prints a one-line status block.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shlex
import statistics as st
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.runtime import (  # noqa: E402
    TRADES_PATH, ensure_poly_paper, ensure_supervisor, write_desk_status,
)

MARK = os.path.join(REPO, "state", "kalshi_checkin_mark.json")
LOGDOC = os.path.join(REPO, "research", "kalshi_backtest.md")
COMMIT_PATHS = (
    "state/kalshi_desk_status.json",
    "state/kalshi_paper_trades.csv",
    "state/kalshi_poly_paper_trades.csv",
    "state/kalshi_checkin_mark.json",
    "research/kalshi_backtest.md",
)


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True,
                          text=True, **kw)


def load_trades():
    if not os.path.exists(TRADES_PATH):
        return []
    with open(TRADES_PATH) as f:
        return list(csv.DictReader(f))


def stats(rows, adapter):
    p = [float(r["pnl"]) for r in rows if r.get("adapter") == adapter]
    if not p:
        return None
    n = len(p)
    wins = [x for x in p if x > 0]
    losses = [x for x in p if x <= 0]
    mu = st.mean(p)
    sd = st.stdev(p) if n > 1 else 0.0
    t = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
    aw = st.mean(wins) if wins else 0.0
    al = st.mean(losses) if losses else 0.0
    be = abs(al) / (aw + abs(al)) if (aw + abs(al)) > 0 else None
    return {"n": n, "pnl": round(sum(p), 2), "hit": round(len(wins) / n, 4),
            "mean": round(mu, 3), "sd": round(sd, 2), "t": round(t, 2),
            "breakeven_hit": round(be, 4) if be else None,
            "cushion_pp": round(100 * (len(wins) / n - be), 2) if be else None}


def main():
    status = [ensure_supervisor(), ensure_poly_paper()]
    rec = write_desk_status(supervisor=status[0])
    rows = load_trades()
    mark = {"n_settled": 0, "t_history": []}
    if os.path.exists(MARK):
        with open(MARK) as f:
            mark = json.load(f)
    new = rows[mark.get("n_settled", 0):]

    mk = stats(rows, "maker")
    sh_ = stats(rows, "shadow")
    if mk:
        hist = mark.get("t_history", [])
        if not hist or hist[-1] != mk["t"]:
            hist.append(mk["t"])
        mark["t_history"] = hist[-12:]

    if new:
        nm = stats(new, "maker")
        ns = stats(new, "shadow")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        line = [f"\n* {now} (auto check-in). "]
        if nm:
            line.append(f"Maker {nm['pnl']:+.2f} ({nm['n']} fills, "
                        f"{int(nm['hit']*nm['n'])}/{nm['n']} won). ")
        if ns:
            line.append(f"Taker {ns['pnl']:+.2f} ({ns['n']}). ")
        if mk:
            line.append(
                f"**Cumulative maker {mk['pnl']:+.2f} ({mk['n']} fills, hit "
                f"{mk['hit']:.3f} vs break-even {mk['breakeven_hit']:.3f}, "
                f"cushion {mk['cushion_pp']:+.2f}pp, t={mk['t']:.2f}).** "
                f"t-history: {' → '.join(str(x) for x in mark['t_history'][-6:])}.")
        with open(LOGDOC, "a") as f:
            f.write("".join(line) + "\n")
        status.append(f"recorded {len(new)} new fills")
    else:
        status.append("no new fills")

    mark["n_settled"] = len(rows)
    os.makedirs(os.path.dirname(MARK), exist_ok=True)
    with open(MARK, "w") as f:
        json.dump(mark, f, indent=1)

    if mk:
        status.append(
            f"maker n={mk['n']} pnl=${mk['pnl']:+.2f} hit={mk['hit']:.3f} "
            f"(be {mk['breakeven_hit']:.3f}) t={mk['t']:.2f}")
    if sh_:
        status.append(f"taker n={sh_['n']} pnl=${sh_['pnl']:+.2f}")
    status.append(f"open={rec['n_open']} cash_shadow={rec['cash'].get('shadow')}")
    pp = rec.get("poly_paper") or {}
    live_c = pp.get("live_crypto") or {}
    poly_c = pp.get("poly_paper") or {}
    status.append(
        f"poly_loop={rec.get('poly_paper_loop')} "
        f"live_crypto n={live_c.get('n')} pnl=${live_c.get('pnl')} "
        f"poly_paper n={poly_c.get('n')} pnl=${poly_c.get('pnl')}"
        + (" AHEAD" if pp.get("poly_ahead") else "")
        + (" READY" if pp.get("ready") else "")
    )
    try:
        from quantfirm.kalshi.poly import snapshot
        snap = snapshot()
        bits = []
        for asset, d in snap.items():
            if not d.get("ok"):
                continue
            bits.append(f"{asset} {d.get('favorite')} up={d['up']}")
        if bits:
            status.append("poly " + "; ".join(bits))
    except Exception:
        pass

    existing = [p for p in COMMIT_PATHS if os.path.exists(os.path.join(REPO, p))]
    if existing:
        sh("git add " + " ".join(shlex.quote(p) for p in existing))
    msg = ("kalshi: desk check-in — "
           + (f"shadow {sh_['pnl']:+.2f} n={sh_['n']}" if sh_ else "no settled fills"))
    c = sh(f"git commit -q -m {shlex.quote(msg)}")
    if c.returncode == 0:
        pushed = sh("git push -q")
        status.append("pushed" if pushed.returncode == 0 else "PUSH FAILED")
    else:
        status.append("nothing to commit")

    print(" | ".join(status))


if __name__ == "__main__":
    main()
