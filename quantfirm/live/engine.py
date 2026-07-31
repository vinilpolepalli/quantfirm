"""The execution desk: one idempotent run per invocation (CI calls it hourly).

Flow: kill-switch check -> load candles (repo history + Kraken top-up) ->
compute target position -> reconcile with bot state -> risk checks -> place
at most one rebalancing order -> persist state + trade log.

Design rules that keep unattended money safe:
  * Idempotent per bar: state.last_bar guards re-runs; deterministic
    client_order_id makes even a double-submit venue-rejected.
  * Signals use only CLOSED candles from an independent venue (Kraken).
  * Any risk violation aborts the run; drawdown breaches trip the kill
    switch file, which blocks all future runs until removed.
  * The bot only manages `bankroll_usd`; it never touches other holdings —
    sells are capped at its own recorded position.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

import pandas as pd

from .. import risk
from ..data import fetch_kraken_recent, load_history
from ..strategies import load_all
from . import state as st
from .rh_client import RobinhoodCrypto, RobinhoodError

CONFIG_FILE = os.environ.get(
    "QF_CONFIG", os.path.join(os.path.dirname(__file__), "..", "..", "config", "live.json"))


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def build_candles(symbol: str) -> pd.DataFrame:
    """Repo history (long warmup) merged with fresh Kraken bars (recency)."""
    try:
        hist = load_history(symbol, "1h")
    except FileNotFoundError:
        hist = pd.DataFrame()
    recent = fetch_kraken_recent(symbol, 60)
    df = pd.concat([hist, recent])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def run() -> dict:
    cfg = load_config()
    policy = risk.RiskPolicy(**cfg.get("risk", {}))
    result: dict = {"ts": st.now_iso(), "action": "none"}

    if not cfg.get("enabled", False):
        result["action"] = "disabled_in_config"
        return result
    if risk.kill_switch_active(st.STATE_DIR):
        result["action"] = "kill_switch_active"
        return result

    strategies = load_all()
    strat = strategies[cfg["strategy"]]
    data_symbol = cfg["data_symbol"]          # e.g. BTCUSDT
    venue_symbol = cfg["venue_symbol"]        # e.g. BTC-USD

    df = build_candles(data_symbol)
    last_bar = df.index[-1]
    data_age_h = (datetime.now(timezone.utc) - last_bar).total_seconds() / 3600

    state = st.load()
    if state.get("last_bar") == last_bar.isoformat():
        result["action"] = "bar_already_processed"
        result["bar"] = last_bar.isoformat()
        return result

    target_frac = float(strat(df, **cfg.get("params", {})).iloc[-1])
    target_frac = max(0.0, min(1.0, target_frac))

    client = RobinhoodCrypto()
    quote = client.best_bid_ask(venue_symbol)
    mid = float(quote["price"])
    ask = float(quote["ask_inclusive_of_buy_spread"])
    bid = float(quote["bid_inclusive_of_sell_spread"])

    pos_qty = float(state.get("position_qty", 0.0))
    cash = float(state.get("cash_usd", 0.0))
    equity = pos_qty * mid + cash
    peak = max(float(state.get("peak_equity", 0.0)), equity)

    target_usd = target_frac * policy.bankroll_usd
    current_usd = pos_qty * mid
    delta_usd = target_usd - current_usd

    result.update({"bar": last_bar.isoformat(), "mid": mid, "target_frac": target_frac,
                   "equity": round(equity, 2), "position_qty": pos_qty,
                   "delta_usd": round(delta_usd, 2)})

    # Drawdown check runs every cycle, trade or not.
    if peak > 0 and equity / peak - 1 < -policy.kill_drawdown:
        risk.trip_kill_switch(st.STATE_DIR, f"drawdown {equity / peak - 1:.2%} (equity {equity:.2f} peak {peak:.2f})")
        result["action"] = "kill_switch_tripped"
        _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
        return result

    if abs(delta_usd) < policy.min_trade_usd:
        result["action"] = "hold"
        _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
        return result

    side = "buy" if delta_usd > 0 else "sell"
    ref_price = ask if side == "buy" else bid
    if side == "buy":
        trade_usd = min(delta_usd, cash)  # never spend money the bot doesn't have
        qty = trade_usd / ask
    else:
        qty = min(-delta_usd / bid, pos_qty)

    # Quantize to the venue's served increment and respect its minimum.
    try:
        pair = client.trading_pair(venue_symbol)
        increment = Decimal(str(pair.get("asset_increment", "0.00000001")))
        min_qty = float(pair.get("min_order_size", 0.0) or 0.0)
        if pair.get("status") not in (None, "", "tradable"):
            result["action"] = f"pair_untradable:{pair.get('status')}"
            _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
            return result
    except Exception:
        increment, min_qty = Decimal("0.00000001"), 0.000001
    qty = float(Decimal(str(qty)).quantize(increment, rounding=ROUND_DOWN))
    trade_usd = qty * ref_price

    if qty <= 0 or qty < min_qty or trade_usd < policy.min_trade_usd:
        result["action"] = f"skip_small_{side}"
        _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
        return result

    violations = risk.check_pre_trade(
        policy, equity_usd=equity, peak_equity_usd=peak, order_usd=trade_usd,
        position_after_usd=current_usd + (trade_usd if side == "buy" else -trade_usd),
        data_age_hours=data_age_h)
    if violations:
        result["action"] = "risk_blocked"
        result["violations"] = violations
        _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
        return result

    order_id = RobinhoodCrypto.deterministic_order_id(
        cfg["strategy"], venue_symbol, side, last_bar.isoformat())
    try:
        resp = client.place_market_order(venue_symbol, side, f"{qty:.8f}", order_id)
        status = resp.get("state", "submitted")
    except RobinhoodError as e:
        if e.status == 400 and "client_order_id" in e.body:
            status = "duplicate_rejected"   # idempotency worked; treat as done
            resp = {}
        else:
            result["action"] = "order_error"
            result["error"] = str(e)
            _finalize(state, last_bar, pos_qty, cash, equity, peak, result)
            return result

    # Book the fill at the quoted touch (market orders fill ~immediately).
    if side == "buy":
        pos_qty += qty
        cash -= qty * ask
    else:
        pos_qty -= qty
        cash += qty * bid
    state["trades"] = int(state.get("trades", 0)) + 1
    st.log_trade({"ts": st.now_iso(), "symbol": venue_symbol, "side": side,
                  "qty": qty, "ref_price": ref_price,
                  "notional_usd": round(trade_usd, 2),
                  "client_order_id": order_id,
                  "order_id": resp.get("id", ""), "status": status})
    result["action"] = f"{side}:{qty}"
    result["order_status"] = status

    equity = pos_qty * mid + cash
    _finalize(state, last_bar, pos_qty, cash, equity, max(peak, equity), result)
    return result


def _finalize(state: dict, last_bar, pos_qty: float, cash: float,
              equity: float, peak: float, result: dict) -> None:
    state.update({
        "last_bar": last_bar.isoformat(),
        "position_qty": round(pos_qty, 10),
        "cash_usd": round(cash, 4),
        "peak_equity": round(peak, 4),
        "last_run": result,
    })
    state.setdefault("equity_history", []).append([st.now_iso(), round(equity, 4)])
    state["equity_history"] = state["equity_history"][-2000:]
    st.save(state)


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2))
    sys.exit(0 if out.get("action") not in ("order_error",) else 1)
