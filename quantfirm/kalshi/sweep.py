"""Bank profit sweep — unused on the live desk.

Owner handles Kalshi → Bank of America ACH. Heal, the supervisor, and
PaperEngine.tick must not call run_sweep. This module stays for a
manual CLI report if someone asks; try_create defaults to False.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from .universe import BANKROLL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SWEEP_PATH = os.path.join(REPO, "state", "kalshi_sweep.json")
PAPER_STATE_PATH = os.path.join(REPO, "state", "kalshi_paper_state.json")

LEAVE = Decimal(str(int(BANKROLL)))       # $250 stays on the desk
PEEL_UNIT = Decimal("50")                 # every $50 of profit
THRESHOLD = LEAVE + PEEL_UNIT             # fire at $300
LEAVE_CENTS = int(LEAVE * 100)
PEEL_UNIT_CENTS = int(PEEL_UNIT * 100)
THRESHOLD_CENTS = int(THRESHOLD * 100)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def peel_amount(cash: Decimal) -> Decimal:
    """Largest $50 multiple that still leaves >= $250. Zero below $300."""
    cash = Decimal(str(cash))
    if cash < THRESHOLD:
        return Decimal("0")
    units = int(((cash - LEAVE) / PEEL_UNIT).to_integral_value(rounding=ROUND_DOWN))
    if units < 1:
        return Decimal("0")
    amt = PEEL_UNIT * units
    if cash - amt < LEAVE:
        return Decimal("0")
    return amt


def load_state(path: str = SWEEP_PATH) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "threshold": float(THRESHOLD),
        "peel_unit": float(PEEL_UNIT),
        "leave": float(LEAVE),
        "destination": "linked Bank of America ACH",
        "due": False,
        "events": [],
        "seen_ids": [],
    }


def save_state(st: dict, path: str = SWEEP_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, path)


def public_view(path: str = SWEEP_PATH) -> dict:
    """Heartbeat snippet. No bank account numbers."""
    st = load_state(path)
    return {
        "threshold": float(THRESHOLD),
        "peel_unit": float(PEEL_UNIT),
        "leave": float(LEAVE),
        "destination": "linked Bank of America ACH",
        "due": bool(st.get("due")),
        "kalshi_cash": st.get("kalshi_cash"),
        "note": st.get("note") or "hold",
        "last_peel_id": st.get("last_peel_id"),
        "last_peel_ts": st.get("last_peel_ts"),
        "create_api": st.get("create_api") or "unknown",
    }


def plan(cash: Decimal, *, pending: bool = False) -> dict:
    """Pure policy. No I/O.

    When available cash >= $300, withdraw the largest $50 multiple that
    still leaves >= $250. A pending ACH blocks another POST.
    """
    cash = Decimal(str(cash))
    if pending:
        return {"action": "wait_pending", "amount": Decimal("0")}
    amt = peel_amount(cash)
    if amt >= PEEL_UNIT:
        return {"action": "withdraw", "amount": amt}
    return {"action": "hold", "amount": Decimal("0")}


def _withdrawal_usd(w: dict) -> Decimal:
    if w.get("amount_dollars") not in (None, ""):
        return Decimal(str(w["amount_dollars"]))
    try:
        cents = int(w.get("amount_cents") or w.get("amount") or 0)
    except (TypeError, ValueError):
        return Decimal("0")
    if cents >= 1000:  # cents, not dollars
        return (Decimal(cents) / 100).quantize(Decimal("0.01"))
    return Decimal(cents)


def _peel_withdrawal(w: dict) -> bool:
    usd = _withdrawal_usd(w)
    if usd < PEEL_UNIT:
        return False
    return (usd % PEEL_UNIT) == 0


def _created_ts(w: dict) -> int:
    try:
        return int(w.get("created_ts") or 0)
    except (TypeError, ValueError):
        return 0


def apply_ledger_debits(state: dict, path: str = SWEEP_PATH) -> float:
    """Subtract applied peels from the live paper ledger once."""
    st = load_state(path)
    total = 0.0
    changed = False
    for ev in st.get("events") or []:
        if ev.get("booked") or ev.get("status") != "applied":
            continue
        amt = float(ev.get("amount_usd") or PEEL_UNIT)
        live = float((state.get("cash") or {}).get("live") or 0.0)
        state.setdefault("cash", {})["live"] = live - amt
        ev["booked"] = True
        total += amt
        changed = True
    if changed:
        save_state(st, path)
    return total


def apply_ledger_debits_file(state_path: str = PAPER_STATE_PATH,
                             sweep_path: str = SWEEP_PATH) -> float:
    if not os.path.exists(state_path):
        return 0.0
    try:
        with open(state_path) as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0.0
    total = apply_ledger_debits(d, sweep_path)
    if total:
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, state_path)
    return total


def run_sweep(client=None, *, path: str = SWEEP_PATH,
              paper_state_path: str = PAPER_STATE_PATH,
              try_create: bool | None = None, now: int | None = None) -> dict:
    """Optional report. Owner handles ACH; the live desk does not call this.

    ``try_create`` defaults to False. POST is never retried
    (``create_withdrawal`` uses tries=1).
    """
    from .client import KalshiApiError, KalshiClient

    now = now if now is not None else _now_unix()
    if try_create is None:
        try_create = False

    st = load_state(path)
    st["threshold"] = float(THRESHOLD)
    st["peel_unit"] = float(PEEL_UNIT)
    st["leave"] = float(LEAVE)
    st["destination"] = "linked Bank of America ACH"
    st.setdefault("events", [])
    st.setdefault("seen_ids", [])

    if client is None:
        client = KalshiClient("prod")
    if not getattr(client, "can_trade", True):
        st["note"] = "no prod creds"
        st["updated"] = _now()
        save_state(st, path)
        return public_view(path)

    try:
        cash = Decimal(str(client.balance()))
    except Exception as e:
        st["note"] = f"balance error: {type(e).__name__}"
        st["updated"] = _now()
        save_state(st, path)
        return public_view(path)

    st["kalshi_cash"] = float(cash)

    withdrawals: list[dict] = []
    try:
        withdrawals = list((client.withdrawals(limit=50) or {}).get("withdrawals") or [])
    except Exception:
        withdrawals = []

    due_since = int(st.get("due_since") or 0)
    pending = False
    matched = None
    for w in withdrawals:
        wid = str(w.get("id") or "")
        if not _peel_withdrawal(w):
            continue
        created = _created_ts(w)
        # Ignore historical $50-multiple ACH until this cycle is armed.
        if not due_since:
            continue
        if created and created + 5 < due_since:
            continue
        status = str(w.get("status") or "")
        usd = float(_withdrawal_usd(w))
        if status == "pending":
            pending = True
        if wid and wid not in st["seen_ids"]:
            matched = w
            st["seen_ids"].append(wid)
            st["events"].append({
                "id": wid,
                "status": status,
                "amount_usd": usd,
                "type": w.get("type"),
                "ts": _now(),
                "booked": False,
            })
        elif status == "applied":
            for ev in st["events"]:
                if ev.get("id") == wid:
                    ev["status"] = "applied"
            matched = matched or w
        if status == "pending" and wid:
            st["pending_id"] = wid

    if matched and str(matched.get("status")) in ("pending", "applied"):
        usd = float(_withdrawal_usd(matched))
        st["due"] = False
        st["create_blocked"] = False
        st["last_peel_id"] = matched.get("id")
        st["last_peel_ts"] = _now()
        st["pending_id"] = matched.get("id") if matched.get("status") == "pending" else None
        st["note"] = (
            f"peeled ${usd:.0f} to linked BofA ({matched.get('status')}); "
            f"continue at ${cash}"
        )
        if matched.get("status") == "applied":
            apply_ledger_debits_file(state_path=paper_state_path, sweep_path=path)
        st["updated"] = _now()
        save_state(st, path)
        view = public_view(path)
        view["note"] = st["note"]
        return view

    pending = pending or bool(st.get("pending_id"))
    decision = plan(cash, pending=pending)
    amt = decision["amount"]

    if decision["action"] == "wait_pending":
        st["due"] = True
        st["note"] = f"SWEEP pending ACH; Kalshi cash ${cash}"
    elif decision["action"] == "withdraw":
        st["due"] = True
        if not st.get("due_since"):
            st["due_since"] = now
        st["note"] = (
            f"SWEEP DUE: Kalshi cash ${cash} >= ${THRESHOLD}; "
            f"peel ${amt} to linked BofA, continue ~${LEAVE}"
        )
        if (try_create and not st.get("pending_id")
                and not st.get("create_blocked")):
            try:
                cents = int(amt * 100)
                resp = client.create_withdrawal(cents)
                wd = resp.get("withdrawal") or resp
                st["create_api"] = "ok"
                st["create_blocked"] = False
                st["pending_id"] = wd.get("id")
                st["note"] = f"posted ${amt} ACH id={wd.get('id')}"
                if wd.get("id"):
                    st["seen_ids"].append(str(wd["id"]))
                    st["events"].append({
                        "id": wd.get("id"),
                        "status": wd.get("status") or "pending",
                        "amount_usd": float(amt),
                        "type": wd.get("type") or "ach",
                        "ts": _now(),
                        "booked": False,
                    })
            except KalshiApiError as e:
                st["create_api"] = f"http_{e.status}"
                if e.status == 404:
                    # Harmless to retry next heal; nothing moved.
                    st["note"] = (
                        f"SWEEP DUE: Kalshi cash ${cash}. Trade API cannot "
                        f"create ACH (POST /portfolio/withdrawals 404). "
                        f"Kalshi app → Transfers → Withdraw → Bank Transfer "
                        f"${amt} to Bank of America. Desk keeps running."
                    )
                else:
                    # Timeout or other error: POST may have been accepted.
                    st["create_blocked"] = True
                    st["note"] = (
                        f"SWEEP DUE: Kalshi cash ${cash}; create failed "
                        f"HTTP {e.status}. Do not retry POST. Withdraw "
                        f"${amt} to BofA in the app if GET is empty."
                    )
            except Exception as e:
                st["create_api"] = type(e).__name__
                st["create_blocked"] = True
                st["note"] = (
                    f"SWEEP DUE: Kalshi cash ${cash}; create error "
                    f"{type(e).__name__}. Do not retry POST. Withdraw "
                    f"${amt} to BofA in the app if GET is empty."
                )
    else:
        if cash < THRESHOLD:
            st["due"] = False
            st["due_since"] = None
            st["pending_id"] = None
            st["create_blocked"] = False
        st["note"] = f"hold (Kalshi cash ${cash}; peel ${PEEL_UNIT} at ${THRESHOLD})"

    st["updated"] = _now()
    save_state(st, path)
    view = public_view(path)
    view["note"] = st["note"]
    view["due"] = bool(st.get("due"))
    return view


def checkin_line(view: dict | None = None) -> str:
    v = view or public_view()
    if v.get("due"):
        return "BANK SWEEP DUE " + str(v.get("note") or "")
    return "bank_sweep=" + str(v.get("note") or "hold")
