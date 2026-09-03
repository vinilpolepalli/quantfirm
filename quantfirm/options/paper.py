"""Deterministic tick engine for the options paper desk — v2 HIGH-RISK MANDATE.

Every trading decision is made here, in code, from a quotes file the execution
agent fetched via the broker MCP. The agent's discretion is zero: it gathers
quotes, runs the tick, commits state, and mails the report. This mirrors the
equity desk's planner/executor split and is the mitigation the agentic-trading
literature (TradeTrap, AMA, FINRA 2026) points at.

PAPER ONLY. This module never emits an order ticket for a real venue.

v2 (2026-09-01): the owner replaced the conservative mandate with an explicit
MAXIMUM-RISK mandate. The desk now runs several aggressive sleeves at once.
Every sleeve remains BOUNDED-LOSS — no naked short options are simulated, so the
book can lose everything but never more than everything. docs/OPTIONS_PAPER_V2.md
is the authoritative spec; the SLEEVES table below is the machine-readable copy.

Accounting is signed so credit and debit structures share one code path:

    net_mark = sum over legs of (+1 long / -1 short) * mid * ratio
    equity   = cash + sum(net_mark * 100 * qty)
    paid_open      = net_mid + SLIP * legspread_sum   (slippage always hurts)
    received_close = net_mid - SLIP * legspread_sum
    pnl = (received_close - paid_open) * 100 * qty - fees

Expiry settlement (absent in v1, load-bearing here because sleeves run short DTE):
    intrinsic(call, S) = max(0, S - K);  intrinsic(put, S) = max(0, K - S)
    settle_value = sum(sign_leg * intrinsic * ratio)
    pnl = (settle_value - paid_open) * 100 * qty - fees_open
Expiry-day ticks force-close at live quotes (mirroring Robinhood's 15:45 ET
sellout); positions that expired unseen settle from snapshot["settle_prices"].
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# account-level constants (pre-registered; changing any of these is a strategy
# change and belongs in a reviewed commit, never in a live session)
# ---------------------------------------------------------------------------

BANKROLL = 500.0
SLIP_FRAC = 0.30                 # of summed leg bid-ask widths, paid each way
FEE_PER_CONTRACT_SIDE = 0.04     # ORF + OCC pass-through, per contract per side
QUOTE_MAX_AGE_MIN = 30           # staleness gate vs snapshot asof

# Loosened drawdown ladder (v1 was 0.75 / 0.50). The owner's mandate accepts
# losing the simulated book; these floors exist only so a wiped book stops
# trading rather than reporting nonsense.
HALT_EQUITY_FRAC = 0.40          # no new entries below this fraction of bankroll
FLATTEN_EQUITY_FRAC = 0.20       # close everything below this

# Owner instruction 2026-09-01: do not trade SPY any more. Enforced here rather
# than only by editing a sleeve's underlyings, so re-adding SPY to a config
# cannot quietly resume trading it.
BANNED_UNDERLYINGS = {"SPY"}

MAX_OPEN_TOTAL = 8               # across all sleeves
MAX_NEW_PER_TICK = 3             # across all sleeves
MAX_TOTAL_RISK_FRAC = 1.00       # 100% of bankroll may be at risk simultaneously

# ---------------------------------------------------------------------------
# SLEEVES — tuned from the v2 design workflow. See docs/OPTIONS_PAPER_V2.md.
# ---------------------------------------------------------------------------

# Two sleeves, chosen to attack the book from opposite directions at once:
# FAT sells short-dated premium on BOTH sides of two index ETFs (get run over in
# either direction, no stop, held to expiry — maximum gamma), while LOTTO buys
# short-dated OTM options on high-beta single names (the single worst-expectancy
# trade in the literature, ridden to zero). Together they deploy ~98% of the
# book. Every ticket is bounded-loss; the book can go to zero but not below.
SLEEVES = {
    "fat": {
        "enabled": True, "kind": "credit_spread", "tag": "FAT",
        "underlyings": ["QQQ"],         # SPY removed 2026-09-01 by owner instruction
        "sides": ["put", "call"],       # both sides at once = defined-risk strangle
        "width": 2.0,
        "delta_band": (0.28, 0.45),     # v1 was 0.12-0.25
        "target_delta": 0.35,           # ~35% chance of finishing ITM, by design
        "dte_band": (2, 9),             # v1 was 28-45; this is the gamma zone
        "qty": 1,
        "min_credit_frac": 0.12,        # >= 12% of width, i.e. >= $0.24 on $2
        "min_oi": 250,
        "max_legspread_frac": 1.20,
        "max_open": 3,
        "profit_frac": 0.25,            # buy back once 75% of the credit is captured
        "stop_mult": None,              # NO STOP — ride it into expiry
        "dte_exit": None,               # no time exit either; let it settle
    },
    # Not a trading sleeve: it only carries the v1 exit rules for the two
    # migrated positions. Without this entry SLEEVES.get("legacy") returns {} and
    # those positions have NO profit target, stop, or time exit at all.
    "legacy": {
        "enabled": False, "kind": "credit_spread", "tag": "PCS",
        "underlyings": [], "sides": [], "width": 1.0,
        "delta_band": (0.0, 0.0), "target_delta": 0.18, "dte_band": (0, 0),
        "qty": 1, "min_credit_frac": 0.0, "min_oi": 0,
        "max_legspread_frac": 0.0, "max_open": 0,
        "profit_frac": 0.50,            # v1: buy back at 50% of credit
        "stop_mult": 2.5,               # v1: stop at 2.5x credit
        "dte_exit": 21,                 # v1: time exit at 21 DTE
    },
    "lotto": {
        "enabled": True, "kind": "long_option", "tag": "LOT",
        "underlyings": ["NVDA", "TSLA", "PLTR", "AMD", "COIN"],
        "sides": ["call", "put"],       # direction from the momentum signal
        "delta_band": (0.15, 0.35),
        "target_delta": 0.25,           # ~75% chance of expiring worthless
        "dte_band": (1, 8),
        "min_oi": 250,
        "max_legspread_frac": 1.20,
        "ticket_usd": 45.0,
        "max_open": 3,
        "profit_mult": 1.0,             # sell at +100%
        "stop_frac": None,              # no stop — ride it to zero
        "dte_exit": None,
        "earnings_boost": True,         # prefer names printing inside the option's life
    },
}


def _install_sleeves(table: dict) -> None:
    SLEEVES.clear()
    SLEEVES.update(table)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _strike(x: float) -> str:
    """Render a strike without lying about it.

    ``f"{232.5:.0f}"`` is ``"232"`` — a different, real contract. Single names
    list half-strikes, so every strike shown to a human goes through here.
    """
    return f"{float(x):g}"


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def _fees(n_legs: int, qty: int) -> float:
    return FEE_PER_CONTRACT_SIDE * n_legs * qty


def _dte(expiry: str, on: date) -> int:
    y, m, d = (int(p) for p in expiry.split("-"))
    return (date(y, m, d) - on).days


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _fresh(c: dict, asof: datetime) -> bool:
    raw = c.get("updated_at")
    if not raw:
        return False
    return abs((asof - _parse_ts(raw)).total_seconds()) <= QUOTE_MAX_AGE_MIN * 60


def _mid(c: dict) -> float:
    return (float(c["bid"]) + float(c["ask"])) / 2.0


def _spread(c: dict) -> float:
    return float(c["ask"]) - float(c["bid"])


def _sign(side: str) -> int:
    return 1 if side == "long" else -1


def _intrinsic(kind: str, strike: float, s: float) -> float:
    return max(0.0, s - strike) if kind == "call" else max(0.0, strike - s)


# ---------------------------------------------------------------------------
# position pricing
# ---------------------------------------------------------------------------

def _price(pos: dict, contracts: dict, asof: datetime):
    """(net_mid, legspread_sum) for a position, or None when a leg is unusable."""
    net, spread_sum = 0.0, 0.0
    for leg in pos["legs"]:
        c = contracts.get(leg["option_id"])
        if not c or not _fresh(c, asof):
            return None
        r = leg.get("ratio", 1)
        net += _sign(leg["side"]) * _mid(c) * r
        spread_sum += _spread(c) * r
    return _round2(net), _round2(spread_sum)


def _settle(pos: dict, s: float) -> float:
    """Signed value of the position at expiry given underlying price s."""
    v = 0.0
    for leg in pos["legs"]:
        v += _sign(leg["side"]) * _intrinsic(leg["type"], float(leg["strike"]),
                                             s) * leg.get("ratio", 1)
    return _round2(v)


def _max_loss(is_debit: bool, paid_open: float, qty: int, width: float) -> float:
    """Worst-case USD loss. Every structure here is bounded by construction:
    a debit can only lose what it paid; a credit spread can only lose the
    width less the credit received (paid_open is negative for credits)."""
    if is_debit:
        return _round2(paid_open * 100 * qty)
    return _round2((width + paid_open) * 100 * qty)


def _expiry_of(pos: dict) -> str:
    return min(leg["expiry"] for leg in pos["legs"])


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

def tick(state: dict, quotes: dict, today: str, allow_entry: bool = True) -> dict:
    """Advance the paper book one day. Mutates and returns `state`."""
    on = date.fromisoformat(today)
    asof = _parse_ts(quotes["asof"])
    contracts = quotes.get("contracts", {})
    unders = quotes.get("underlyings", {})
    settle_px = quotes.get("settle_prices", {})
    events: list[str] = []
    incidents: list[str] = []

    # ---- 1. settle anything that expired, then mark the rest ---------------
    for p in [q for q in state["positions"] if q["status"] == "open"]:
        exp = _expiry_of(p)
        p["dte"] = _dte(exp, on)
        if p["dte"] < 0:
            key = f'{p["underlying"]}|{exp}'
            s = settle_px.get(key)
            if s is None:
                incidents.append(
                    f'{p["id"]}: expired {exp} but no settle price for {key}; '
                    "holding until supplied")
                continue
            _close_at(state, p, _settle(p, float(s)), today, "expired",
                      fee=0.0, events=events,
                      note=f'settled at {p["underlying"]} {float(s):.2f}')
            continue
        pr = _price(p, contracts, asof)
        if pr is None:
            incidents.append(f'{p["id"]}: stale or missing leg quotes; carrying stale mark')
        else:
            p["mark"], p["mark_spread"] = pr

    # ---- 2. account-level ladder ------------------------------------------
    equity = _equity(state)
    flatten = equity < FLATTEN_EQUITY_FRAC * state["bankroll_usd"]
    if flatten:
        incidents.append(f"equity {equity:.2f} below "
                         f"{FLATTEN_EQUITY_FRAC:.0%} of bankroll: flattening")
    if equity < HALT_EQUITY_FRAC * state["bankroll_usd"] and not state.get("halted"):
        state["halted"] = True
        incidents.append(f"equity {equity:.2f} below "
                         f"{HALT_EQUITY_FRAC:.0%} of bankroll: entries halted")

    # ---- 3. exits ----------------------------------------------------------
    for p in [q for q in state["positions"] if q["status"] == "open"]:
        if p.get("mark") is None:
            continue
        cfg = SLEEVES.get(p["sleeve"], {})
        reason = None
        if flatten:
            reason = "flatten"
        elif p["dte"] == 0:
            reason = "expiry_day_sellout"          # mirrors RH 15:45 ET sellout
        elif _hit_profit(p, cfg):
            reason = "profit_target"
        elif _hit_stop(p, cfg):
            reason = "stop"
        elif cfg.get("dte_exit") is not None and p["dte"] <= cfg["dte_exit"]:
            reason = "time_exit"
        if not reason:
            continue
        pr = _price(p, contracts, asof)
        if pr is None:
            incidents.append(f'{p["id"]}: exit "{reason}" due but quotes unusable; retry next tick')
            continue
        net_mid, legspread = pr
        received = _round2(net_mid - SLIP_FRAC * legspread)
        _close_at(state, p, received, today, reason,
                  fee=_fees(len(p["legs"]), p["qty"]), events=events,
                  exit_mid=net_mid)

    # ---- 4. entries --------------------------------------------------------
    opened = 0
    if allow_entry and not state.get("halted") and not flatten:
        for name, cfg in SLEEVES.items():
            if opened >= MAX_NEW_PER_TICK:
                break
            if not cfg.get("enabled", True):
                continue
            n_open = sum(1 for q in state["positions"]
                         if q["status"] == "open" and q["sleeve"] == name)
            if n_open >= cfg["max_open"]:
                continue
            if len([q for q in state["positions"] if q["status"] == "open"]) >= MAX_OPEN_TOTAL:
                break
            cand = _pick(name, cfg, quotes, contracts, unders, state, on, asof, events)
            if not cand:
                continue
            risk_now = sum(q["max_loss"] for q in state["positions"] if q["status"] == "open")
            cap = MAX_TOTAL_RISK_FRAC * state["bankroll_usd"]
            if risk_now + cand["max_loss"] > cap:
                events.append(f"{name}: candidate skipped, open risk "
                              f"${risk_now:.0f} + ${cand['max_loss']:.0f} exceeds ${cap:.0f} cap")
                continue
            _open(state, cand, today, events)
            opened += 1

    # ---- 5. record ---------------------------------------------------------
    state["equity"] = _equity(state)
    state["incidents"].extend(f"{today}: {i}" for i in incidents)
    open_now = [q for q in state["positions"] if q["status"] == "open"]
    ref_sym = next((u for c in SLEEVES.values() if c.get("enabled")
                    for u in c.get("underlyings", [])), None)
    row = {"date": today, "equity": state["equity"], "cash": _round2(state["cash"]),
           "open": len(open_now),
           "risk": _round2(sum(q["max_loss"] for q in open_now)),
           "ref_sym": ref_sym,
           "ref_px": unders.get(ref_sym, {}).get("last") if ref_sym else None}
    state["history"].append(row)
    state["last_report"] = _report(state, row, events, incidents, on)
    return state


def _equity(state: dict) -> float:
    v = state["cash"]
    for p in state["positions"]:
        if p["status"] == "open":
            v += p.get("mark", p["paid_open"]) * 100 * p["qty"]
    return _round2(v)


def _hit_profit(p: dict, cfg: dict) -> bool:
    """Credit: buy back once the liability decays to profit_frac of the credit.
    Debit: sell once the premium has grown by profit_mult (1.0 == +100%)."""
    entry = p["paid_open"]
    if entry < 0:
        frac = cfg.get("profit_frac")
        return frac is not None and p["mark"] >= entry * frac
    mult = cfg.get("profit_mult")
    return mult is not None and p["mark"] >= entry * (1.0 + mult)


def _hit_stop(p: dict, cfg: dict) -> bool:
    """Credit: liability grew to stop_mult x the credit. Debit: premium lost
    stop_frac of its value. Either may be None, meaning no stop (ride it out)."""
    entry = p["paid_open"]
    if entry < 0:
        mult = cfg.get("stop_mult")
        return mult is not None and p["mark"] <= entry * mult
    frac = cfg.get("stop_frac")
    return frac is not None and p["mark"] <= entry * (1.0 - frac)


def _close_at(state: dict, p: dict, received: float, today: str, reason: str,
              fee: float, events: list, note: str = "", exit_mid: float = None) -> None:
    qty = p["qty"]
    pnl = _round2((received - p["paid_open"]) * 100 * qty - fee - p["fees_open"])
    state["cash"] = _round2(state["cash"] + received * 100 * qty - fee)
    p.update(status="closed", closed=today, exit_reason=reason,
             exit_price=received, exit_mid=received if exit_mid is None else exit_mid,
             fees_close=fee, realized_pnl=pnl)
    tail = f" ({note})" if note else ""
    events.append(f'CLOSED {p["id"]} [{p["sleeve"]}] {reason}{tail} '
                  f'at {received:+.2f} vs entry {p["paid_open"]:+.2f} -> P&L ${pnl:+.2f}')


def _open(state: dict, cand: dict, today: str, events: list) -> None:
    seq = state.get("seq", 0) + 1
    state["seq"] = seq
    fee = _fees(len(cand["legs"]), cand["qty"])
    pos = {
        "id": f'{cand["tag"]}-{today.replace("-", "")}-{seq:02d}',
        "sleeve": cand["sleeve"], "underlying": cand["underlying"],
        "structure": cand["structure"], "legs": cand["legs"], "qty": cand["qty"],
        "width": cand.get("width", 0.0), "opened": today,
        "paid_open": cand["paid_open"], "entry_mid": cand["net_mid"],
        "entry_slippage": _round2(cand["paid_open"] - cand["net_mid"]),
        "entry_legspread": cand["legspread"], "entry_delta": cand.get("delta"),
        "entry_iv": cand.get("iv"), "entry_underlying": cand.get("spot"),
        "max_loss": cand["max_loss"], "fees_open": fee, "status": "open",
        "mark": cand["paid_open"], "dte": cand["dte"],
    }
    state["cash"] = _round2(state["cash"] - cand["paid_open"] * 100 * cand["qty"] - fee)
    state["positions"].append(pos)
    kind = "credit" if cand["paid_open"] < 0 else "debit"
    events.append(
        f'OPENED {pos["id"]} [{cand["sleeve"]}] {cand["desc"]} '
        f'{kind} {abs(cand["paid_open"]):.2f} (mid {abs(cand["net_mid"]):.2f}) '
        f'x{cand["qty"]}, max loss ${cand["max_loss"]:.0f}')


# ---------------------------------------------------------------------------
# candidate selection — one deterministic total order per sleeve
# ---------------------------------------------------------------------------

def _chain(contracts: dict, asof: datetime, sym: str, kind: str):
    """{(expiry, strike): contract} for one underlying and option type."""
    out = {}
    for oid, c in contracts.items():
        if c.get("underlying", "SPY") != sym or c.get("type") != kind:
            continue
        if not _fresh(c, asof):
            continue
        out[(c["expiry"], float(c["strike"]))] = dict(c, option_id=oid)
    return out


def _held_ids(state: dict) -> set:
    return {leg["option_id"] for p in state["positions"] if p["status"] == "open"
            for leg in p["legs"]}


def _pick(name: str, cfg: dict, quotes: dict, contracts: dict, unders: dict,
          state: dict, on: date, asof: datetime, events: list):
    fn = {"credit_spread": _pick_credit_spread,
          "long_option": _pick_long_option}[cfg["kind"]]
    return fn(name, cfg, quotes, contracts, unders, state, on, asof, events)


def _pick_credit_spread(name, cfg, quotes, contracts, unders, state, on, asof, events):
    held, best = _held_ids(state), None
    for sym in cfg["underlyings"]:
        if sym in BANNED_UNDERLYINGS:
            continue
        spot = unders.get(sym, {}).get("last")
        if spot is None:
            continue
        for kind, side_sign in (("put", -1), ("call", 1)):
            if kind not in cfg["sides"]:
                continue
            chain = _chain(contracts, asof, sym, kind)
            for (expiry, strike), c in chain.items():
                dte = _dte(expiry, on)
                if not (cfg["dte_band"][0] <= dte <= cfg["dte_band"][1]):
                    continue
                d = c.get("delta")
                if d is None or not (cfg["delta_band"][0] <= abs(float(d)) <= cfg["delta_band"][1]):
                    continue
                long_strike = strike + side_sign * cfg["width"]
                lc = chain.get((expiry, long_strike))
                if not lc or c["option_id"] in held or lc["option_id"] in held:
                    continue
                if int(c.get("oi", 0)) < cfg["min_oi"] or int(lc.get("oi", 0)) < cfg["min_oi"]:
                    continue
                net_mid = _round2(-_mid(c) + _mid(lc))          # negative = credit
                legspread = _round2(_spread(c) + _spread(lc))
                paid = _round2(net_mid + SLIP_FRAC * legspread)
                credit = -paid
                if credit < cfg["min_credit_frac"] * cfg["width"]:
                    continue
                if legspread > cfg["max_legspread_frac"] * credit:
                    continue
                score = (abs(abs(float(d)) - cfg["target_delta"]), -credit, strike)
                if best is None or score < best[0]:
                    best = (score, dict(
                        sleeve=name, tag=cfg["tag"], underlying=sym,
                        structure=f"{kind}_credit_spread", width=cfg["width"],
                        qty=cfg["qty"], net_mid=net_mid, legspread=legspread,
                        paid_open=paid, delta=float(d), iv=float(c.get("iv", 0)),
                        spot=float(spot), dte=dte,
                        max_loss=_max_loss(False, paid, cfg["qty"], cfg["width"]),
                        desc=f'{sym} {expiry} -{_strike(strike)}{kind[0].upper()}/'
                             f'+{_strike(long_strike)}{kind[0].upper()} {dte}dte '
                             f'{abs(float(d)):.2f}d',
                        legs=[
                            {"option_id": c["option_id"], "strike": strike,
                             "expiry": expiry, "type": kind, "side": "short", "ratio": 1},
                            {"option_id": lc["option_id"], "strike": long_strike,
                             "expiry": expiry, "type": kind, "side": "long", "ratio": 1},
                        ]))
    if best is None:
        events.append(f"{name}: no entry (no candidate passed delta/DTE/credit/OI/spread gates)")
        return None
    return best[1]


def _pick_long_option(name, cfg, quotes, contracts, unders, state, on, asof, events):
    held, best = _held_ids(state), None
    for sym in cfg["underlyings"]:
        if sym in BANNED_UNDERLYINGS:
            continue
        u = unders.get(sym, {})
        spot, mom = u.get("last"), u.get("momentum")
        if spot is None or mom is None:
            continue
        kind = "call" if float(mom) >= 0 else "put"
        if kind not in cfg["sides"]:
            continue
        for (expiry, strike), c in _chain(contracts, asof, sym, kind).items():
            dte = _dte(expiry, on)
            if not (cfg["dte_band"][0] <= dte <= cfg["dte_band"][1]):
                continue
            d = c.get("delta")
            if d is None or not (cfg["delta_band"][0] <= abs(float(d)) <= cfg["delta_band"][1]):
                continue
            if c["option_id"] in held or int(c.get("oi", 0)) < cfg["min_oi"]:
                continue
            net_mid = _round2(_mid(c))                      # positive = debit
            legspread = _round2(_spread(c))
            paid = _round2(net_mid + SLIP_FRAC * legspread)
            if paid <= 0:
                continue
            qty = max(1, int(cfg["ticket_usd"] // (paid * 100)))
            cost = paid * 100 * qty
            if cost > cfg["ticket_usd"] * 1.5 or cost < cfg["ticket_usd"] * 0.25:
                continue
            if legspread > cfg["max_legspread_frac"] * paid:
                continue
            # earnings inside the contract's life is the highest-variance setup
            # available (and the worst-expectancy one in the literature), so it
            # sorts first when the sleeve asks for it.
            ed = u.get("earnings_in_days")
            hot = 0 if (cfg.get("earnings_boost") and ed is not None
                        and 0 <= int(ed) <= dte) else 1
            score = (hot, abs(abs(float(d)) - cfg["target_delta"]),
                     -abs(float(mom)), strike)
            if best is None or score < best[0]:
                best = (score, dict(
                    sleeve=name, tag=cfg["tag"], underlying=sym,
                    structure=f"long_{kind}", width=0.0, qty=qty,
                    net_mid=net_mid, legspread=legspread, paid_open=paid,
                    delta=float(d), iv=float(c.get("iv", 0)), spot=float(spot), dte=dte,
                    max_loss=_max_loss(True, paid, qty, 0.0),
                    desc=f'{sym} {expiry} +{_strike(strike)}{kind[0].upper()} {dte}dte '
                         f'{abs(float(d)):.2f}d mom {float(mom):+.2%}'
                         + ('' if hot else ' [earnings]'),
                    legs=[{"option_id": c["option_id"], "strike": strike,
                           "expiry": expiry, "type": kind, "side": "long", "ratio": 1}]))
    if best is None:
        events.append(f"{name}: no entry (no candidate passed delta/DTE/ticket/OI gates)")
        return None
    return best[1]


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def _report(state: dict, row: dict, events: list, incidents: list, on: date) -> dict:
    start = date.fromisoformat(state["started"])
    closed = [p for p in state["positions"] if p["status"] == "closed"]
    wins = [p for p in closed if p["realized_pnl"] > 0]
    return {
        "date": row["date"], "day": (on - start).days + 1,
        "equity": state["equity"], "bankroll": state["bankroll_usd"],
        "pnl_total": _round2(state["equity"] - state["bankroll_usd"]),
        "pnl_realized": _round2(sum(p["realized_pnl"] for p in closed)),
        "risk_open": row["risk"], "cash": row["cash"],
        "closed_n": len(closed),
        "win_rate": _round2(100.0 * len(wins) / len(closed)) if closed else None,
        "open": [{"id": p["id"], "sleeve": p["sleeve"], "desc": _desc(p),
                  "dte": p["dte"], "entry": p["paid_open"], "mark": p.get("mark"),
                  "max_loss": p["max_loss"],
                  "unrl": _round2((p.get("mark", p["paid_open"]) - p["paid_open"])
                                  * 100 * p["qty"] - p["fees_open"])}
                 for p in state["positions"] if p["status"] == "open"],
        "events": events, "incidents": incidents,
        "halted": bool(state.get("halted")),
        "ref_sym": row.get("ref_sym"), "ref_px": row.get("ref_px"),
    }


def _desc(p: dict) -> str:
    legs = sorted(p["legs"], key=lambda l: float(l["strike"]))
    body = "/".join(f'{"+" if l["side"] == "long" else "-"}{_strike(l["strike"])}'
                    f'{l["type"][0].upper()}' for l in legs)
    return f'{p["underlying"]} {body} {_expiry_of(p)[5:]}'


def render_daily(r: dict) -> str:
    L = [f'quantfirm options paper desk — day {r["day"]} ({r["date"]})  [HIGH-RISK MANDATE]',
         "=" * 66,
         f'equity        ${r["equity"]:.2f}  ({r["pnl_total"]:+.2f} vs ${r["bankroll"]:.0f} start)',
         f'realized P&L  ${r["pnl_realized"]:+.2f}   closed {r["closed_n"]}'
         + (f'   win rate {r["win_rate"]:.0f}%' if r["win_rate"] is not None else ""),
         f'capital at risk ${r["risk_open"]:.2f}   cash ${r["cash"]:.2f}']
    if r.get("ref_px"):
        L.append(f'{r["ref_sym"]:<13} {r["ref_px"]:.2f}')
    if r["halted"]:
        L.append("STATUS        HALTED — drawdown ladder tripped, no new entries")
    L += ["", "open positions:" if r["open"] else "open positions: none"]
    for p in r["open"]:
        mark = "stale" if p["mark"] is None else f'{p["mark"]:+.2f}'
        L.append(f'  {p["id"]:<22} {p["sleeve"]:<8} {p["desc"]:<28} dte {p["dte"]:>2}  '
                 f'entry {p["entry"]:+.2f} -> {mark}  risk ${p["max_loss"]:>6.0f}  '
                 f'unrl ${p["unrl"]:+.2f}')
    L += ["", "today:"]
    for e in r["events"] or ["(no actions)"]:
        L.append(f"  - {e}")
    for i in r["incidents"]:
        L.append(f"  ! {i}")
    L += ["", "paper simulation under an explicit maximum-risk mandate — fills modeled at "
          "60% of combined half-spread plus $0.04/contract/side. Not real orders, "
          "not investment advice."]
    return "\n".join(L)


def render_weekly(state: dict, today: str) -> str:
    on = date.fromisoformat(today)
    wk = on - timedelta(days=7)
    hist = state["history"]
    week = [h for h in hist if date.fromisoformat(h["date"]) > wk]
    closed = [p for p in state["positions"] if p["status"] == "closed"]
    cw = [p for p in closed if p.get("closed", "") > wk.isoformat()]
    start_eq = week[0]["equity"] if week else state["bankroll_usd"]
    wins = [p for p in cw if p["realized_pnl"] > 0]
    L = [f"quantfirm options paper desk — weekly report (week ending {today})",
         "=" * 66,
         f'equity ${state["equity"]:.2f} | week P&L ${state["equity"] - start_eq:+.2f} | '
         f'since start ${state["equity"] - state["bankroll_usd"]:+.2f} on ${state["bankroll_usd"]:.0f}',
         "", f"trades closed this week: {len(cw)}"
         + (f" ({len(wins)} winners, {100.0*len(wins)/len(cw):.0f}% hit rate)" if cw else "")]
    for p in cw:
        L.append(f'  {p["id"]:<22} {p["sleeve"]:<8} {_desc(p):<28} {p["exit_reason"]:<18} '
                 f'P&L ${p["realized_pnl"]:+8.2f}')
    by = {}
    for p in closed:
        by.setdefault(p["sleeve"], []).append(p["realized_pnl"])
    if by:
        L += ["", "per-sleeve realized P&L (cumulative):"]
        for s, v in sorted(by.items()):
            L.append(f"  {s:<10} {len(v):>3} trades   ${sum(v):+8.2f}")
    slip = sum(abs(p.get("entry_slippage", 0.0)) * 100 * p["qty"]
               for p in state["positions"])
    slip += sum(abs(p["exit_mid"] - p["exit_price"]) * 100 * p["qty"]
                for p in closed if p.get("exit_mid") is not None)
    fees = sum(p.get("fees_open", 0.0) + p.get("fees_close", 0.0) for p in state["positions"])
    L += ["", f"cost meter (cumulative): modeled entry slippage ${slip:.2f}, fees ${fees:.2f} "
          f'— {100 * (slip + fees) / state["bankroll_usd"]:.1f}% of bankroll',
          f'incidents to date: {len(state["incidents"])}', "", "equity curve:"]
    for h in hist:
        L.append(f'  {h["date"]}  ${h["equity"]:>7.2f}  open {h["open"]}  '
                 f'risk ${h.get("risk", 0):>6.2f}')
    L += ["", "paper simulation under an explicit maximum-risk mandate — see "
          "docs/OPTIONS_PAPER_V2.md for the pre-registered spec."]
    return "\n".join(L)


def new_state(started: str, ends: str) -> dict:
    return {"desk": "options_paper", "version": 2, "mandate": "HIGH_RISK",
            "started": started, "ends": ends, "bankroll_usd": BANKROLL,
            "cash": BANKROLL, "equity": BANKROLL, "halted": False, "seq": 0,
            "positions": [], "history": [], "incidents": []}
