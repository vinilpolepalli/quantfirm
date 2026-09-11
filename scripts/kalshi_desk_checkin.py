#!/usr/bin/env python3
"""Hourly check-in for the Kalshi paper desk: report, commit, self-heal.

Designed to be safe to run unattended, repeatedly, for weeks:
  * tallies any fills settled since the last check-in and appends them to the
    session log (idempotent — it records a high-water mark in state/)
  * recomputes the statistics that actually decide the question (hit rate vs
    break-even, t-stat trajectory)
  * restarts the supervisor loop if it died (e.g. container restart)
  * commits and pushes, so the record survives the container

Prints a short status block; the agent turn that runs it relays anything
noteworthy to the user.
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import shlex
import statistics as st
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES = os.path.join(REPO, "state", "kalshi_paper_trades.csv")
MARK = os.path.join(REPO, "state", "kalshi_checkin_mark.json")
LOGDOC = os.path.join(REPO, "research", "kalshi_backtest.md")
LOOP = os.path.join(REPO, "scripts", "kalshi_paper_loop.sh")


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, cwd=REPO, capture_output=True,
                          text=True, **kw)


PIDFILE = os.path.join(REPO, "state", "kalshi_paper_loop.pid")


def supervisor_alive() -> bool:
    """Check the PID file, not pgrep.

    Regression: `pgrep -f kalshi_paper_loop.sh` also matches the /bin/sh that
    is running that very pgrep, so it ALWAYS returned True and this check-in
    reported "supervisor: alive" for a supervisor that had been dead for an
    hour. Verify a real, live PID instead."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)          # signal 0 = liveness probe, no effect
        return True
    except OSError:
        return False


def ensure_supervisor() -> str:
    if supervisor_alive():
        return "supervisor: alive"
    sh(f"chmod +x {LOOP}")
    subprocess.Popen(f"setsid nohup {LOOP} >/dev/null 2>&1 &",
                     shell=True, cwd=REPO, start_new_session=True)
    return "supervisor: WAS DEAD -> restarted"


def load():
    if not os.path.exists(TRADES):
        return []
    with open(TRADES) as f:
        return list(csv.DictReader(f))


def stats(rows, adapter):
    p = [float(r["pnl"]) for r in rows if r["adapter"] == adapter]
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
    status = [ensure_supervisor()]
    rows = load()
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
    with open(MARK, "w") as f:
        json.dump(mark, f, indent=1)

    if mk:
        status.append(
            f"maker n={mk['n']} pnl=${mk['pnl']:+.2f} hit={mk['hit']:.3f} "
            f"(be {mk['breakeven_hit']:.3f}) t={mk['t']:.2f}")
    if sh_:
        status.append(f"taker n={sh_['n']} pnl=${sh_['pnl']:+.2f}")

    msg = ("desk: auto check-in — "
           + (f"maker {mk['pnl']:+.2f} n={mk['n']} t={mk['t']:.2f}" if mk else "no fills")
           + "\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
           + "\nClaude-Session: https://claude.ai/code/session_01QEzLS4u6E7dCgjXtCZdfGQ")
    sh("git add -A state/ research/ 2>/dev/null")
    c = sh(f"git commit -q -m {shlex.quote(msg)}")
    if c.returncode == 0:
        pushed = sh("git push -q")
        status.append("pushed" if pushed.returncode == 0 else "PUSH FAILED")
    else:
        status.append("nothing to commit")

    print(" | ".join(status))


if __name__ == "__main__":
    main()
