"""Ladder bookkeeping for mutually exclusive and nested Kalshi strikes.

This is not a view. Exclusive brackets on one event must sum to $1 of
YES payout and stay non-negative. Nested "above X" contracts must be
monotone in the threshold. Retail books, especially crypto hourly ranges
and CPI/payrolls ladders, often violate that on the quote.

Every number here is fee-aware and size-aware. A 1¢ ask on a zero-size
wing is not an arb. A missing bracket means the dutch book is incomplete
and must not trade.

Two executable books, both taker:

* Exclusive buy-all-YES: pay sum(ask_i) + fees, receive $1. Trade only
  when every bracket has an ask and min depth is at least one contract.
* Exclusive sell-all-YES: collect sum(bid_i) - fees, pay $1. Same
  completeness rule on bids.
* Nested inversion: buy the easier (lower) threshold, sell the harder
  (higher) threshold when bid(harder) > ask(easier) after fees. Locked
  edge is bid_inner - ask_outer - fees (the worst state).
"""

from __future__ import annotations

from dataclasses import dataclass

from .fair import taker_fee


@dataclass(frozen=True)
class LadderLeg:
    """One binary on a ladder. Prices are YES dollars. Sizes in contracts."""

    ticker: str
    floor: float | None = None  # inclusive lower bound when known
    cap: float | None = None    # inclusive upper bound; None = open tail
    yes_bid: float | None = None
    yes_ask: float | None = None
    yes_bid_size: float | None = None
    yes_ask_size: float | None = None
    volume: float | None = None
    last: float | None = None
    threshold: float | None = None  # nested "above X" strike
    strike_type: str = ""
    title: str = ""

    @property
    def mid(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2.0

    @property
    def quoted(self) -> bool:
        return self.yes_bid is not None or self.yes_ask is not None


def _pos(x: float | None) -> float:
    return float(x) if x is not None and x > 0 else 0.0


def exclusive_mid_sum(legs: list[LadderLeg]) -> dict:
    """Quoted-mid sum. Diagnostic only — not an executable book."""
    mids = [lg.mid for lg in legs if lg.mid is not None]
    n_missing = sum(1 for lg in legs if lg.mid is None)
    s = sum(mids) if mids else None
    return {
        "n_legs": len(legs),
        "n_quoted": len(mids),
        "n_missing_mid": n_missing,
        "mid_sum": round(s, 4) if s is not None else None,
        "mid_sum_gap": round(s - 1.0, 4) if s is not None else None,
    }


def exclusive_dutch(legs: list[LadderLeg], count: float | None = None) -> dict:
    """Fee-aware exclusive dutch at top-of-book.

    ``count`` defaults to the bottleneck top-of-book size (floored to a
    whole contract). Incomplete books (a missing ask or bid) are not
    traded — they return ``complete=False`` and edge None.
    """
    n = len(legs)
    asks = [lg.yes_ask for lg in legs]
    bids = [lg.yes_bid for lg in legs]
    ask_sz = [_pos(lg.yes_ask_size) for lg in legs]
    bid_sz = [_pos(lg.yes_bid_size) for lg in legs]
    ask_ok = all(a is not None and a > 0 for a in asks)
    bid_ok = all(b is not None and b > 0 for b in bids)
    ask_depth = min(ask_sz) if ask_ok and ask_sz else 0.0
    bid_depth = min(bid_sz) if bid_ok and bid_sz else 0.0

    buy = _dutch_buy_all_yes(legs, count, ask_ok, ask_depth)
    sell = _dutch_sell_all_yes(legs, count, bid_ok, bid_depth)
    out = {
        "n_legs": n,
        "n_with_ask": sum(1 for a in asks if a is not None),
        "n_with_bid": sum(1 for b in bids if b is not None),
        "sum_ask": round(sum(a or 0 for a in asks), 4) if ask_ok else None,
        "sum_bid": round(sum(b or 0 for b in bids), 4) if bid_ok else None,
        "ask_depth": round(ask_depth, 2),
        "bid_depth": round(bid_depth, 2),
        **{f"buy_{k}": v for k, v in buy.items()},
        **{f"sell_{k}": v for k, v in sell.items()},
    }
    out["tradeable"] = bool(
        (buy.get("complete") and (buy.get("edge") or 0) > 0)
        or (sell.get("complete") and (sell.get("edge") or 0) > 0)
    )
    return out


def _dutch_buy_all_yes(legs, count, complete, depth) -> dict:
    if not complete:
        return {"complete": False, "count": 0, "cost": None, "fees": None,
                "payout": None, "edge": None, "reason": "missing_ask"}
    depth_n = int(depth)
    if depth_n < 1:
        return {"complete": False, "count": 0, "cost": None, "fees": None,
                "payout": None, "edge": None, "reason": "no_ask_depth"}
    n = depth_n if count is None else int(min(count, depth_n))
    if n < 1:
        return {"complete": False, "count": 0, "cost": None, "fees": None,
                "payout": None, "edge": None, "reason": "count_lt_1"}
    cost = sum(n * float(lg.yes_ask) for lg in legs)
    fees = sum(taker_fee(n, float(lg.yes_ask)) for lg in legs)
    payout = float(n)  # exactly one YES pays $1
    edge = payout - cost - fees
    return {
        "complete": True,
        "count": n,
        "cost": round(cost, 4),
        "fees": round(fees, 4),
        "payout": round(payout, 4),
        "edge": round(edge, 4),
        "reason": "ok" if edge > 0 else "no_edge",
    }


def _dutch_sell_all_yes(legs, count, complete, depth) -> dict:
    if not complete:
        return {"complete": False, "count": 0, "proceeds": None,
                "fees": None, "payout": None, "edge": None,
                "reason": "missing_bid"}
    depth_n = int(depth)
    if depth_n < 1:
        return {"complete": False, "count": 0, "proceeds": None,
                "fees": None, "payout": None, "edge": None,
                "reason": "no_bid_depth"}
    n = depth_n if count is None else int(min(count, depth_n))
    if n < 1:
        return {"complete": False, "count": 0, "proceeds": None,
                "fees": None, "payout": None, "edge": None,
                "reason": "count_lt_1"}
    proceeds = sum(n * float(lg.yes_bid) for lg in legs)
    fees = sum(taker_fee(n, float(lg.yes_bid)) for lg in legs)
    payout = float(n)  # pay $1 on the winning YES
    edge = proceeds - payout - fees
    return {
        "complete": True,
        "count": n,
        "proceeds": round(proceeds, 4),
        "fees": round(fees, 4),
        "payout": round(payout, 4),
        "edge": round(edge, 4),
        "reason": "ok" if edge > 0 else "no_edge",
    }


def nested_monotone(legs: list[LadderLeg]) -> dict:
    """P(>k) must fall as k rises. Report every adjacent inversion.

    Legs need ``threshold`` set. Sorted ascending in k.
    """
    ranked = sorted(
        [lg for lg in legs if lg.threshold is not None],
        key=lambda lg: lg.threshold)
    violations = []
    locked = []
    for a, b in zip(ranked, ranked[1:]):
        # a is easier (lower k, should be more expensive); b is harder
        mid_a, mid_b = a.mid, b.mid
        inverted_mid = (
            mid_a is not None and mid_b is not None and mid_b > mid_a + 1e-9)
        if inverted_mid:
            violations.append({
                "outer": a.ticker, "inner": b.ticker,
                "k_outer": a.threshold, "k_inner": b.threshold,
                "mid_outer": round(mid_a, 4), "mid_inner": round(mid_b, 4),
                "mid_gap": round(mid_b - mid_a, 4),
            })
        if a.yes_ask is None or b.yes_bid is None:
            continue
        # Buy outer (easier) at ask, sell inner (harder) at bid.
        # Worst-state locked edge = bid_inner - ask_outer - fees (1 lot).
        fees = taker_fee(1, a.yes_ask) + taker_fee(1, b.yes_bid)
        edge = b.yes_bid - a.yes_ask - fees
        if edge > 0:
            sz = int(min(_pos(a.yes_ask_size), _pos(b.yes_bid_size)))
            locked.append({
                "outer": a.ticker, "inner": b.ticker,
                "k_outer": a.threshold, "k_inner": b.threshold,
                "ask_outer": a.yes_ask, "bid_inner": b.yes_bid,
                "fees": round(fees, 4),
                "edge_1": round(edge, 4),
                "count": sz,
                "edge_sized": round(edge * sz, 4) if sz else 0.0,
            })
    return {
        "n_legs": len(ranked),
        "n_mid_inversions": len(violations),
        "n_locked": len(locked),
        "violations": violations,
        "locked": locked,
        "tradeable": any((x.get("count") or 0) >= 1 and x["edge_sized"] > 0
                         for x in locked),
    }


def exclusive_adjacent_monotone(legs: list[LadderLeg]) -> dict:
    """Adjacent exclusive mids should not jump in a way that prints a
    higher mass on a further-from-spot wing than the ATM bucket while
    both are quoted. This is a diagnostic, not an arb by itself.
    """
    ranked = sorted(
        [lg for lg in legs if lg.floor is not None],
        key=lambda lg: lg.floor)
    jumps = []
    for a, b in zip(ranked, ranked[1:]):
        if a.mid is None or b.mid is None:
            continue
        # overlapping floors/caps is a contract-spec bug
        if a.cap is not None and b.floor is not None and b.floor + 1e-9 < a.cap:
            jumps.append({"a": a.ticker, "b": b.ticker, "kind": "overlap",
                          "a_cap": a.cap, "b_floor": b.floor})
        if a.cap is not None and b.floor is not None and b.floor > a.cap + 1e-6:
            jumps.append({"a": a.ticker, "b": b.ticker, "kind": "gap",
                          "a_cap": a.cap, "b_floor": b.floor})
    return {"n_ranked": len(ranked), "n_flags": len(jumps), "flags": jumps}


def ensemble_to_brackets(values: list[float], legs: list[LadderLeg],
                         round_to: float | None = None) -> dict:
    """Map numeric ensemble members onto exclusive legs.

    Kalshi ``between`` contracts include both printed bounds (weather
    "75-76°" is 75 and 76; BTC ``77000–77099.99`` is that closed
    interval). ``less`` is x < cap. ``greater`` is x > floor.
    """
    nums = [float(v) for v in values if v is not None]
    if round_to:
        nums = [round(v / round_to) * round_to for v in nums]
    if not nums or not legs:
        return {"n_members": 0, "probs": {}, "unmapped": 0}
    counts = {lg.ticker: 0 for lg in legs}
    unmapped = 0
    for x in nums:
        hit = _match_leg(x, legs)
        if hit is None:
            unmapped += 1
        else:
            counts[hit] += 1
    n = len(nums)
    probs = {k: round(v / n, 6) for k, v in counts.items()}
    return {
        "n_members": n,
        "probs": probs,
        "counts": counts,
        "unmapped": unmapped,
        "mean": round(sum(nums) / n, 4),
        "p10": round(sorted(nums)[max(0, int(0.1 * n) - 1)], 4),
        "p50": round(sorted(nums)[n // 2], 4),
        "p90": round(sorted(nums)[min(n - 1, int(0.9 * n))], 4),
    }


def ensemble_exceedance(values: list[float], legs: list[LadderLeg]) -> dict:
    """P(x > k) for nested greater / greater_or_equal legs."""
    nums = [float(v) for v in values if v is not None]
    n = len(nums)
    probs = {}
    for lg in legs:
        k = lg.threshold
        if k is None:
            continue
        ge = (lg.strike_type or "").startswith("greater_or_equal")
        if n == 0:
            probs[lg.ticker] = None
            continue
        if ge:
            p = sum(1 for x in nums if x >= k) / n
        else:
            p = sum(1 for x in nums if x > k) / n
        probs[lg.ticker] = round(p, 6)
    return {"n_members": n, "probs": probs}


def _match_leg(x: float, legs: list[LadderLeg]) -> str | None:
    for lg in legs:
        st = (lg.strike_type or "").lower()
        lo, hi = lg.floor, lg.cap
        if st in ("less", "less_or_equal"):
            if hi is None:
                continue
            if st == "less_or_equal" and x <= hi:
                return lg.ticker
            if st == "less" and x < hi:
                return lg.ticker
            continue
        if st.startswith("greater"):
            if lo is None:
                continue
            if "equal" in st:
                if x >= lo:
                    return lg.ticker
            elif x > lo:
                return lg.ticker
            continue
        if lo is not None and hi is not None and lo <= x <= hi:
            return lg.ticker
        if lo is not None and hi is None and x >= lo:
            return lg.ticker
        if lo is None and hi is not None and x < hi:
            return lg.ticker
    return None


def nowcast_to_nested(point: float, legs: list[LadderLeg],
                      sigma: float | None = None) -> dict:
    """Point nowcast -> P(>k) for nested threshold contracts.

    If ``sigma`` is None the mapping is a step: P(>k) = 1 if point > k
    else 0. With sigma, P = 1 - Phi((k - point)/sigma) — a coarse
    print-error / revision band, not a structural model.
    """
    import math
    ranked = sorted(
        [lg for lg in legs if lg.threshold is not None],
        key=lambda lg: lg.threshold)
    probs = {}
    for lg in ranked:
        k = float(lg.threshold)
        if sigma is None or sigma <= 0:
            p = 1.0 if point > k else 0.0
        else:
            z = (k - point) / sigma
            p = 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))
        probs[lg.ticker] = round(p, 6)
    return {"point": point, "sigma": sigma, "probs": probs}


def fee_aware_edge(model_p: float, yes_ask: float | None,
                    yes_bid: float | None, count: int = 1) -> dict:
    """Take YES if model_p beats ask+fee; take NO if 1-model_p beats NO px."""
    yes_edge = no_edge = None
    side = None
    px = None
    if yes_ask is not None and 0 < yes_ask < 1:
        fee = taker_fee(count, yes_ask)
        yes_edge = count * (model_p - yes_ask) - fee
    if yes_bid is not None and 0 < yes_bid < 1:
        no_px = 1.0 - yes_bid
        fee = taker_fee(count, no_px)
        no_edge = count * ((1.0 - model_p) - no_px) - fee
    if (yes_edge or -1) > 0 and (yes_edge or 0) >= (no_edge or 0):
        side, px = "yes", yes_ask
    elif (no_edge or -1) > 0:
        side, px = "no", (1.0 - yes_bid) if yes_bid is not None else None
    return {
        "model_p": round(model_p, 6),
        "yes_edge": None if yes_edge is None else round(yes_edge, 4),
        "no_edge": None if no_edge is None else round(no_edge, 4),
        "side": side,
        "px": px,
        "count": count,
    }


def takeable_edge(model_p: float, yes_ask: float | None, yes_bid: float | None,
                  count: int = 1, min_px: float = 0.05,
                  max_px: float = 0.92) -> dict:
    """fee_aware_edge that refuses 1¢ leftovers and 99¢ last ticks."""
    use_ask = yes_ask if yes_ask is not None and min_px <= yes_ask <= max_px else None
    no_px = (1.0 - yes_bid) if yes_bid is not None else None
    use_bid = yes_bid if no_px is not None and min_px <= no_px <= max_px else None
    return fee_aware_edge(model_p, use_ask, use_bid, count=count)


def parse_strikes(market: dict) -> tuple[float | None, float | None, float | None, str]:
    """(floor, cap, nested_threshold, strike_type) from a Kalshi market."""
    def n(v):
        if v in (None, ""):
            return None
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            return None
    floor = n(market.get("floor_strike"))
    cap = n(market.get("cap_strike"))
    st = str(market.get("strike_type") or "").lower()
    thresh = None
    if st in ("greater", "greater_or_equal", "less", "less_or_equal"):
        thresh = floor if st.startswith("greater") else cap
    if thresh is None and st.startswith("greater"):
        import re
        m = re.search(r"T(-?\d+(?:\.\d+)?)$", str(market.get("ticker") or ""))
        if m:
            thresh = float(m.group(1))
    return floor, cap, thresh, st


def legs_from_markets(markets: list[dict], quotes: dict[str, object] | None = None
                      ) -> list[LadderLeg]:
    """Build legs from /markets rows plus optional Quote objects or dicts."""
    quotes = quotes or {}
    out = []
    for m in markets:
        tkr = m.get("ticker")
        if not tkr:
            continue
        floor, cap, thresh, st = parse_strikes(m)
        q = quotes.get(tkr)
        yes_bid = yes_ask = yes_bid_size = yes_ask_size = None
        if q is not None:
            yes_bid = _qattr(q, "yes_bid")
            yes_ask = _qattr(q, "yes_ask")
            yes_bid_size = _qattr(q, "yes_bid_size")
            yes_ask_size = _qattr(q, "yes_ask_size")
        else:
            yes_bid = _mdollar(m, "yes_bid_dollars", "yes_bid")
            yes_ask = _mdollar(m, "yes_ask_dollars", "yes_ask")
            if yes_ask is None:
                no_bid = _mdollar(m, "no_bid_dollars", "no_bid")
                if no_bid is not None:
                    yes_ask = 1.0 - no_bid
            yes_bid_size = _mdollar(m, "yes_bid_size_fp", "yes_bid_size")
            yes_ask_size = _mdollar(m, "yes_ask_size_fp", "yes_ask_size")
        last = _mdollar(m, "last_price_dollars", "last_price")
        vol = _mdollar(m, "volume_fp", "volume")
        out.append(LadderLeg(
            ticker=tkr, floor=floor, cap=cap, threshold=thresh,
            strike_type=st,
            yes_bid=yes_bid, yes_ask=yes_ask,
            yes_bid_size=yes_bid_size, yes_ask_size=yes_ask_size,
            volume=vol, last=last, title=str(m.get("title") or "")))
    return out


def _qattr(q, name):
    if isinstance(q, dict):
        v = q.get(name)
    else:
        v = getattr(q, name, None)
    if v is None:
        return None
    return float(v)


def _mdollar(m, *keys):
    for k in keys:
        v = m.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None
