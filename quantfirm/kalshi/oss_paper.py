"""Paper clone of the OSS prediction-market loop, sized to the $257 book.

This is the improved port of agiprolabs FLB + mjunaidca paper-first, not
a live bot. Modifications vs the public skills/bots:

* no live order path (``--live`` is a hard refuse)
* hold-to-venue-``result`` only (never a self-computed CLI)
* skip 1¢ leftovers and zero-volume advertised size (phantom wings)
* one-lot taker NO on 5–20¢ YES; maker candidates are logged, not filled
* forecast YES takes are logged and sat (12-day tape already −$12)
* hourly crypto ranges are sat (complete-hour sum(ask) $4–14)
* pre-declared kill after 20 settled fades

The $257 stays in the Kalshi account. This file marks a counterfactual
book against that notional. It does not reserve the incentive cash and
it does not send an order.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .fair import taker_fee
from .ladder import exclusive_dutch, legs_from_markets

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(REPO, "state", "kalshi_oss_paper.json")

BANKROLL = 257.0
FLB_LO, FLB_HI = 0.05, 0.20
MAX_BET_FRAC = 0.015
MAX_EXPOSURE_FRAC = 0.20
MAX_POSITIONS = 8
MAX_PER_EVENT = 3
COUNT = 1
MIN_VOLUME = 10.0
KILL_N = 20
WEATHER_SERIES = (
    "KXHIGHNY", "KXHIGHCHI", "KXHIGHTBOS", "KXHIGHHOU",
    "KXHIGHLAX", "KXHIGHMIA", "KXHIGHDEN",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None = None) -> str:
    return (ts or _now()).isoformat()


def _f(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass
class Intent:
    ticker: str
    event: str
    side: str
    px: float
    count: int
    fee: float
    yes_ask: float
    yes_bid: float
    volume: float
    reason: str
    family: str = "flb_taker"


@dataclass
class Position:
    ticker: str
    event: str
    side: str
    px: float
    count: int
    fee: float
    yes_ask: float
    yes_bid: float
    volume: float
    family: str
    opened: str
    cost: float


def empty_state(capital: float = BANKROLL) -> dict:
    return {
        "started": _iso(),
        "capital": capital,
        "cash": capital,
        "ticks": 0,
        "live": False,
        "positions": [],
        "settled": [],
        "skipped": [],
        "maker_watch": [],
        "forecast_watch": [],
        "history": [],
        "verdict": "INSUFFICIENT",
        "verdict_reason": "no settled fades yet",
        "killed": False,
        "kill_reason": None,
    }


def load_state(path: str = STATE_PATH, capital: float = BANKROLL) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            st = json.load(f)
        st.setdefault("capital", capital)
        return st
    return empty_state(capital)


def save_state(st: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def phantom_wing(yes_ask, yes_ask_size, volume) -> bool:
    """Empty-room 1¢/size-70 wings on hourly crypto, and dead leftovers."""
    px = _f(yes_ask)
    vol = _f(volume) or 0.0
    sz = _f(yes_ask_size) or 0.0
    if px is None:
        return True
    if px < FLB_LO:
        return True
    if vol < MIN_VOLUME:
        return True
    if sz >= 50 and vol <= 0:
        return True
    return False


def flb_taker_intent(leg, event: str, count: int = COUNT) -> Intent | None:
    """Buy NO as a taker on a 5–20¢ YES. None if the quote is not executable."""
    ask, bid = _f(leg.yes_ask), _f(leg.yes_bid)
    if ask is None or bid is None:
        return None
    if not (FLB_LO <= ask <= FLB_HI):
        return None
    if phantom_wing(ask, getattr(leg, "yes_ask_size", None), getattr(leg, "volume", None)):
        return None
    no_px = 1.0 - bid
    if not (0 < no_px < 1):
        return None
    if (getattr(leg, "yes_bid_size", None) or 0) < count:
        return None
    fee = taker_fee(count, no_px)
    return Intent(
        ticker=leg.ticker, event=event, side="no", px=round(no_px, 4),
        count=count, fee=fee, yes_ask=ask, yes_bid=bid,
        volume=float(getattr(leg, "volume", 0) or 0),
        reason="flb_taker_5_20", family="flb_taker",
    )


def dutch_intent(legs, event: str) -> dict | None:
    d = exclusive_dutch(legs, count=1)
    if not d.get("tradeable"):
        return None
    return {"event": event, "dutch": d}


def exposure(positions: list) -> float:
    return sum(float(p.get("cost") or 0) for p in positions)


def select_intents(intents: list[Intent], st: dict,
                   capital: float) -> tuple[list[Intent], list[dict]]:
    """Apply size / correlation / kill caps. Returns (take, skip)."""
    if st.get("killed"):
        return [], [{"ticker": i.ticker, "reason": "sleeve_killed"} for i in intents]
    open_tk = {p["ticker"] for p in st.get("positions") or []}
    per_event = {}
    for p in st.get("positions") or []:
        per_event[p["event"]] = per_event.get(p["event"], 0) + 1
    cash = float(st.get("cash") or 0)
    exp = exposure(st.get("positions") or [])
    take, skip = [], []
    max_bet = capital * MAX_BET_FRAC
    max_exp = capital * MAX_EXPOSURE_FRAC
    n_open = len(st.get("positions") or [])
    for i in intents:
        if i.ticker in open_tk:
            skip.append({"ticker": i.ticker, "reason": "already_open"})
            continue
        if n_open + len(take) >= MAX_POSITIONS:
            skip.append({"ticker": i.ticker, "reason": "max_positions"})
            continue
        if per_event.get(i.event, 0) >= MAX_PER_EVENT:
            skip.append({"ticker": i.ticker, "reason": "max_per_event"})
            continue
        cost = i.px * i.count + i.fee
        if cost > max_bet + 1e-9:
            skip.append({"ticker": i.ticker, "reason": "max_bet_frac"})
            continue
        if cost > cash + 1e-9:
            skip.append({"ticker": i.ticker, "reason": "no_cash"})
            continue
        if exp + cost > max_exp + 1e-9:
            skip.append({"ticker": i.ticker, "reason": "max_exposure"})
            continue
        take.append(i)
        open_tk.add(i.ticker)
        per_event[i.event] = per_event.get(i.event, 0) + 1
        cash -= cost
        exp += cost
    return take, skip


def open_positions(st: dict, intents: list[Intent], opened: str | None = None) -> list[dict]:
    opened = opened or _iso()
    out = []
    for i in intents:
        cost = round(i.px * i.count + i.fee, 4)
        st["cash"] = round(float(st["cash"]) - cost, 4)
        pos = asdict(Position(
            ticker=i.ticker, event=i.event, side=i.side, px=i.px,
            count=i.count, fee=i.fee, yes_ask=i.yes_ask, yes_bid=i.yes_bid,
            volume=i.volume, family=i.family, opened=opened, cost=cost,
        ))
        st["positions"].append(pos)
        out.append(pos)
    return out


def settle_position(pos: dict, result: str) -> dict:
    """Settle one paper NO (or YES) against the venue result field."""
    res = str(result or "").lower()
    if res not in ("yes", "no"):
        raise ValueError(f"venue result required, got {result!r}")
    count = int(pos["count"])
    px = float(pos["px"])
    fee = float(pos["fee"])
    side = pos["side"]
    if side == "no":
        won = res == "no"
        payout = count * (1.0 if won else 0.0)
    elif side == "yes":
        won = res == "yes"
        payout = count * (1.0 if won else 0.0)
    else:
        raise ValueError(f"unknown side {side}")
    pnl = round(payout - count * px - fee, 4)
    return {
        **pos,
        "result": res,
        "won": won,
        "payout": payout,
        "pnl": pnl,
        "settled": _iso(),
        "longshot_hit": bool(side == "no" and res == "yes"),
    }


def apply_settlements(st: dict, result_by_ticker: dict[str, str]) -> list[dict]:
    kept, done = [], []
    for pos in st.get("positions") or []:
        res = result_by_ticker.get(pos["ticker"])
        if res not in ("yes", "no"):
            kept.append(pos)
            continue
        rec = settle_position(pos, res)
        st["cash"] = round(float(st["cash"]) + rec["payout"], 4)
        done.append(rec)
    st["positions"] = kept
    st["settled"] = (st.get("settled") or []) + done
    return done


def flb_stats(settled: list) -> dict:
    fades = [t for t in settled if t.get("family") == "flb_taker"]
    if not fades:
        return {"n": 0, "pnl": 0.0, "hits": 0, "hit_rate": None, "mean_ask": None}
    hits = sum(1 for t in fades if t.get("longshot_hit"))
    asks = [_f(t.get("yes_ask")) for t in fades]
    asks = [a for a in asks if a is not None]
    return {
        "n": len(fades),
        "pnl": round(sum(float(t.get("pnl") or 0) for t in fades), 4),
        "hits": hits,
        "hit_rate": round(hits / len(fades), 4),
        "mean_ask": round(sum(asks) / len(asks), 4) if asks else None,
    }


def verdict(st: dict) -> tuple[str, str]:
    """Pre-declared kills. Written before the forward tape arrives."""
    if st.get("killed") and st.get("kill_reason"):
        return "NO", st["kill_reason"]
    stats = flb_stats(st.get("settled") or [])
    cash = float(st.get("cash") or 0)
    capital = float(st.get("capital") or BANKROLL)
    if cash < 0.5 * capital:
        return "NO", f"cash ${cash:.2f} < 50% of ${capital:.0f} — ruin brake"
    if stats["n"] < KILL_N:
        return "INSUFFICIENT", (
            f"{stats['n']} settled fades, need {KILL_N} before a go/no-go "
            f"(hist tape was taker −$1.21 / 66 at a 10.6% hit rate)"
        )
    # Kill 1: the cheap YES is not overpriced vs its own ask.
    if stats["hit_rate"] is not None and stats["mean_ask"] is not None:
        if stats["hit_rate"] + 1e-9 >= stats["mean_ask"]:
            return "NO", (
                f"hit_rate {stats['hit_rate']:.1%} >= mean ask "
                f"{stats['mean_ask']:.1%} — longshot is not overpriced"
            )
    # Kill 2: the sleeve lost money at one-lot size.
    if stats["pnl"] <= 0:
        return "NO", f"n={stats['n']} pnl=${stats['pnl']:.2f} — no edge after fees"
    return "PAPER_OK", (
        f"n={stats['n']} pnl=${stats['pnl']:.2f} hit={stats['hit_rate']:.1%} "
        f"< mean ask {stats['mean_ask']:.1%} — still paper, not a live raise"
    )


def maybe_kill(st: dict) -> None:
    code, why = verdict(st)
    st["verdict"] = code
    st["verdict_reason"] = why
    if code == "NO":
        st["killed"] = True
        st["kill_reason"] = why


def intents_from_event(event: str, markets: list[dict]) -> tuple[list[Intent], dict]:
    legs = legs_from_markets(markets)
    flb, watch = [], []
    for lg in legs:
        intent = flb_taker_intent(lg, event)
        if intent:
            flb.append(intent)
        elif _f(lg.yes_ask) is not None and FLB_LO <= _f(lg.yes_ask) <= FLB_HI:
            watch.append({
                "ticker": lg.ticker, "event": event,
                "yes_ask": lg.yes_ask, "volume": lg.volume,
                "reason": "quoted_but_not_executable",
            })
    dutch = dutch_intent(legs, event)
    return flb, {"maker_watch": watch, "dutch": dutch,
                 "n_legs": len(legs),
                 "sum_ask": exclusive_dutch(legs).get("sum_ask")}


def refuse_live(live: bool) -> None:
    if live:
        raise SystemExit(
            "refusing --live on kalshi_oss_paper "
            "(paper sleeve cannot send Kalshi orders; "
            "see research/kalshi_oss_skills.md)"
        )
