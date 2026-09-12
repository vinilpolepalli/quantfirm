"""Supervisor liveness, open-window count, committed desk heartbeat.

No imports from paper/agent — those modules import halt, and the
supervisor scripts need to stay cheap enough to run every 15 minutes.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from .halt import kill_switch_tripped
from .universe import BANKROLL, PAPER_ASSETS, PAPER_STRATEGY

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIDFILE = os.path.join(REPO, "state", "kalshi_paper_loop.pid")
STATE_PATH = os.path.join(REPO, "state", "kalshi_paper_state.json")
STATUS_PATH = os.path.join(REPO, "state", "kalshi_desk_status.json")
TRADES_PATH = os.path.join(REPO, "state", "kalshi_paper_trades.csv")
LOOP = os.path.join(REPO, "scripts", "kalshi_paper_loop.sh")
TMUX_SESSION = "kalshi-desk"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def supervisor_alive() -> bool:
    """PID-file liveness. Do not pgrep the loop script — that self-matches."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _tmux(*args: str) -> subprocess.CompletedProcess:
    cmd = ["tmux"]
    if os.path.exists(TMUX_CONF):
        cmd += ["-f", TMUX_CONF]
    return subprocess.run(cmd + list(args), cwd=REPO, capture_output=True, text=True)


def ensure_supervisor() -> str:
    """Restart the 24/7 loop if the PID is dead.

    Inherit this process environment so Cloud Agent secrets
    (KALSHI_PROD_*) reach the loop. Do not ``tmux send-keys`` the PEM.
    """
    if supervisor_alive():
        return "supervisor: alive"
    os.makedirs(os.path.join(REPO, "state"), exist_ok=True)
    os.chmod(LOOP, 0o755)
    env = os.environ.copy()
    # Registered live book. Do not inherit a stale METALS/STRATEGY from a
    # previous commodities-only session (that sat out weekend BTC).
    env["METALS"] = ",".join(PAPER_ASSETS)
    env["STRATEGY"] = PAPER_STRATEGY
    env.setdefault("BANKROLL", str(int(BANKROLL)))
    env.setdefault("SESSION_MIN", "110")
    log_path = os.path.join(REPO, "state", "kalshi_paper_loop.log")
    log_f = open(log_path, "a")
    subprocess.Popen(
        ["/bin/bash", LOOP],
        cwd=REPO, start_new_session=True, env=env,
        stdout=log_f, stderr=subprocess.STDOUT)
    return "supervisor: WAS DEAD -> restarted (inherited env)"


def count_open_markets(client=None) -> int:
    """How many paper-book 15m series have an open window right now.

    Counts PAPER_ASSETS (commodities + BTC + ETH). Weekend: gold/WTI
    close Sat 04:00Z; crypto stays open and is enough to start a session.
    """
    from .client import KalshiClient
    from .universe import LIVE_SERIES, PAPER_ASSETS
    inv = {asset: ticker for ticker, asset in LIVE_SERIES.items()}
    c = client or KalshiClient("prod")
    n = 0
    for asset in PAPER_ASSETS:
        series = inv.get(asset)
        if not series:
            continue
        try:
            if c.open_market_for_series(series):
                n += 1
        except Exception:
            continue
    return n


def write_desk_status(supervisor: str | None = None,
                      state_path: str = STATE_PATH,
                      status_path: str = STATUS_PATH) -> dict:
    """Small committed snapshot. Tape / decisions stay gitignored."""
    state: dict = {}
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            state = {}
    open_pos = state.get("open") or []
    rec = {
        "ts": _now(),
        "strategy": state.get("strategy") or os.environ.get("STRATEGY", PAPER_STRATEGY),
        "universe": list(state.get("metals") or PAPER_ASSETS),
        "bankroll": BANKROLL,
        "live": bool(state.get("live")) or os.environ.get("KALSHI_LIVE") in (
            "1", "true", "TRUE", "yes"),
        "kill_switch": kill_switch_tripped(),
        "supervisor": supervisor or ("alive" if supervisor_alive() else "down"),
        "cash": state.get("cash") or {},
        "realized": state.get("realized") or {},
        "n_open": len(open_pos),
        "open": [
            {k: p.get(k) for k in ("metal", "side", "count", "ticker",
                                   "fill_price", "adapter")}
            for p in open_pos if isinstance(p, dict)
        ],
        "n_settled": state.get("n_settled", 0),
        "updated": state.get("updated"),
        "started": state.get("started"),
    }
    os.makedirs(os.path.dirname(status_path) or ".", exist_ok=True)
    tmp = status_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, status_path)
    return rec
