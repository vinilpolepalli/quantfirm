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
from .universe import BANKROLL, COMMODITY_ASSETS, PAPER_ASSETS, PAPER_STRATEGY

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIDFILE = os.path.join(REPO, "state", "kalshi_paper_loop.pid")
STATE_PATH = os.path.join(REPO, "state", "kalshi_paper_state.json")
STATUS_PATH = os.path.join(REPO, "state", "kalshi_desk_status.json")
TRADES_PATH = os.path.join(REPO, "state", "kalshi_paper_trades.csv")
LOOP = os.path.join(REPO, "scripts", "kalshi_paper_loop.sh")
POLY_LOOP = os.path.join(REPO, "scripts", "kalshi_poly_paper_loop.sh")
POLY_PIDFILE = os.path.join(REPO, "state", "kalshi_poly_paper.pid")
POLY_STATE_PATH = os.path.join(REPO, "state", "kalshi_poly_paper_state.json")
POLY_TRADES_PATH = os.path.join(REPO, "state", "kalshi_poly_paper_trades.csv")
DIV_LOOP = os.path.join(REPO, "scripts", "kalshi_div_paper_loop.sh")
DIV_PIDFILE = os.path.join(REPO, "state", "kalshi_div_paper.pid")
DIV_STATE_PATH = os.path.join(REPO, "state", "kalshi_div_paper_state.json")
DIV_TRADES_PATH = os.path.join(REPO, "state", "kalshi_div_paper_trades.csv")
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
    if kill_switch_tripped():
        if supervisor_alive():
            return "supervisor: alive (kill switch — not restarting)"
        return "supervisor: down (kill switch — not restarting)"
    if supervisor_alive():
        return "supervisor: alive"
    os.makedirs(os.path.join(REPO, "state"), exist_ok=True)
    os.chmod(LOOP, 0o755)
    env = os.environ.copy()
    # Registered live book. Do not inherit a stale METALS/STRATEGY.
    # METALS stays the seven names; live entries sit separately when
    # commodity 15m series are dark.
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


def poly_paper_alive() -> bool:
    try:
        with open(POLY_PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pidfile_pid(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _kill_tree(pid: int) -> None:
    """SIGKILL pid and descendants. Targeted PIDs only — never pkill -f."""
    try:
        kids = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True)
        for line in kids.stdout.split():
            try:
                _kill_tree(int(line))
            except ValueError:
                pass
    except Exception:
        pass
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _stop_named_supervisor(pidfile: str, expect: str) -> bool:
    """Stop one paper-sleeve bash loop if the pidfile matches `expect`.

    Refuses to kill the live desk (`kalshi_paper_loop.sh`).
    """
    pid = _pidfile_pid(pidfile)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    cmd = _cmdline(pid)
    if expect not in cmd:
        return False
    _kill_tree(pid)
    return True


def ensure_poly_paper() -> str:
    """Poly paper sleeve is sat. Owner is on live desk_book only.

    Check-in still calls this so a stray loop is stopped, never restarted.
    """
    if poly_paper_alive() and _stop_named_supervisor(
            POLY_PIDFILE, "kalshi_poly_paper_loop"):
        return "poly_paper: stopped (owner sat paper; not restarting)"
    return "poly_paper: off (not restarting)"


def div_paper_alive() -> bool:
    try:
        with open(DIV_PIDFILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_div_paper() -> str:
    """DOGE/XRP/NEAR paper sleeve is sat. Owner is on live desk_book only."""
    if div_paper_alive() and _stop_named_supervisor(
            DIV_PIDFILE, "kalshi_div_paper_loop"):
        return "div_paper: stopped (owner sat paper; not restarting)"
    return "div_paper: off (not restarting)"


def _live_env_on() -> bool:
    return os.environ.get("KALSHI_LIVE", "0") in ("1", "true", "TRUE", "yes")


def open_count_universe() -> tuple[str, ...]:
    """Which 15m names `open-count` should probe.

    Live supervisor inherits KALSHI_LIVE=1, so a crypto-only weekend
    (or Thu maintenance) does not start a live session. Poly/div force
    KALSHI_LIVE=0 and still see BTC/ETH.
    """
    return COMMODITY_ASSETS if _live_env_on() else PAPER_ASSETS


def probe_open_markets(client=None, assets=None) -> tuple[int, int]:
    """(open_windows, successful_probes) over `assets`.

    Default assets=PAPER_ASSETS (commodities + BTC + ETH). A probe that
    throws is not successful — live sit fail-opens when probed==0.
    """
    from .client import KalshiClient
    from .universe import LIVE_SERIES, PAPER_ASSETS
    names = PAPER_ASSETS if assets is None else tuple(assets)
    inv = {asset: ticker for ticker, asset in LIVE_SERIES.items()}
    c = client or KalshiClient("prod")
    n = 0
    probed = 0
    for asset in names:
        series = inv.get(asset)
        if not series:
            continue
        try:
            m = c.open_market_for_series(series)
            probed += 1
        except Exception:
            continue
        if m:
            n += 1
    return n, probed


def count_open_markets(client=None, assets=None) -> int:
    """How many of `assets` 15m series have an open window right now.

    Default PAPER_ASSETS (commodities + BTC + ETH). Live `open-count`
    passes COMMODITY_ASSETS so weekend BTC/ETH is not enough to start
    a live session. Poly/div keep the default.
    """
    from .universe import PAPER_ASSETS
    names = PAPER_ASSETS if assets is None else tuple(assets)
    return probe_open_markets(client=client, assets=names)[0]


def live_commodity_dark(client=None) -> bool:
    """True iff commodity 15m series are observably dark.

    Fail-open: if every probe threw, return False so live does not sit
    on a total API flake (same idea as supervisor open-count fail →
    start anyway).
    """
    n, probed = probe_open_markets(client=client, assets=COMMODITY_ASSETS)
    if probed == 0:
        return False
    return n == 0


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
        "live": (not kill_switch_tripped()) and (
            bool(state.get("live")) or os.environ.get("KALSHI_LIVE") in (
                "1", "true", "TRUE", "yes")),
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
    poly_state: dict = {}
    if os.path.exists(POLY_STATE_PATH):
        try:
            with open(POLY_STATE_PATH) as f:
                poly_state = json.load(f)
        except (OSError, json.JSONDecodeError):
            poly_state = {}
    rec["poly_paper_loop"] = "alive" if poly_paper_alive() else "down"
    rec["poly_paper_n_open"] = len(poly_state.get("open") or [])
    rec["poly_paper_cash"] = (poly_state.get("cash") or {}).get("shadow")
    div_state: dict = {}
    if os.path.exists(DIV_STATE_PATH):
        try:
            with open(DIV_STATE_PATH) as f:
                div_state = json.load(f)
        except (OSError, json.JSONDecodeError):
            div_state = {}
    rec["div_paper_loop"] = "alive" if div_paper_alive() else "down"
    rec["div_paper_n_open"] = len(div_state.get("open") or [])
    rec["div_paper_cash"] = (div_state.get("cash") or {}).get("shadow")
    rec["div_paper_realized"] = (div_state.get("realized") or {}).get("shadow")
    try:
        from .poly import compare_snapshot
        rec["poly_paper"] = compare_snapshot()
    except Exception:
        pass
    os.makedirs(os.path.dirname(status_path) or ".", exist_ok=True)
    tmp = status_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, status_path)
    return rec
