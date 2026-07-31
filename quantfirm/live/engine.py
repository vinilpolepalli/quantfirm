"""The execution desk: one idempotent run per invocation (CI calls it hourly).

Order lifecycle (reviewed adversarially; every rule below exists because a
specific failure mode was found):

  1. RECONCILE FIRST. If a previous run left a pending order intent, resolve
     it against venue truth (orders lookup by client_order_id) before doing
     anything else. No new orders while an intent is unresolved.
  2. INTENT BEFORE SUBMIT. The order intent (bar, side, qty, client_order_id)
     is persisted to state BEFORE the POST, so a crash at any point leaves
     evidence that the next run reconciles. The deterministic client_order_id
     alone is NOT enough — it rotates with the bar.
  3. BOOK VENUE TRUTH ONLY. Fills are booked from the venue's order record
     (filled quantity, average price), never assumed from the quote. A 400
     "duplicate" is resolved by looking up the original order, not guessed.
  4. ERRORS DON'T ADVANCE THE CLOCK. last_bar is only updated when the bar
     was fully handled; an order_error leaves it unset so the bar retries.
  5. FAIL SAFE ON BLINDNESS. Trading requires state.orders_read_verified
     (set by scripts/seed_books.py after proving the credential can actually
     see its own orders) — a credential that can trade but not read fills
     would force blind booking, which is how books diverge from reality.
  6. Kill switch = FLATTEN + HALT, not freeze: a drawdown breach exits the
     position instead of locking the bot into holding it.
"""

from __future__ import annotations

import json
import os
import sys
import time
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

TERMINAL_STATES = {"filled", "canceled", "cancelled", "rejected", "failed", "expired"}
FILL_POLL_SECONDS = 45
QUOTE_SANITY_MAX_GAP = 0.08  # quote vs candle close divergence that aborts the run


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
    if df.empty:
        raise RuntimeError("no candle data from repo cache or Kraken")
    return df


def find_order(client: RobinhoodCrypto, client_order_id: str) -> dict | None:
    for o in client.orders():
        if o.get("client_order_id") == client_order_id:
            return o
    return None


def poll_terminal(client: RobinhoodCrypto, client_order_id: str,
                  seconds: int = FILL_POLL_SECONDS) -> dict | None:
    """Wait briefly for the order to reach a terminal state. Returns the
    latest order record seen (possibly non-terminal), or None if invisible."""
    deadline = time.time() + seconds
    order = None
    while time.time() < deadline:
        order = find_order(client, client_order_id)
        if order and order.get("state") in TERMINAL_STATES:
            return order
        time.sleep(3)
    return order


def book_order(state: dict, order: dict, fallback_price: float) -> dict:
    """Apply the venue-reported result of an order to the books."""
    side = order.get("side")
    filled = float(order.get("filled_asset_quantity") or 0.0)
    avg = order.get("average_price")
    price = float(avg) if avg else fallback_price
    if filled > 0:
        if side == "buy":
            state["position_qty"] = float(state.get("position_qty", 0.0)) + filled
            state["cash_usd"] = float(state.get("cash_usd", 0.0)) - filled * price
        else:
            state["position_qty"] = max(0.0, float(state.get("position_qty", 0.0)) - filled)
            state["cash_usd"] = float(state.get("cash_usd", 0.0)) + filled * price
        state["trades"] = int(state.get("trades", 0)) + 1
    st.log_trade({"ts": st.now_iso(), "symbol": order.get("symbol", ""),
                  "side": side, "qty": filled, "ref_price": price,
                  "notional_usd": round(filled * price, 2),
                  "client_order_id": order.get("client_order_id", ""),
                  "order_id": order.get("id", ""),
                  "status": order.get("state", "unknown")})
    return {"filled_qty": filled, "avg_price": price, "state": order.get("state")}


def reconcile_pending(client: RobinhoodCrypto, state: dict, result: dict) -> bool:
    """Resolve a pending order intent against venue truth. True = resolved."""
    intent = state.get("pending_order")
    if not intent:
        return True
    order = find_order(client, intent["client_order_id"])
    if order is None:
        # Order never reached the venue (POST failed before acceptance).
        result["reconciled"] = {"intent": intent, "outcome": "not_found_discarded"}
        state["pending_order"] = None
        st.save(state)
        return True
    if order.get("state") not in TERMINAL_STATES:
        result["reconciled"] = {"intent": intent, "outcome": "still_open"}
        return False
    booked = book_order(state, order, fallback_price=float(intent.get("ref_price", 0.0)))
    result["reconciled"] = {"intent": intent, "outcome": "booked", **booked}
    state["pending_order"] = None
    st.save(state)
    return True


def submit_and_book(client: RobinhoodCrypto, state: dict, cfg: dict, *,
                    side: str, qty: float, ref_price: float, bar_iso: str,
                    result: dict) -> bool:
    """Full order lifecycle. Returns True if the bar can be marked handled."""
    order_id = RobinhoodCrypto.deterministic_order_id(
        cfg["strategy"], cfg["venue_symbol"], side, bar_iso)
    state["pending_order"] = {"bar": bar_iso, "side": side, "qty": qty,
                              "ref_price": ref_price, "client_order_id": order_id,
                              "submitted_at": st.now_iso()}
    st.save(state)  # intent hits disk (and the next commit) before the POST

    try:
        client.place_market_order(cfg["venue_symbol"], side, f"{qty:.8f}", order_id)
    except RobinhoodError as e:
        existing = find_order(client, order_id)
        if existing is None:
            state["pending_order"] = None
            st.save(state)
            result["action"] = "order_error"
            result["error"] = str(e)
            return False  # bar NOT handled — retried next run
        # duplicate of a real order (crash-rerun); fall through to booking it
    order = poll_terminal(client, order_id)
    if order is None or order.get("state") not in TERMINAL_STATES:
        result["action"] = f"{side}_pending_confirmation"
        return False  # intent stays pending; next run reconciles
    booked = book_order(state, order, fallback_price=ref_price)
    state["pending_order"] = None
    result["action"] = f"{side}:{booked['filled_qty']}@{booked['avg_price']}"
    result["order_state"] = booked["state"]
    return True


def run() -> dict:
    cfg = load_config()
    policy = risk.RiskPolicy(**cfg.get("risk", {}))
    result: dict = {"ts": st.now_iso(), "action": "none"}

    if not cfg.get("enabled", False):
        result["action"] = "disabled_in_config"
        return result

    state = st.load()  # raises loudly on corrupt state — fail safe, no trade

    df = build_candles(cfg["data_symbol"])
    last_bar = df.index[-1]
    data_age_h = (datetime.now(timezone.utc) - last_bar).total_seconds() / 3600

    client = RobinhoodCrypto()
    quote = client.best_bid_ask(cfg["venue_symbol"])
    mid = float(quote["price"])
    ask = float(quote["ask_inclusive_of_buy_spread"])
    bid = float(quote["bid_inclusive_of_sell_spread"])

    # Quote sanity: one absurd quote must not poison peak_equity or trigger trades.
    last_close = float(df["close"].iloc[-1])
    if abs(mid / last_close - 1) > QUOTE_SANITY_MAX_GAP:
        result["action"] = "bad_quote"
        result["quote_gap"] = round(mid / last_close - 1, 4)
        return result

    # Blindness guard: never trade with a credential that can't see its orders.
    if not state.get("orders_read_verified"):
        result["action"] = "orders_read_unverified"
        result["hint"] = "run scripts/seed_books.py to initialize and verify"
        return result

    # Reconcile any pending intent before ANY decision.
    if not reconcile_pending(client, state, result):
        result["action"] = "pending_order_unresolved"
        return result

    pos_qty = float(state.get("position_qty", 0.0))
    cash = float(state.get("cash_usd", 0.0))
    equity = pos_qty * mid + cash
    peak = max(float(state.get("peak_equity", 0.0)), equity)
    bar_iso = last_bar.isoformat()
    result.update({"bar": bar_iso, "mid": mid, "equity": round(equity, 2),
                   "position_qty": pos_qty, "cash_usd": round(cash, 2)})

    # Kill switch: flatten remaining position, then halt.
    if risk.kill_switch_active(st.STATE_DIR):
        if pos_qty * bid >= policy.min_trade_usd:
            qty = _quantize(client, cfg, pos_qty, result)
            if qty > 0:
                submit_and_book(client, state, cfg, side="sell", qty=qty,
                                ref_price=bid, bar_iso=bar_iso, result=result)
                result["action"] = "kill_switch_flatten:" + result.get("action", "")
        else:
            result["action"] = "kill_switch_halted"
        _persist(state, None, mid, result)
        return result

    if not state.get("initialized"):
        result["action"] = "books_uninitialized"
        result["hint"] = "run scripts/seed_books.py first"
        return result

    if state.get("last_bar") == bar_iso:
        result["action"] = "bar_already_processed"
        return result

    # Drawdown breach trips the kill switch (flatten happens this same run).
    if peak > 0 and equity / peak - 1 < -policy.kill_drawdown:
        risk.trip_kill_switch(
            st.STATE_DIR, f"drawdown {equity / peak - 1:.2%} (equity {equity:.2f} peak {peak:.2f})")
        if pos_qty > 0:
            qty = _quantize(client, cfg, pos_qty, result)
            if qty > 0:
                submit_and_book(client, state, cfg, side="sell", qty=qty,
                                ref_price=bid, bar_iso=bar_iso, result=result)
        result["action"] = "kill_switch_tripped_flattened"
        _persist(state, bar_iso, mid, result)
        return result

    target_frac = float(load_all()[cfg["strategy"]](df, **cfg.get("params", {})).iloc[-1])
    target_frac = max(0.0, min(1.0, target_frac))
    target_usd = target_frac * policy.bankroll_usd
    delta_usd = target_usd - pos_qty * mid
    result.update({"target_frac": target_frac, "delta_usd": round(delta_usd, 2)})

    if abs(delta_usd) < policy.min_trade_usd:
        result["action"] = "hold"
        _persist(state, bar_iso, mid, result)
        return result

    side = "buy" if delta_usd > 0 else "sell"
    ref_price = ask if side == "buy" else bid
    raw_qty = min(delta_usd, cash) / ask if side == "buy" else min(-delta_usd / bid, pos_qty)
    qty = _quantize(client, cfg, raw_qty, result)
    trade_usd = qty * ref_price
    if qty <= 0 or trade_usd < policy.min_trade_usd:
        result["action"] = f"skip_small_{side}"
        _persist(state, bar_iso, mid, result)
        return result

    violations = risk.check_pre_trade(
        policy, equity_usd=equity, peak_equity_usd=peak, order_usd=trade_usd,
        position_after_usd=pos_qty * mid + (trade_usd if side == "buy" else -trade_usd),
        data_age_hours=data_age_h)
    if violations:
        result["action"] = "risk_blocked"
        result["violations"] = violations
        _persist(state, bar_iso, mid, result)
        return result

    handled = submit_and_book(client, state, cfg, side=side, qty=qty,
                              ref_price=ref_price, bar_iso=bar_iso, result=result)
    _persist(state, bar_iso if handled else None, mid, result)
    return result


def _quantize(client: RobinhoodCrypto, cfg: dict, qty: float, result: dict) -> float:
    try:
        pair = client.trading_pair(cfg["venue_symbol"])
        increment = Decimal(str(pair.get("asset_increment") or "0.00000001"))
        min_qty = float(pair.get("min_order_size") or 0.000001)
        if pair.get("status") not in (None, "", "tradable"):
            result["pair_status"] = pair.get("status")
            return 0.0
    except Exception:
        # Cannot confirm venue precision — refuse rather than guess too fine.
        result["pair_status"] = "precision_unavailable"
        return 0.0
    q = float(Decimal(str(qty)).quantize(increment, rounding=ROUND_DOWN))
    return q if q >= min_qty else 0.0


def _persist(state: dict, handled_bar: str | None, mid: float, result: dict) -> None:
    if handled_bar:
        state["last_bar"] = handled_bar
    equity = float(state.get("position_qty", 0.0)) * mid + float(state.get("cash_usd", 0.0))
    state["peak_equity"] = round(max(float(state.get("peak_equity", 0.0)), equity), 4)
    state["last_run"] = result
    state.setdefault("equity_history", []).append([st.now_iso(), round(equity, 4)])
    state["equity_history"] = state["equity_history"][-2000:]
    st.save(state)


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=2))
    sys.exit(1 if out.get("action") in ("order_error",) else 0)
