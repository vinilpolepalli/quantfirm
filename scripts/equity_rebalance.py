"""Equity execution-desk helper — run by the scheduled agent session.

The MCP (review_equity_order/place_equity_order) is only callable BY the
agent, so this script does everything deterministic around it:

    plan   : compute the target portfolio from the live config + panel,
             diff against state/equity_state.json, print the ORDER LIST
             (dollar-based fractional market orders) the session must place.
    record : after the session places an order and sees the review/fill
             response, record it into state + trade log.
    mark   : mark-to-market the books from a JSON of {symbol: price} and
             append the equity snapshot (the session gets prices via
             get_equity_quotes).

Safety rules encoded here (session must obey the printed plan verbatim):
  * min order $2 (hysteresis), max single order = bankroll
  * cash-account discipline: never plan buys exceeding recorded settled cash;
    sells settle T+1 — the plan tags proceeds as unsettled until next day
  * drawdown kill switch shared with the crypto desk (state/KILL_SWITCH_EQ):
    when tripped, plan() emits only liquidation orders

Usage:
    python scripts/equity_rebalance.py plan
    python scripts/equity_rebalance.py record --symbol AAPL --side buy \
        --dollars 25.00 --filled-qty 0.0824 --price 303.31 --order-id <uuid>
    python scripts/equity_rebalance.py mark --prices '{"AAPL": 303.1, ...}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

from quantfirm.equities import backtest as bt  # noqa: E402
from quantfirm.equities.data import load_panel  # noqa: E402
from quantfirm.equities.strategies import load_all  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CONFIG = os.path.join(ROOT, "config", "equity_live.json")
STATE = os.path.join(ROOT, "state", "equity_state.json")
TRADE_LOG = os.path.join(ROOT, "state", "equity_trade_log.csv")
KILL = os.path.join(ROOT, "state", "KILL_SWITCH_EQ")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if not os.path.exists(STATE):
        return {"version": 1, "initialized": False, "positions": {},
                "settled_cash": 0.0, "unsettled_cash": 0.0,
                "unsettled_date": None, "peak_equity": 0.0,
                "equity_history": [], "last_rebalance": None}
    with open(STATE) as f:
        state = json.load(f)
    if "positions" not in state:
        raise RuntimeError(f"malformed {STATE}; refusing to plan")
    return state


def save_state(state: dict) -> None:
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE)


def settle(state: dict) -> None:
    """Roll unsettled sale proceeds into settled cash after T+1."""
    ud = state.get("unsettled_date")
    if ud and ud < date.today().isoformat():
        state["settled_cash"] = round(
            state.get("settled_cash", 0.0) + state.get("unsettled_cash", 0.0), 2)
        state["unsettled_cash"] = 0.0
        state["unsettled_date"] = None


def plan() -> None:
    with open(CONFIG) as f:
        cfg = json.load(f)
    state = load_state()
    settle(state)

    # Run lock: one emitted plan per UTC day. A duplicate session firing must
    # not double-rebalance (or, worse, kill-switch-liquidate lots bought
    # hours earlier with unsettled proceeds — a GFV). The stamp is written
    # only when a plan is actually emitted, so no-op runs don't burn the day.
    today = date.today().isoformat()
    if state.get("last_plan_date") == today:
        save_state(state)
        print(json.dumps({"action": "already_planned_today"})); return
    save_state(state)

    if not cfg.get("enabled", False):
        print(json.dumps({"action": "disabled_in_config"})); return
    if not state.get("initialized"):
        print(json.dumps({"action": "books_uninitialized",
                          "hint": "fund the agentic account, then record initial cash via 'record --init-cash N'"})); return

    closes = load_panel()
    last_date = str(closes.index[-1].date())
    # One-shot book reconstruction after an outside actor liquidated part of
    # the book (see quantfirm/equities/reconstruct.py). Consumes the flag so
    # it can never fire twice; every later cycle returns to the strategy's
    # own 21-day cadence.
    reconstructing = bool(state.get("reconstruct_pending"))
    if reconstructing:
        from quantfirm.equities.reconstruct import reconstruct_targets
        tgt = reconstruct_targets(closes, list(state.get("positions", {})),
                                  cfg.get("params", {}))
        target_w = pd.Series(tgt, dtype=float)
    else:
        strat = load_all()[cfg["strategy"]]
        w = strat(closes, **cfg.get("params", {}))
        target_w = w.reindex(closes.index).ffill().iloc[-1]
    target_w = target_w[target_w > 0]

    bankroll = float(cfg["risk"]["bankroll_usd"])
    positions = state.get("positions", {})
    prices = closes.iloc[-1]
    pos_value = {s: q * float(prices.get(s, 0) or 0) for s, q in positions.items()}
    equity = sum(pos_value.values()) + state["settled_cash"] + state["unsettled_cash"]
    peak = max(state.get("peak_equity", 0.0), equity)

    kill_active = os.path.exists(KILL)
    dd = equity / peak - 1 if peak > 0 else 0.0
    orders = []

    if not kill_active and peak > 0 and dd < -float(cfg["risk"]["kill_drawdown"]):
        with open(KILL, "w") as f:
            json.dump({"reason": f"drawdown {dd:.2%}", "tripped_at": _now()}, f)
        kill_active = True

    if kill_active:
        gfv_hold = state.get("gfv_hold", {})
        deferred = []
        for s, v in pos_value.items():
            if v < 2.0:
                continue
            # never liquidate a lot bought with unsettled funds before the
            # funding sale settles — that's a good-faith violation
            if gfv_hold.get(s, "") >= today:
                deferred.append(s)
                continue
            orders.append({"symbol": s, "side": "sell", "dollars": round(v, 2),
                           "reason": "kill_switch_liquidation"})
        print(json.dumps({"action": "kill_switch", "drawdown": round(dd, 4),
                          "orders": orders, "deferred_for_settlement": deferred,
                          "equity": round(equity, 2)}, indent=2))
        return

    # Hysteresis: the $0.01 SEC sell fee is 25-50bps on tiny drift orders, so
    # a rebalance must clear BOTH an absolute floor and a relative band
    # (fraction of the target position) before it's worth trading.
    min_order = float(cfg["risk"].get("min_order_usd", 5.0))
    band = float(cfg["risk"].get("rebalance_band_frac", 0.15))
    # Sizing base = the firm's OWN equity, so profits compound instead of
    # sitting idle (sizing off the static bankroll would strand every dollar
    # earned above it). Guarded two ways: never size off an equity mark more
    # than `max_growth_mult` times the original bankroll (protects against a
    # bad price mark inflating targets), and buys are still limited to
    # settled cash further below.
    growth_cap = float(cfg["risk"].get("max_growth_mult", 5.0))
    sizing_base = min(max(equity, 0.0), bankroll * growth_cap)
    target_val = {s: float(frac) * sizing_base for s, frac in target_w.items()}

    def _worth_trading(delta: float, target: float) -> bool:
        return abs(delta) >= max(min_order, band * max(target, 1.0))

    sells, buys = [], []
    for s, v in pos_value.items():
        delta = target_val.get(s, 0.0) - v
        if delta < 0 and _worth_trading(delta, target_val.get(s, v)):
            sells.append({"symbol": s, "side": "sell", "dollars": round(-delta, 2)})
    budget = state["settled_cash"] + sum(o["dollars"] for o in sells)  # sells fill first
    for s, tv in sorted(target_val.items(), key=lambda kv: -kv[1]):
        delta = tv - pos_value.get(s, 0.0)
        if delta > 0 and _worth_trading(delta, tv):
            amt = round(min(delta, max(0.0, budget)), 2)
            if amt >= min_order:
                buys.append({"symbol": s, "side": "buy", "dollars": amt})
                budget -= amt

    # Concentration surveillance. config's max_single_name_frac was never
    # enforced in code, and the strategy's inverse-vol weighting breaches it
    # in ~8% of historical rebalances (a low-vol name can draw 5x the dollars
    # of a volatile one at the same rank). Enforcing it live would deviate
    # from the backtested weights, so the plan REPORTS the breach and leaves
    # sizing untouched — the research desk owns whether to cap it.
    cap = float(cfg["risk"].get("max_single_name_frac", 1.0))
    breaches = {s: round(float(f), 4) for s, f in target_w.items() if float(f) > cap}

    state["last_plan_date"] = today
    if reconstructing:
        state["reconstruct_pending"] = False
        state.setdefault("incidents", []).append(
            {"ts": _now(), "type": "book_reconstruction",
             "detail": f"one-shot re-rank at {last_date}; targets "
                       f"{ {k: round(float(v), 4) for k, v in target_w.items()} }"})
    save_state(state)
    print(json.dumps({
        "action": "rebalance_plan", "as_of_panel_date": last_date,
        "mode": "reconstruction" if reconstructing else "scheduled",
        "equity": round(equity, 2), "sizing_base": round(sizing_base, 2),
        "drawdown": round(dd, 4),
        "settled_cash": state["settled_cash"], "unsettled_cash": state["unsettled_cash"],
        "target_weights": {s: round(float(v), 4) for s, v in target_w.items()},
        "concentration_breaches": breaches or None,
        "orders": sells + buys,
        "instructions": "Place sells first, wait for fills, then buys, via "
                        "review_equity_order -> place_equity_order (market, "
                        "dollar_amount, agentic account). Record EVERY fill "
                        "with 'record'. If any order is rejected, stop and "
                        "record what filled.",
    }, indent=2))


def record(args) -> None:
    state = load_state()
    if args.init_cash is not None:
        state.update({"initialized": True, "settled_cash": round(args.init_cash, 2),
                      "peak_equity": round(args.init_cash, 2)})
        save_state(state)
        print(json.dumps({"initialized": True, "settled_cash": args.init_cash}))
        return
    qty = float(args.filled_qty); px = float(args.price); usd = float(args.dollars)
    pos = state["positions"]
    if args.side == "buy":
        pos[args.symbol] = round(pos.get(args.symbol, 0.0) + qty, 8)
        state["settled_cash"] = round(state["settled_cash"] - usd, 2)
        # a buy made while sale proceeds are unsettled cannot be sold before
        # those proceeds settle (T+1) without a good-faith violation
        if state.get("unsettled_cash", 0.0) > 0:
            state.setdefault("gfv_hold", {})[args.symbol] = date.today().isoformat()
    else:
        pos[args.symbol] = round(max(0.0, pos.get(args.symbol, 0.0) - qty), 8)
        if pos[args.symbol] == 0:
            del pos[args.symbol]
        state["unsettled_cash"] = round(state.get("unsettled_cash", 0.0) + usd, 2)
        state["unsettled_date"] = date.today().isoformat()
    header = not os.path.exists(TRADE_LOG)
    with open(TRADE_LOG, "a") as f:
        if header:
            f.write("ts,symbol,side,dollars,filled_qty,price,order_id\n")
        f.write(f"{_now()},{args.symbol},{args.side},{usd},{qty},{px},{args.order_id}\n")
    state["last_rebalance"] = _now()
    save_state(state)
    print(json.dumps({"recorded": True, "positions": state["positions"],
                      "settled_cash": state["settled_cash"],
                      "unsettled_cash": state["unsettled_cash"]}))


def mark(args) -> None:
    state = load_state()
    prices = json.loads(args.prices)
    equity = state["settled_cash"] + state.get("unsettled_cash", 0.0) + sum(
        q * float(prices.get(s, 0) or 0) for s, q in state["positions"].items())
    state["peak_equity"] = round(max(state.get("peak_equity", 0.0), equity), 2)
    state.setdefault("equity_history", []).append([_now(), round(equity, 2)])
    state["equity_history"] = state["equity_history"][-1000:]
    save_state(state)
    print(json.dumps({"equity": round(equity, 2), "peak": state["peak_equity"],
                      "drawdown": round(equity / state["peak_equity"] - 1, 4)
                      if state["peak_equity"] > 0 else 0.0}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("record")
    r.add_argument("--symbol"); r.add_argument("--side", choices=["buy", "sell"])
    r.add_argument("--dollars", type=float, default=0.0)
    r.add_argument("--filled-qty", default="0"); r.add_argument("--price", default="0")
    r.add_argument("--order-id", default=""); r.add_argument("--init-cash", type=float)
    m = sub.add_parser("mark")
    m.add_argument("--prices", required=True)
    args = ap.parse_args()
    {"plan": lambda a: plan(), "record": record, "mark": mark}[args.cmd](args)


if __name__ == "__main__":
    main()
