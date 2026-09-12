"""Replay-only cash-out: sell if the entry signal dies.

NOT wired into the live paper engine. Hold-to-settle stays the live
book. On 2026-09-12 live fills the 60¢ rule is behind holding
(research/kalshi_cashout.md) — do not bounce the agent for this.

Signal (same as desk_book entry, ignoring the 3-minute wait):

  * held YES is dead when yes_ask < 0.60 (would not buy YES now)
  * held NO is dead when 1 - yes_bid < 0.60
  * crypto: if a Poly quote exists and Poly's ≥55¢ favorite is missing
    or the other side, the confirm is dead

Exit price is the bid of the held side (YES bid, or NO bid = 1 - yes_ask).
A 15s min-hold avoids selling the same second we bought into the spread.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from .fair import taker_fee
from .poly import PolyQuote, poly_favorite
from .universe import CRYPTO_LIVE

PRICE_MIN = 0.60
POLY_PRICE_MIN = 0.55
MIN_HOLD_S = 15


def held_entry_px(side: str, yes_bid: float | None,
                  yes_ask: float | None) -> float | None:
    """Price we would pay to enter this side right now."""
    if side == "yes":
        return yes_ask if yes_ask is not None else yes_bid
    if yes_bid is not None:
        return 1.0 - yes_bid
    return None


def held_exit_px(side: str, yes_bid: float | None,
                  yes_ask: float | None) -> float | None:
    """Bid of the held side — what an IOC sell would hit."""
    if side == "yes":
        return yes_bid
    if yes_ask is not None:
        return 1.0 - yes_ask
    return None


def cash_out_reason(side: str, yes_bid: float | None, yes_ask: float | None,
                    *, metal: str | None = None,
                    poly_yes_bid: float | None = None,
                    poly_yes_ask: float | None = None,
                    poly_down_ask: float | None = None,
                    price_min: float = PRICE_MIN,
                    use_poly: bool = True) -> str | None:
    """Why the held side is dead, or None to keep holding."""
    px = held_entry_px(side, yes_bid, yes_ask)
    if px is None:
        return None
    if px < price_min:
        return "kalshi_dead"
    if not use_poly or metal not in CRYPTO_LIVE:
        return None
    if poly_yes_bid is None and poly_yes_ask is None:
        return None
    q = PolyQuote(asset=str(metal), slug="", up_bid=poly_yes_bid,
                   up_ask=poly_yes_ask, down_bid=None, down_ask=poly_down_ask,
                   ts=0.0)
    fav = poly_favorite(q, price_min=POLY_PRICE_MIN)
    if fav is None or fav != side:
        return "poly_disagree"
    return None


def should_cash_out(side: str, yes_bid: float | None, yes_ask: float | None,
                     *, metal: str | None = None,
                     poly_yes_bid: float | None = None,
                     poly_yes_ask: float | None = None,
                     poly_down_ask: float | None = None,
                     price_min: float = PRICE_MIN,
                     use_poly: bool = True) -> bool:
    """True when we would no longer take this side."""
    return cash_out_reason(
        side, yes_bid, yes_ask, metal=metal, poly_yes_bid=poly_yes_bid,
        poly_yes_ask=poly_yes_ask, poly_down_ask=poly_down_ask,
        price_min=price_min, use_poly=use_poly) is not None


def exit_pnl(count: float, fill_price: float, exit_px: float,
              entry_fee: float | None = None) -> float:
    entry_fee = taker_fee(count, fill_price) if entry_fee is None else entry_fee
    return count * exit_px - taker_fee(count, exit_px) - count * fill_price - entry_fee


def _iso_to_ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def parse_loop_fills(log_text: str) -> list[dict]:
    """LIVE FILL + SETTLE live pairs from kalshi_paper_loop.log."""
    fills = {}
    fill_re = re.compile(
        r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\] LIVE FILL "
        r"(yes|no) ([0-9.]+) (\S+)")
    set_re = re.compile(
        r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\] SETTLE live "
        r"(\S+) (yes|no) pnl=([+-][0-9.]+)")
    for m in fill_re.finditer(log_text):
        fills[m.group(4)] = {
            "filled_at": m.group(1),
            "fill_ts": _iso_to_ts(m.group(1)),
            "side": m.group(2),
            "count": float(m.group(3)),
            "ticker": m.group(4),
        }
    for m in set_re.finditer(log_text):
        rec = fills.get(m.group(2))
        if rec is None:
            continue
        rec["settled_at"] = m.group(1)
        rec["result"] = m.group(3)
        rec["hold_pnl"] = float(m.group(4))
    metal = {"KXBTC": "btc", "KXETH": "eth", "KXGOLD": "gold",
             "KXSILVER": "silver", "KXCOPPER": "copper", "KXWTI": "wti",
             "KXNATGAS": "natgas"}
    out = []
    for rec in fills.values():
        tkr = rec["ticker"]
        rec["metal"] = next((v for k, v in metal.items() if tkr.startswith(k)), None)
        out.append(rec)
    return out


def _poly_from_dec(d: dict) -> tuple[float | None, float | None, float | None]:
    up = d.get("poly_up") or [None, None]
    dn = d.get("poly_down") or [None, None]
    up_bid = up[0] if isinstance(up, list) and len(up) > 0 else None
    up_ask = up[1] if isinstance(up, list) and len(up) > 1 else None
    dn_ask = dn[1] if isinstance(dn, list) and len(dn) > 1 else None
    return up_bid, up_ask, dn_ask


def infer_fill_price(fill: dict, decisions: list[dict]) -> float | None:
    """CSV fill_price, else the quote we would have paid near the fill."""
    if fill.get("fill_price") is not None:
        return fill["fill_price"]
    tkr = fill["ticker"]
    side = fill["side"]
    fill_ts = fill["fill_ts"]
    fallback = None
    for d in decisions:
        if d.get("ticker") != tkr:
            continue
        ts = float(d.get("ts") or 0)
        if ts < fill_ts - 2:
            continue
        if ts > fill_ts + 45:
            break
        px = held_entry_px(side, d.get("bid"), d.get("ask"))
        if px is None:
            continue
        if d.get("intent") == side:
            return round(px, 4)
        if fallback is None:
            fallback = px
    return None if fallback is None else round(fallback, 4)


def replay_one(fill: dict, decisions: list[dict], *,
               use_poly: bool = True, min_hold_s: float = MIN_HOLD_S,
               price_min: float = PRICE_MIN) -> dict:
    """First decision tick after min-hold where the signal is dead."""
    tkr = fill["ticker"]
    side = fill["side"]
    metal = fill.get("metal")
    fill_ts = fill["fill_ts"]
    hold = fill.get("hold_pnl")
    count = fill.get("count") or 0
    fill_px = infer_fill_price(fill, decisions)
    base = {
        "ticker": tkr, "metal": metal, "side": side,
        "filled_at": fill.get("filled_at"), "fill_price": fill_px,
        "count": count, "hold_pnl": hold, "use_poly": use_poly,
    }
    for d in decisions:
        if d.get("ticker") != tkr:
            continue
        ts = float(d.get("ts") or 0)
        if ts < fill_ts + min_hold_s:
            continue
        bid, ask = d.get("bid"), d.get("ask")
        pb, pa, pdown = _poly_from_dec(d)
        reason = cash_out_reason(side, bid, ask, metal=metal,
                                 poly_yes_bid=pb, poly_yes_ask=pa,
                                 poly_down_ask=pdown, use_poly=use_poly,
                                 price_min=price_min)
        if reason is None:
            continue
        px = held_exit_px(side, bid, ask)
        if px is None or px <= 0:
            continue
        px = round(px, 4)
        if fill_px is None:
            return {**base, "exited": True, "exit_ts": ts, "exit_px": px,
                    "tau_s": d.get("tau_s"), "reason": reason,
                    "exit_pnl": None, "delta": None}
        pnl = exit_pnl(count, fill_px, px) if count else None
        return {**base, "exited": True, "exit_ts": ts, "exit_px": px,
                "tau_s": d.get("tau_s"), "reason": reason,
                "hold_pnl": hold, "exit_pnl": None if pnl is None else round(pnl, 4),
                "delta": (None if pnl is None or hold is None else round(pnl - hold, 4))}
    return {**base, "exited": False, "exit_pnl": hold, "delta": 0.0}


def load_decisions(path: str) -> list[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def attach_fill_prices(fills: list[dict], csv_path: str) -> None:
    import csv as _csv
    if not os.path.exists(csv_path):
        return
    by_tkr = {}
    with open(csv_path) as f:
        for row in _csv.DictReader(f):
            if row.get("adapter") != "live":
                continue
            by_tkr[row.get("ticker")] = row
    for rec in fills:
        row = by_tkr.get(rec["ticker"])
        if not row:
            continue
        try:
            rec["fill_price"] = float(row["fill_price"])
            rec["count"] = float(row.get("count") or rec["count"])
            if row.get("pnl") not in (None, ""):
                rec["hold_pnl"] = float(row["pnl"])
        except (TypeError, ValueError):
            pass


def _score_rows(rows: list[dict]) -> dict:
    exited = [r for r in rows if r.get("exited")]
    hold = sum(r.get("hold_pnl") or 0 for r in rows)
    exit_sum = sum((r.get("exit_pnl") if r.get("exit_pnl") is not None
                    else r.get("hold_pnl") or 0) for r in rows)
    saved = [r for r in rows if r.get("exited")
             and (r.get("hold_pnl") or 0) < 0
             and (r.get("delta") or 0) > 0]
    cut = [r for r in rows if r.get("exited")
           and (r.get("hold_pnl") or 0) > 0
           and (r.get("delta") or 0) < 0]
    return {
        "n": len(rows),
        "n_exit": len(exited),
        "n_saved": len(saved),
        "n_cut": len(cut),
        "hold_pnl": round(hold, 2),
        "exit_pnl": round(exit_sum, 2),
        "delta": round(exit_sum - hold, 2),
        "ahead": bool(rows) and exit_sum > hold,
    }


def replay_snapshot(log_path: str, decisions_path: str, trades_path: str,
                    use_poly: bool = True, price_min: float = PRICE_MIN,
                    min_hold_s: float = MIN_HOLD_S,
                    include_rows: bool = True) -> dict:
    with open(log_path) as f:
        fills = parse_loop_fills(f.read())
    attach_fill_prices(fills, trades_path)
    fills = [r for r in fills if r.get("settled_at") and r.get("hold_pnl") is not None]
    fills.sort(key=lambda r: r.get("fill_ts") or 0)
    decisions = load_decisions(decisions_path)
    rows = [replay_one(r, decisions, use_poly=use_poly, min_hold_s=min_hold_s,
                       price_min=price_min) for r in fills]
    out = _score_rows(rows)
    crypto = _score_rows([r for r in rows if r.get("metal") in CRYPTO_LIVE])
    out.update({
        "use_poly": use_poly,
        "price_min": price_min,
        "min_hold_s": min_hold_s,
        "crypto": crypto,
    })
    if include_rows:
        out["rows"] = rows
    return out
