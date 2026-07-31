"""Bot state, committed to the repo by each CI run so every desk (and every
agent session) can read the firm's books. Schema:

{
  "version": 1,
  "last_bar": "2026-07-31T14:00:00+00:00",   # last hourly bar acted on
  "position_qty": 0.0031,                      # asset units the BOT owns
  "cash_usd": 12.5,                            # bot-attributed cash
  "equity_history": [["iso", equity_usd], ...],
  "peak_equity": 265.0,
  "trades": int,
  "last_run": {...}                            # diagnostics from latest run
}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

STATE_DIR = os.environ.get("QF_STATE_DIR",
                           os.path.join(os.path.dirname(__file__), "..", "..", "state"))
STATE_FILE = os.path.join(STATE_DIR, "live_state.json")
TRADE_LOG = os.path.join(STATE_DIR, "trade_log.csv")


def load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"version": 1, "last_bar": None, "position_qty": 0.0, "cash_usd": 0.0,
                "equity_history": [], "peak_equity": 0.0, "trades": 0, "last_run": {}}
    with open(STATE_FILE) as f:
        return json.load(f)


def save(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def log_trade(row: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    header = "ts,symbol,side,qty,ref_price,notional_usd,client_order_id,order_id,status\n"
    exists = os.path.exists(TRADE_LOG)
    with open(TRADE_LOG, "a") as f:
        if not exists:
            f.write(header)
        f.write(",".join(str(row.get(k, "")) for k in
                         ["ts", "symbol", "side", "qty", "ref_price", "notional_usd",
                          "client_order_id", "order_id", "status"]) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
