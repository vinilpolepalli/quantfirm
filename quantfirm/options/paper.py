"""Deterministic tick engine for the options paper desk.

Every trading decision is made here, in code, from a quotes file the execution
agent fetched via the broker MCP. The agent's discretion is zero: it gathers
quotes, runs the tick, commits state, and mails the report. This mirrors the
equity desk's planner/executor split and is the mitigation the agentic-trading
literature (TradeTrap, AMA, FINRA 2026) points at.

PAPER ONLY. This module never emits an order ticket for a real venue.

Pre-registered strategy (docs/OPTIONS_PAPER.md is the authoritative spec):
  * SPY put credit spreads, $1 wide, 1 contract, short leg nearest -0.18 delta
    within [-0.25, -0.12], expiry 28-45 calendar days out at entry.
  * Entry gates: net mid credit >= $0.12; both legs open interest >= 100;
    combined leg spread width <= 80% of net mid; quotes fresh.
  * Exits: buy back at <= 50% of entry credit (profit), >= 2.5x entry credit
    (stop), or DTE <= 21 (time). Whichever trips first at the daily tick.
  * Limits: max 3 open positions, max 1 new position per tick, total max-loss
    across open positions <= 60% of bankroll. Equity < 75% of bankroll halts
    new entries; < 50% flattens everything (mirrors the firm drawdown ladder).

Fill model (conservative, ORATS-flavoured): a two-leg spread fills at
net_mid -/+ 0.30 * (leg width sum) — i.e. it gives up 60% of the combined
half-spread — plus $0.04/contract/side regulatory fees. Marks use net mid.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# spec constants (pre-registered; changing any of these is a strategy change
# and belongs in a reviewed commit, never in a live session)
# ---------------------------------------------------------------------------

UNDERLYING = "SPY"
BANKROLL = 500.0
WIDTH = 1.0                      # $ between strikes
QTY = 1                          # contracts per position
TARGET_DELTA = -0.18
DELTA_BAND = (-0.25, -0.12)
DTE_ENTRY = (28, 45)
DTE_EXIT = 21
MIN_CREDIT = 0.12                # net mid, per share
MIN_OI = 100
MAX_LEGSPREAD_FRAC = 0.80        # (leg width sum) / net mid
PROFIT_FRAC = 0.50               # buy back at 50% of entry credit
STOP_MULT = 2.5                  # buy back at 2.5x entry credit
MAX_OPEN = 3
MAX_NEW_PER_TICK = 1
MAX_TOTAL_RISK_FRAC = 0.60       # of bankroll
HALT_EQUITY_FRAC = 0.75          # no new entries below this
FLATTEN_EQUITY_FRAC = 0.50       # close everything below this
SLIP_FRAC = 0.30                 # of (leg width sum), paid each way
FEE_PER_CONTRACT_SIDE = 0.04     # ORF + OCC pass-through, per contract/side
QUOTE_MAX_AGE_MIN = 30           # quote staleness gate vs snapshot asof


def _fees(legs: int) -> float:
    return FEE_PER_CONTRACT_SIDE * legs * QTY


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


@dataclass
class Leg:
    option_id: str
    strike: float
    expiry: str  # YYYY-MM-DD


def _dte(expiry: str, on: date) -> int:
    y, m, d = (int(p) for p in expiry.split("-"))
    return (date(y, m, d) - on).days


def _parse_asof(quotes: dict) -> datetime:
    raw = quotes.get("asof", "")
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _fresh(contract: dict, asof: datetime) -> bool:
    raw = contract.get("updated_at")
    if not raw:
        return False
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return abs((asof - ts).total_seconds()) <= QUOTE_MAX_AGE_MIN * 60


def _mid(c: dict) -> float:
    bid, ask = float(c["bid"]), float(c["ask"])
    return (bid + ask) / 2.0


def _width(c: dict) -> float:
    return float(c["ask"]) - float(c["bid"])


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def tick(state: dict, quotes: dict, today: str, allow_entry: bool = True) -> dict:
    """Advance the paper book one day. Mutates and returns `state`.

    `quotes` schema: {"asof": iso8601, "underlying": {...},
                      "contracts": {option_id: {strike,type,expiry,bid,ask,
                                                delta,iv,oi,updated_at}}}
    Appends a report dict to state["last_report"].
    """
    on = date.fromisoformat(today)
    asof = _parse_asof(quotes)
    contracts = quotes.get("contracts", {})
    events: list[str] = []
    incidents: list[str] = []

    # ---- 1. mark open positions ------------------------------------------
    open_positions = [p for p in state["positions"] if p["status"] == "open"]
    marked_liability = 0.0
    for p in open_positions:
        cs = contracts.get(p["short"]["option_id"])
        cl = contracts.get(p["long"]["option_id"])
        p["dte"] = _dte(p["short"]["expiry"], on)
        if not cs or not cl:
            incidents.append(f"{p['id']}: quotes missing for one or both legs; carrying stale mark")
        elif not (_fresh(cs, asof) and _fresh(cl, asof)):
            incidents.append(f"{p['id']}: stale leg quotes (> {QUOTE_MAX_AGE_MIN}m); carrying stale mark")
        else:
            p["mark"] = _round2(_mid(cs) - _mid(cl))
            p["mark_width"] = _round2(_width(cs) + _width(cl))
        marked_liability += p.get("mark", p["entry_credit"]) * 100 * p["qty"]

    equity = state["cash"] - marked_liability
    state["equity"] = _round2(equity)

    # ---- 2. drawdown ladder ----------------------------------------------
    flatten = equity < FLATTEN_EQUITY_FRAC * state["bankroll_usd"]
    if flatten and open_positions:
        incidents.append("equity below 50% of bankroll: flattening all positions")
    if equity < HALT_EQUITY_FRAC * state["bankroll_usd"] and not state.get("halted"):
        state["halted"] = True
        incidents.append("equity below 75% of bankroll: new entries halted")

    # ---- 3. exits ---------------------------------------------------------
    for p in open_positions:
        reason = None
        if flatten:
            reason = "flatten"
        elif p.get("mark") is not None and p["mark"] <= p["profit_target"]:
            reason = "profit_target"
        elif p.get("mark") is not None and p["mark"] >= p["stop_level"]:
            reason = "stop"
        elif p["dte"] <= DTE_EXIT:
            reason = "time_exit"
        if not reason:
            continue
        cs = contracts.get(p["short"]["option_id"])
        cl = contracts.get(p["long"]["option_id"])
        if not cs or not cl or not (_fresh(cs, asof) and _fresh(cl, asof)):
            incidents.append(f"{p['id']}: exit '{reason}' due but quotes unusable; retry next tick")
            continue
        net_mid = _mid(cs) - _mid(cl)
        legspread = _width(cs) + _width(cl)
        debit = _round2(max(0.0, net_mid + SLIP_FRAC * legspread))
        fee = _fees(2)
        pnl = _round2((p["entry_credit"] - debit) * 100 * p["qty"] - fee - p["fees_open"])
        state["cash"] = _round2(state["cash"] - debit * 100 * p["qty"] - fee)
        p.update(status="closed", closed=today, exit_reason=reason,
                 exit_debit=debit, exit_net_mid=_round2(net_mid), fees_close=fee,
                 realized_pnl=pnl)
        events.append(f"CLOSED {p['id']} ({reason}) debit {debit:.2f} vs mid "
                      f"{net_mid:.2f} -> P&L ${pnl:+.2f}")

    # ---- 4. entry ---------------------------------------------------------
    still_open = [p for p in state["positions"] if p["status"] == "open"]
    open_risk = sum((p["width"] - p["entry_credit"]) * 100 * p["qty"] for p in still_open)
    can_enter = (allow_entry and not state.get("halted") and not flatten
                 and len(still_open) < MAX_OPEN)
    if can_enter:
        cand = _pick_entry(contracts, asof, on, state, events)
        if cand:
            short_c, long_c, credit, net_mid, legspread = cand
            max_loss = (WIDTH - credit) * 100 * QTY + _fees(2) * 2
            if open_risk + max_loss > MAX_TOTAL_RISK_FRAC * state["bankroll_usd"]:
                events.append("entry candidate found but total open risk cap "
                              f"(${MAX_TOTAL_RISK_FRAC * state['bankroll_usd']:.0f}) would be exceeded; skipped")
            else:
                fee = _fees(2)
                seq = state.get("seq", 0) + 1
                state["seq"] = seq
                pos = {
                    "id": f"PCS-{today.replace('-', '')}-{seq:02d}",
                    "underlying": UNDERLYING,
                    "structure": "put_credit_spread",
                    "short": {"option_id": short_c["id"], "strike": float(short_c["strike"]),
                              "expiry": short_c["expiry"]},
                    "long": {"option_id": long_c["id"], "strike": float(long_c["strike"]),
                             "expiry": long_c["expiry"]},
                    "qty": QTY, "width": WIDTH, "opened": today,
                    "entry_credit": credit, "entry_net_mid": _round2(net_mid),
                    "entry_slippage": _round2(net_mid - credit),
                    "entry_legspread": _round2(legspread),
                    "entry_short_delta": float(short_c.get("delta", 0.0)),
                    "entry_short_iv": float(short_c.get("iv", 0.0)),
                    "fees_open": fee, "status": "open",
                    "mark": credit, "dte": _dte(short_c["expiry"], on),
                    "profit_target": _round2(credit * PROFIT_FRAC),
                    "stop_level": _round2(credit * STOP_MULT),
                }
                state["cash"] = _round2(state["cash"] + credit * 100 * QTY - fee)
                state["positions"].append(pos)
                events.append(
                    f"OPENED {pos['id']}: short {short_c['strike']}P / long {long_c['strike']}P "
                    f"{short_c['expiry']} (dte {pos['dte']}, delta {pos['entry_short_delta']:.2f}) "
                    f"credit {credit:.2f} (mid {net_mid:.2f}), max loss "
                    f"${(WIDTH - credit) * 100:.0f}")

    # ---- 5. re-mark equity and record ------------------------------------
    open_after = [p for p in state["positions"] if p["status"] == "open"]
    liability = sum(p.get("mark", p["entry_credit"]) * 100 * p["qty"] for p in open_after)
    state["equity"] = _round2(state["cash"] - liability)
    state["incidents"].extend(f"{today}: {i}" for i in incidents)
    row = {"date": today, "equity": state["equity"], "cash": state["cash"],
           "open": len(open_after),
           "spy": float(quotes.get("underlying", {}).get("last", 0.0)) or None}
    state["history"].append(row)
    state["last_report"] = _report(state, row, events, incidents, on)
    return state


def _pick_entry(contracts: dict, asof: datetime, on: date, state: dict,
                events: list) -> tuple | None:
    held = {p["short"]["option_id"] for p in state["positions"] if p["status"] == "open"}
    by_key = {}
    for oid, c in contracts.items():
        if c.get("type") != "put":
            continue
        c = dict(c, id=oid)
        by_key[(c["expiry"], float(c["strike"]))] = c

    best = None
    for (expiry, strike), c in by_key.items():
        dte = _dte(expiry, on)
        if not (DTE_ENTRY[0] <= dte <= DTE_ENTRY[1]):
            continue
        delta = c.get("delta")
        if delta is None or not (DELTA_BAND[0] <= float(delta) <= DELTA_BAND[1]):
            continue
        if c["id"] in held:
            continue
        long_c = by_key.get((expiry, strike - WIDTH))
        if not long_c:
            continue
        if not (_fresh(c, asof) and _fresh(long_c, asof)):
            continue
        if int(c.get("oi", 0)) < MIN_OI or int(long_c.get("oi", 0)) < MIN_OI:
            continue
        net_mid = _mid(c) - _mid(long_c)
        if net_mid < MIN_CREDIT:
            continue
        legspread = _width(c) + _width(long_c)
        if legspread > MAX_LEGSPREAD_FRAC * net_mid:
            continue
        score = abs(float(delta) - TARGET_DELTA)
        if best is None or score < best[0]:
            best = (score, c, long_c, net_mid, legspread)

    if best is None:
        events.append("no entry: no candidate passed the gates "
                      "(delta band, credit floor, OI, leg-spread cap, freshness)")
        return None
    _, c, long_c, net_mid, legspread = best
    credit = _round2(net_mid - SLIP_FRAC * legspread)
    if credit < MIN_CREDIT:
        events.append(f"no entry: best candidate credit {credit:.2f} after "
                      "modeled slippage fell below the floor")
        return None
    return c, long_c, credit, net_mid, legspread


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def _report(state: dict, row: dict, events: list, incidents: list, on: date) -> dict:
    start = date.fromisoformat(state["started"])
    day_n = (on - start).days + 1
    closed = [p for p in state["positions"] if p["status"] == "closed"]
    realized = _round2(sum(p.get("realized_pnl", 0.0) for p in closed))
    return {
        "date": row["date"], "day": day_n,
        "equity": state["equity"], "bankroll": state["bankroll_usd"],
        "pnl_total": _round2(state["equity"] - state["bankroll_usd"]),
        "pnl_realized": realized,
        "open": [
            {"id": p["id"],
             "legs": f"-{p['short']['strike']:.0f}P/+{p['long']['strike']:.0f}P {p['short']['expiry']}",
             "dte": p["dte"], "entry_credit": p["entry_credit"],
             "mark": p.get("mark"),
             "unrealized": _round2((p["entry_credit"] - p.get("mark", p["entry_credit"]))
                                   * 100 * p["qty"] - p["fees_open"])}
            for p in state["positions"] if p["status"] == "open"],
        "events": events, "incidents": incidents,
        "halted": bool(state.get("halted")),
        "spy": row.get("spy"),
    }


def render_daily(report: dict) -> str:
    lines = [
        f"quantfirm options paper desk — day {report['day']} ({report['date']})",
        "=" * 60,
        f"equity        ${report['equity']:.2f}  "
        f"({report['pnl_total']:+.2f} vs ${report['bankroll']:.0f} start)",
    ]
    lines.append(f"realized P&L  ${report['pnl_realized']:+.2f}")
    if report.get("spy"):
        lines.append(f"SPY           {report['spy']:.2f}")
    if report["halted"]:
        lines.append("STATUS        HALTED — no new entries (drawdown ladder)")
    lines.append("")
    if report["open"]:
        lines.append("open positions:")
        for p in report["open"]:
            mark = f"{p['mark']:.2f}" if p.get("mark") is not None else "stale"
            lines.append(f"  {p['id']}  {p['legs']}  dte {p['dte']:>2}  "
                         f"credit {p['entry_credit']:.2f} -> mark {mark}  "
                         f"unrl ${p['unrealized']:+.2f}")
    else:
        lines.append("open positions: none")
    lines.append("")
    lines.append("today:")
    for e in report["events"] or ["(no actions)"]:
        lines.append(f"  - {e}")
    for i in report["incidents"]:
        lines.append(f"  ! {i}")
    lines.append("")
    lines.append("paper simulation — fills modeled at 60% of combined half-spread "
                 "plus $0.04/contract/side; not real orders, not investment advice.")
    return "\n".join(lines)


def render_weekly(state: dict, today: str) -> str:
    on = date.fromisoformat(today)
    week_ago = on - timedelta(days=7)
    hist = [h for h in state["history"] if h["date"] >= state["started"]]
    week = [h for h in hist if date.fromisoformat(h["date"]) > week_ago]
    closed = [p for p in state["positions"] if p["status"] == "closed"]
    closed_week = [p for p in closed if p.get("closed", "") > week_ago.isoformat()]
    start_eq = week[0]["equity"] if week else state["bankroll_usd"]
    lines = [
        f"quantfirm options paper desk — weekly report (week ending {today})",
        "=" * 64,
        f"equity ${state['equity']:.2f} | week P&L ${state['equity'] - start_eq:+.2f} | "
        f"since start ${state['equity'] - state['bankroll_usd']:+.2f} on ${state['bankroll_usd']:.0f}",
        "",
        f"trades closed this week: {len(closed_week)}",
    ]
    for p in closed_week:
        lines.append(f"  {p['id']}  opened {p['opened']} closed {p['closed']} "
                     f"({p['exit_reason']})  credit {p['entry_credit']:.2f} -> "
                     f"debit {p['exit_debit']:.2f}  P&L ${p['realized_pnl']:+.2f}")
    # cost accounting — the number this paper run exists to measure
    all_pos = [p for p in state["positions"]]
    slip = sum(p.get("entry_slippage", 0.0) * 100 * p["qty"] for p in all_pos)
    slip += sum((p.get("exit_debit", 0.0) - p.get("exit_net_mid", 0.0)) * 100 * p["qty"]
                for p in closed)
    fees = sum(p.get("fees_open", 0.0) + p.get("fees_close", 0.0) for p in all_pos)
    lines += [
        "",
        f"cost meter (cumulative): modeled slippage ${slip:.2f}, fees ${fees:.2f} "
        f"— {100 * (slip + fees) / state['bankroll_usd']:.1f}% of bankroll",
        f"incidents to date: {len(state['incidents'])}",
        "",
        "equity curve:",
    ]
    for h in hist:
        lines.append(f"  {h['date']}  ${h['equity']:.2f}  open {h['open']}")
    lines.append("")
    lines.append("paper simulation — see docs/OPTIONS_PAPER.md for the "
                 "pre-registered spec and what this window can and cannot prove.")
    return "\n".join(lines)


def new_state(started: str, ends: str) -> dict:
    return {
        "desk": "options_paper", "version": 1,
        "started": started, "ends": ends,
        "bankroll_usd": BANKROLL, "cash": BANKROLL, "equity": BANKROLL,
        "halted": False, "seq": 0,
        "positions": [], "history": [], "incidents": [],
        "registry": {},
    }
