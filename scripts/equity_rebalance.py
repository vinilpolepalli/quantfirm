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
    python scripts/equity_rebalance.py reconcile-cash --venue-cash 16.19 \
        --note "owner deposit"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone, date

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


# NYSE full closures. Only used to decide whether the panel is missing a
# session — a wrong entry costs at most one deferred rebalance, never a trade
# on stale data. Past 2027 the check degrades to weekdays-only, which is
# stricter (a holiday reads as a missing session), so it stays fail-closed.
NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def missing_sessions(panel_end: date, today: date) -> list[str]:
    """Trading sessions that closed after `panel_end` and before `today`.

    Non-empty means the panel is missing at least one completed close, so the
    strategy would rank and band-check against a market it cannot see. Today
    itself is excluded — its close does not exist while the desk is planning.
    """
    out, d = [], panel_end + timedelta(days=1)
    while d < today:
        if d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def resolve_account(cfg: dict) -> str | None:
    """Account number is deliberately NOT stored in the repo (it is an account
    identifier, and this repo is shareable). Resolution order: environment
    variable, then a gitignored local override, then config only if it looks
    like a real account rather than the placeholder. Returns None when
    unresolved — callers must refuse to trade rather than guess."""
    env = os.environ.get("QF_EQUITY_ACCOUNT", "").strip()
    if env.isdigit():
        return env
    local = os.path.join(ROOT, "config", "account.local.json")
    if os.path.exists(local):
        try:
            with open(local) as f:
                v = str(json.load(f).get("account_number", "")).strip()
            if v.isdigit():
                return v
        except Exception:
            pass
    v = str(cfg.get("account_number", "")).strip()
    return v if v.isdigit() else None


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


def reconcile_cash(args) -> None:
    """Bring recorded settled cash to the broker's figure.

    The runbook has always said "reconcile before planning", but there was no
    primitive for the cash leg, so the books could only ever drift. Cash that
    appears after inception (an owner deposit, proceeds from lots that were in
    the account before the mandate started) is real spendable money, but it is
    NOT profit — so it raises the cost basis rather than the P&L. Without that,
    every dollar added to the account would show up on a public dashboard as
    performance.

    Direction matters. A surplus is booked as a contribution. A shortfall is
    the signature of an outside actor moving money out, and this desk has seen
    that happen: it is recorded and refused, never silently absorbed.
    """
    state = load_state()
    books = round(state.get("settled_cash", 0.0), 2)
    venue = round(float(args.venue_cash), 2)
    delta = round(venue - books, 2)

    if abs(delta) < 0.01:
        print(json.dumps({"action": "cash_in_sync", "settled_cash": books})); return

    if delta < 0:
        state.setdefault("incidents", []).append(
            {"ts": _now(), "type": "cash_shortfall_refused",
             "detail": f"venue settled cash {venue} is {abs(delta)} BELOW books "
                       f"{books}; not absorbed. Investigate before trading.",
             "note": args.note or ""})
        save_state(state)
        print(json.dumps({"action": "cash_shortfall_refused", "books": books,
                          "venue": venue, "delta": delta,
                          "hint": "money left the account — audit orders and "
                                  "transfers before the desk trades again"}, indent=2))
        sys.exit(1)

    state["settled_cash"] = venue
    state["cost_basis"] = round(state.get("cost_basis", 250.0) + delta, 2)
    state.setdefault("contributions", []).append(
        {"ts": _now(), "amount": delta, "note": args.note or ""})
    state.setdefault("incidents", []).append(
        {"ts": _now(), "type": "cash_contribution",
         "detail": f"settled_cash {books} -> {venue} (+{delta}); cost_basis "
                   f"-> {state['cost_basis']}", "note": args.note or ""})
    save_state(state)
    print(json.dumps({"action": "cash_reconciled", "added": delta,
                      "settled_cash": venue,
                      "cost_basis": state["cost_basis"]}, indent=2))


def resume(args) -> None:
    """Clear a tripped kill switch and rebase the drawdown reference.

    Deleting state/KILL_SWITCH_EQ by hand does not work: peak_equity never
    decays, so the very next plan measures drawdown against the old high-water
    mark and re-trips immediately. Recovery therefore has to rebase the peak to
    current equity, which is a real decision — it forfeits the old high-water
    mark — so it is explicit, logged, and never automatic.
    """
    state = load_state()
    hist = state.get("equity_history", [])
    if not hist:
        sys.exit("no equity history — cannot rebase a peak that does not exist")
    equity = float(hist[-1][1])
    old_peak = float(state.get("peak_equity", equity) or equity)
    tripped = os.path.exists(KILL)

    if not tripped and equity >= old_peak:
        print(json.dumps({"action": "nothing_to_resume",
                          "kill_switch": False, "equity": equity,
                          "peak_equity": old_peak})); return

    if not args.i_accept:
        dd = equity / old_peak - 1 if old_peak else 0.0
        sys.exit(json.dumps({
            "action": "resume_requires_acknowledgement",
            "kill_switch_present": tripped,
            "equity": equity, "peak_equity": old_peak,
            "drawdown_vs_peak": round(dd, 4),
            "what_this_does": (
                f"clears state/KILL_SWITCH_EQ and rebases peak_equity "
                f"{old_peak} -> {equity}, so the {dd:.1%} drawdown is written "
                f"off and future drawdown is measured from here"),
            "how": "re-run with --i-accept",
        }, indent=2))

    if tripped:
        os.remove(KILL)
    state["peak_equity"] = round(equity, 2)
    state.setdefault("incidents", []).append({
        "ts": _now(), "type": "kill_switch_resume",
        "detail": (f"kill switch cleared (present={tripped}); peak_equity "
                   f"rebased {old_peak} -> {round(equity, 2)}; prior drawdown "
                   f"{equity / old_peak - 1:.2%} written off")})
    save_state(state)
    print(json.dumps({"action": "resumed", "kill_switch_cleared": tripped,
                      "peak_equity": round(equity, 2)}, indent=2))


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

    # Stale-panel guard. EQUITY.md has always documented "plan refuses stale
    # panels" but nothing enforced it, and nothing refreshed the panel either,
    # so the desk silently ranked and band-checked on a market it could not
    # see. A holding can breach its rebalance band on a session the planner is
    # blind to — exactly the failure that left cash idle while WDC drifted
    # 21% below target. Refuse rather than trade on a stale view.
    missing = missing_sessions(closes.index[-1].date(), date.today())
    if missing:
        # Record it: a day with no trades and no explanation is
        # indistinguishable on the dashboard from a day the strategy chose to
        # hold, and those are very different things.
        incs = state.setdefault("incidents", [])
        if not any(i.get("type") == "stale_panel" and i["ts"][:10] == today
                   for i in incs):
            incs.append({"ts": _now(), "type": "stale_panel",
                         "detail": f"panel ends {last_date}; missing "
                                   f"{', '.join(missing)} — refused to plan"})
            save_state(state)
        print(json.dumps({
            "action": "stale_panel_refusing_to_trade",
            "panel_last_date": last_date,
            "missing_sessions": missing,
            "hint": "run scripts/update_equities.py, then re-run plan",
        }, indent=2))
        return
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

    # Single-name concentration cap. config declared max_single_name_frac but
    # nothing enforced it; the strategy's inverse-vol weighting hands a low-vol
    # name a huge share whenever the ranks mix calm and volatile stocks (8% of
    # backtest rebalances exceeded 34%, once reaching 45%). This is a DELIBERATE
    # live-vs-research divergence: a declared risk limit that silently does not
    # bind is worse than no limit. Excess is redistributed to names with room;
    # anything that cannot be placed stays in cash.
    cap_frac = float(cfg["risk"].get("max_single_name_frac", 1.0))
    cap_usd = cap_frac * sizing_base
    capped = []
    if 0 < cap_frac < 1.0:
        for _ in range(10):
            excess, room = 0.0, {}
            for s, v in target_val.items():
                if v > cap_usd + 1e-9:
                    excess += v - cap_usd
                    target_val[s] = cap_usd
                    if s not in capped:
                        capped.append(s)
                else:
                    room[s] = cap_usd - v
            total_room = sum(room.values())
            if excess <= 1e-9 or total_room <= 1e-9:
                break
            share = min(1.0, excess / total_room)
            for s, r in room.items():
                target_val[s] += r * share
            if excess <= total_room:
                break

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
        "account_number": resolve_account(cfg) or "UNRESOLVED — set QF_EQUITY_ACCOUNT; do NOT trade",
        "equity": round(equity, 2), "sizing_base": round(sizing_base, 2),
        "position_cap_applied": capped, "drawdown": round(dd, 4),
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
    state["last_prices"] = {k: float(v) for k, v in prices.items()}
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
    rs = sub.add_parser("resume")
    rs.add_argument("--i-accept", action="store_true",
                    help="acknowledge that resuming writes off the drawdown "
                         "by rebasing peak_equity to current equity")
    rc = sub.add_parser("reconcile-cash")
    rc.add_argument("--venue-cash", type=float, required=True,
                    help="broker settled cash, from get_portfolio/get_accounts")
    rc.add_argument("--note", default="", help="why the books differ")
    args = ap.parse_args()
    {"plan": lambda a: plan(), "record": record, "mark": mark,
     "reconcile-cash": reconcile_cash, "resume": resume}[args.cmd](args)


if __name__ == "__main__":
    main()
