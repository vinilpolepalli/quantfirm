#!/usr/bin/env python3
"""Hold the container awake WITHOUT starting a second trading engine.

The hourly Routine used to block by running a foreground `cli paper` session.
Blocking is the point -- an idle session gets its container reclaimed, and a
reclaimed container takes the supervisor with it. But that foreground engine
ran *concurrently with the supervisor's*, and two engines against one state
file double-trade: each holds its own in-memory `state.open`, so the
"already in this ticker" guard is False for both and the same view is opened
twice in one 15-min window. See `_engine_lock` in quantfirm/kalshi/cli.py.

This script does the same job -- occupy the foreground for N minutes -- while
the supervisor stays the single writer. It also babysits: if the supervisor
dies mid-block it is restarted here rather than waiting for the next hour.

    python3 scripts/kalshi_keepalive.py --minutes 8.5
"""
import argparse
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
LOG = os.path.join(REPO, "state", "kalshi_paper_loop.log")
DECISIONS = os.path.join(REPO, "state", "kalshi_paper_decisions.jsonl")


def _import_checkin():
    """Reuse the check-in's liveness + restart helpers; one implementation."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kalshi_desk_checkin", os.path.join(REPO, "scripts",
                                            "kalshi_desk_checkin.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=8.5)
    ap.add_argument("--poll", type=float, default=20.0,
                    help="seconds between supervisor liveness checks")
    a = ap.parse_args()

    ck = _import_checkin()
    print(f"keepalive: {a.minutes:g}min, no trading engine of its own")
    print(ck.ensure_supervisor())

    deadline = time.time() + a.minutes * 60
    seen = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    restarts = 0
    while time.time() < deadline:
        time.sleep(min(a.poll, max(1.0, deadline - time.time())))
        if not ck.supervisor_alive():
            restarts += 1
            print(f"[{stamp()}] supervisor DIED -> {ck.ensure_supervisor()}")
        # surface whatever the supervisor's engine did while we waited
        try:
            size = os.path.getsize(LOG)
            if size > seen:
                with open(LOG) as f:
                    f.seek(seen)
                    for line in f.read().splitlines():
                        if any(w in line for w in ("FILL", "SETTLE", "WATCHDOG",
                                                   "WARNING", "supervisor")):
                            print(" ", line)
                seen = size
            elif size < seen:       # log rotated
                seen = 0
        except OSError:
            pass

    age = (time.time() - os.path.getmtime(DECISIONS)
           if os.path.exists(DECISIONS) else float("inf"))
    print(f"keepalive done: supervisor_alive={ck.supervisor_alive()} "
          f"restarts={restarts} last_decision_age={age:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
