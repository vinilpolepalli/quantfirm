"""Copy Polymarket leader trades onto Kalshi, paper only.

The leaders trade on Polymarket. We never send a Polymarket order and we
never send a Kalshi order. A mapped fill is a simulated taker on the Kalshi
contract that is the same bet (team moneyline or draw), after a lag, at
Kalshi's quoted price, with the quadratic taker fee.

Selection for the quoted backtest uses only information from before
``CUTOFF`` (2026-09-15 00:00 UTC). Replaying the same window that put a
wallet on today's leaderboard is a separate, labeled trial.

Pre-registered trials live in ``TRIALS``. Do not add one after seeing P&L.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Fixed before any copy-trade P&L was computed.
CUTOFF = datetime(2026, 9, 15, tzinfo=timezone.utc)
CUTOFF_TS = int(CUTOFF.timestamp())
TOP_K = 5
LAG_S = 60
BUCKET_S = 300
MAX_SPREAD = 0.15
MAX_NAME_FRAC = 0.35
MAX_TICKER_FRAC = 0.35
MIN_PX = 0.02
MAX_PX = 0.98
FILL_GRACE_S = 300
PRICE_GATE = 0.03

# league slug prefix -> Kalshi game series. Verified against prod 2026-09-22.
LEAGUE_SERIES = {
    "epl": "KXEPLGAME",
    "lal": "KXLALIGAGAME",
    "ucl": "KXUCLGAME",
    "sea": "KXSERIEAGAME",
    "bun": "KXBUNDESLIGAGAME",
    "nfl": "KXNFLGAME",
    "mlb": "KXMLBGAME",
    "nba": "KXNBAGAME",
    "cfb": "KXNCAAFGAME",
    "atp": "KXATPMATCH",
    "wta": "KXWTAMATCH",
    "mls": "KXMLSGAME",
    "fl1": "KXLIGUE1GAME",
    "fac": "KXFACUPGAME",
    "efl": "KXEFLCHAMPIONSHIPGAME",
    "uel": "KXUELGAME",
}

# Decision trial is honest_pnl_equal at the close quote. The others are
# robustness, including a fade control and an adverse-price stress.
TRIALS = (
    {"name": "honest_pnl_equal", "rank": "pnl", "weight": "equal",
     "bankroll": 250.0, "price_gate": None, "biased": False, "fade": False,
     "fill": "close"},
    {"name": "honest_pnl_weighted", "rank": "pnl", "weight": "pnl",
     "bankroll": 250.0, "price_gate": None, "biased": False, "fade": False,
     "fill": "close"},
    {"name": "honest_vol_equal", "rank": "vol", "weight": "equal",
     "bankroll": 250.0, "price_gate": None, "biased": False, "fade": False,
     "fill": "close"},
    {"name": "honest_pnl_equal_500", "rank": "pnl", "weight": "equal",
     "bankroll": 500.0, "price_gate": None, "biased": False, "fade": False,
     "fill": "close"},
    {"name": "honest_pnl_pricegate", "rank": "pnl", "weight": "equal",
     "bankroll": 250.0, "price_gate": PRICE_GATE, "biased": False,
     "fade": False, "fill": "close"},
    {"name": "honest_pnl_equal_adverse", "rank": "pnl", "weight": "equal",
     "bankroll": 250.0, "price_gate": None, "biased": False, "fade": False,
     "fill": "adverse"},
    {"name": "fade_pnl_equal", "rank": "pnl", "weight": "equal",
     "bankroll": 250.0, "price_gate": None, "biased": False, "fade": True,
     "fill": "close"},
    {"name": "biased_week_pnl", "rank": "week", "weight": "equal",
     "bankroll": 250.0, "price_gate": None, "biased": True, "fade": False,
     "fill": "close"},
)

_STOP = {
    "fc", "cf", "afc", "sc", "ac", "ca", "de", "da", "do", "vs", "the", "club",
}
_BAD_TITLE = (
    "o/u", "over/under", "spread", "handicap", "up or down", "temperature",
    "both teams", "btts", "first inning", "nrfi", "assists", "rebounds",
    "yards", "touchdowns", "total points", "total goals", "set winner",
    "set ", "map ",
)
_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_TOKEN_RE = re.compile(r"-(\d{2}[A-Z]{3}\d{2})")
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


def taker_fee(count: float, price: float, multiplier: float = 1.0) -> float:
    """Quadratic taker fee. Sports series pass their own fee_multiplier.

    Metals are multiplier 1 → ceil(0.07·C·P·(1−P)). MLB was 0.5 on
    2026-09-22. Maker fees are not charged: the copy is a taker.
    """
    if count <= 0 or price <= 0.0 or price >= 1.0 or multiplier <= 0:
        return 0.0
    raw = 0.07 * multiplier * count * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def is_prior_sport(title: str) -> bool:
    """Closed-position titles we treat as a sports moneyline for ranking.

    This is the selection filter, not the trade mapper. The mapper requires
    Polymarket ``sportsMarketType == moneyline`` plus a Kalshi twin.
    """
    t = (title or "").lower()
    if any(b in t for b in _BAD_TITLE):
        return False
    return ("win on" in t or " vs " in t or " vs. " in t or "end in a draw" in t)


def date_token_from_slug(slug: str) -> str | None:
    """Kalshi date token, e.g. 2026-09-18 → 26SEP18. Not locale-dependent."""
    m = _DATE_RE.search(slug or "")
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    return f"{year % 100:02d}{_MONTHS[month - 1]}{day:02d}"


def date_token_from_ticker(ticker: str) -> str | None:
    m = _TOKEN_RE.search(ticker or "")
    return m.group(1) if m else None


def league_of(slug: str) -> str:
    return (slug or "").split("-", 1)[0].lower()


def tokens(name: str) -> set[str]:
    parts = re.split(r"[^a-z0-9]+", (name or "").lower())
    return {p for p in parts if len(p) >= 3 and p not in _STOP}


def names_match(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    if ta <= tb or tb <= ta:
        return True
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & big) / len(small) >= 0.67


def split_vs(title: str) -> list[str] | None:
    t = title or ""
    m = re.search(r"\((.+?)\bvs\.?\s+(.+?)\)", t, flags=re.I)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    tail = t.split(":")[-1]
    parts = re.split(r"\s+vs\.?\s+", tail, maxsplit=1, flags=re.I)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return [parts[0].strip(), parts[1].strip()]
    return None


def parse_jsonish(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        import json
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def weights_from_scores(scores: dict[str, float], mode: str) -> dict[str, float]:
    """Positive scores only. ``equal`` or proportional to the score."""
    clean = {k: float(v) for k, v in scores.items() if v is not None and float(v) > 0}
    if not clean:
        return {}
    if mode == "equal":
        w = 1.0 / len(clean)
        return {k: w for k in clean}
    total = sum(clean.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in clean.items()}


def top_scores(scores: dict[str, float], k: int = TOP_K) -> dict[str, float]:
    ranked = sorted(
        ((w, s) for w, s in scores.items() if s is not None and s > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return {w: s for w, s in ranked[:k]}


@dataclass
class Candle:
    end_ts: int
    yes_bid_low: float | None
    yes_bid_close: float | None
    yes_ask_high: float | None
    yes_ask_close: float | None
    volume: float = 0.0

    @property
    def yes_bid_for_low(self) -> float | None:
        return self.yes_bid_low if self.yes_bid_low is not None else self.yes_bid_close

    @property
    def yes_ask_for_high(self) -> float | None:
        return self.yes_ask_high if self.yes_ask_high is not None else self.yes_ask_close


@dataclass
class KMarket:
    ticker: str
    event_ticker: str
    series: str
    subtitle: str
    result: str | None
    close_ts: int | None
    fee_multiplier: float


@dataclass
class MappedTrade:
    wallet: str
    ts: int
    ticker: str
    kalshi_side: str
    action: str
    size: float
    poly_price: float
    fee_multiplier: float
    close_ts: int | None
    result: str | None


@dataclass
class Bucket:
    wallet: str
    ts_end: int
    ticker: str
    kalshi_side: str
    action: str
    size: float
    poly_notional: float
    fee_multiplier: float
    close_ts: int | None
    result: str | None

    @property
    def poly_vwap(self) -> float:
        if self.size <= 0:
            return 0.0
        return self.poly_notional / self.size


def contract_label(market: dict, outcome: str) -> tuple[str | None, str | None]:
    """Return (kalshi subtitle label, yes|no) for one Polymarket moneyline."""
    outcomes = [str(x) for x in parse_jsonish(market.get("outcomes"))]
    low = {o.lower() for o in outcomes}
    if low == {"yes", "no"}:
        raw = market.get("groupItemTitle") or ""
        question = market.get("question") or ""
        if raw.lower().startswith("draw") or "end in a draw" in question.lower():
            label = "Tie"
        else:
            label = raw
        ol = (outcome or "").strip().lower()
        if ol not in {"yes", "no"} or not label:
            return None, None
        return label, ol
    exact = [o for o in outcomes if o.lower() == (outcome or "").strip().lower()]
    if len(exact) == 1:
        return exact[0], "yes"
    return None, None


def _index_events(markets: list[KMarket]) -> dict[tuple[str, str], dict[str, list[KMarket]]]:
    out: dict[tuple[str, str], dict[str, list[KMarket]]] = {}
    for m in markets:
        token = date_token_from_ticker(m.event_ticker)
        if not token:
            continue
        bucket = out.setdefault((m.series, token), {})
        bucket.setdefault(m.event_ticker, []).append(m)
    return out


def build_market_index(markets: list[KMarket]):
    """(series, date token) -> event ticker -> markets."""
    return _index_events(markets)


def _choose_event(events: dict[str, list[KMarket]], title: str, label: str) -> str | None:
    sides = split_vs(title)
    scores: list[tuple[int, str]] = []
    for eid, mkts in events.items():
        subs = [m.subtitle for m in mkts]
        if sides and len(sides) == 2:
            score = sum(1 for s in sides if any(names_match(s, sub) for sub in subs))
        elif label == "Tie":
            score = 1 if any(s.lower() in {"tie", "draw"} for s in subs) else 0
        else:
            score = 1 if any(names_match(label, sub) for sub in subs) else 0
        scores.append((score, eid))
    if not scores:
        return None
    best = max(s for s, _ in scores)
    need = 2 if sides and len(sides) == 2 else 1
    if best < need:
        return None
    cands = [eid for s, eid in scores if s == best]
    if len(cands) != 1:
        return None
    return cands[0]


def _pick_market(mkts: list[KMarket], label: str) -> KMarket | None:
    if label == "Tie":
        hits = [m for m in mkts if m.subtitle.lower() in {"tie", "draw"}]
    else:
        hits = [m for m in mkts if names_match(label, m.subtitle)]
    if len(hits) != 1:
        return None
    return hits[0]


def map_trade(trade: dict, event: dict | None, markets: list[KMarket],
             index: dict | None = None) -> MappedTrade | None:
    """Map one Polymarket trade onto one Kalshi yes/no contract, or skip it."""
    if not event:
        return None
    slug = trade.get("slug") or ""
    gm = None
    for m in event.get("markets") or []:
        if m.get("slug") == slug:
            gm = m
            break
    if gm is None:
        return None
    if (gm.get("sportsMarketType") or "").lower() != "moneyline":
        return None
    event_slug = trade.get("eventSlug") or event.get("slug") or slug
    series = LEAGUE_SERIES.get(league_of(event_slug))
    token = date_token_from_slug(event_slug) or date_token_from_slug(slug)
    if not series or not token:
        return None
    label, kside = contract_label(gm, trade.get("outcome") or "")
    if not label or not kside:
        return None
    indexed = index if index is not None else _index_events(markets)
    events = indexed.get((series, token)) or {}
    title = event.get("title") or ""
    if label == "Tie":
        title = gm.get("groupItemTitle") or title
    eid = _choose_event(events, title, label)
    if eid is None:
        return None
    km = _pick_market(events[eid], label)
    if km is None:
        return None
    side = (trade.get("side") or "").upper()
    if side == "BUY":
        action = "buy"
    elif side == "SELL":
        action = "sell"
    else:
        return None
    try:
        size = float(trade.get("size") or 0)
        price = float(trade.get("price") or 0)
        ts = int(trade.get("timestamp") or 0)
    except (TypeError, ValueError):
        return None
    if size <= 0 or ts <= 0 or not (0 < price < 1):
        return None
    return MappedTrade(
        wallet=(trade.get("proxyWallet") or trade.get("wallet") or "").lower(),
        ts=ts,
        ticker=km.ticker,
        kalshi_side=kside,
        action=action,
        size=size,
        poly_price=price,
        fee_multiplier=km.fee_multiplier,
        close_ts=km.close_ts,
        result=km.result,
    )


def coalesce(trades: list[MappedTrade], bucket_s: int = BUCKET_S) -> list[Bucket]:
    """Merge same-side clips in a bucket. Act at the bucket close, not the first print."""
    groups: dict[tuple, Bucket] = {}
    for t in trades:
        bstart = (t.ts // bucket_s) * bucket_s
        key = (t.wallet, t.ticker, t.kalshi_side, t.action, bstart)
        g = groups.get(key)
        if g is None:
            groups[key] = Bucket(
                wallet=t.wallet, ts_end=bstart + bucket_s, ticker=t.ticker,
                kalshi_side=t.kalshi_side, action=t.action, size=t.size,
                poly_notional=t.size * t.poly_price, fee_multiplier=t.fee_multiplier,
                close_ts=t.close_ts, result=t.result,
            )
        else:
            g.size += t.size
            g.poly_notional += t.size * t.poly_price
    return sorted(groups.values(), key=lambda b: (b.ts_end, b.wallet, b.ticker, b.action))


def _two_sided(c: Candle, max_spread: float) -> bool:
    bid, ask = c.yes_bid_close, c.yes_ask_close
    if bid is None or ask is None:
        return False
    if not (0.0 < bid < 1.0 and 0.0 < ask < 1.0):
        return False
    if ask + 1e-9 < bid:
        return False
    if ask - bid > max_spread + 1e-9:
        return False
    return True


def first_candle(candles: list[Candle], ts: int, close_ts: int | None,
                 grace_s: int, max_spread: float) -> Candle | None:
    """First two-sided candle that ends at or after ``ts`` and not after the close."""
    start = 0
    # candles are sorted by end_ts
    lo, hi = 0, len(candles)
    while lo < hi:
        mid = (lo + hi) // 2
        if candles[mid].end_ts < ts:
            lo = mid + 1
        else:
            hi = mid
    start = lo
    last = ts + grace_s
    for c in candles[start:]:
        if c.end_ts > last:
            break
        if close_ts is not None and c.end_ts > close_ts:
            break
        if _two_sided(c, max_spread):
            return c
    return None


def _px_in_band(px: float | None) -> bool:
    return px is not None and MIN_PX <= px <= MAX_PX


def quote_prices(c: Candle, kalshi_side: str, fill: str) -> tuple[float | None, float | None]:
    """(buy price, sell price) for our side. Adverse uses the worse extreme."""
    if fill == "adverse":
        yes_buy = c.yes_ask_for_high
        yes_sell = c.yes_bid_for_low
    else:
        yes_buy = c.yes_ask_close
        yes_sell = c.yes_bid_close
    if kalshi_side == "yes":
        return yes_buy, yes_sell
    if yes_sell is None or yes_buy is None:
        return None, None
    # NO ask = 1 - YES bid; NO bid = 1 - YES ask. Adverse flips the extremes.
    if fill == "adverse":
        no_buy = None if c.yes_bid_for_low is None else 1.0 - c.yes_bid_for_low
        no_sell = None if c.yes_ask_for_high is None else 1.0 - c.yes_ask_for_high
        return no_buy, no_sell
    return 1.0 - yes_sell, 1.0 - yes_buy


def our_side(leader_side: str, fade: bool) -> str:
    if not fade:
        return leader_side
    return "no" if leader_side == "yes" else "yes"


@dataclass
class Lot:
    qty: int = 0
    basis: float = 0.0
    fee: float = 0.0


@dataclass
class Sleeve:
    cash0: float
    cash: float
    lots: dict[tuple[str, str], Lot] = field(default_factory=dict)
    closes: list[float] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    fees: float = 0.0

    def equity_at_cost(self) -> float:
        return self.cash + sum(lot.basis for lot in self.lots.values())


@dataclass
class LeaderBook:
    qty: dict[tuple[str, str], float] = field(default_factory=dict)
    cost: dict[tuple[str, str], float] = field(default_factory=dict)

    def apply(self, b: Bucket) -> None:
        key = (b.ticker, b.kalshi_side)
        if b.action == "buy":
            self.qty[key] = self.qty.get(key, 0.0) + b.size
            self.cost[key] = self.cost.get(key, 0.0) + b.poly_notional
            return
        q = self.qty.get(key, 0.0)
        if q <= 1e-9:
            return
        sell = min(b.size, q)
        frac = sell / q
        self.cost[key] = self.cost.get(key, 0.0) * (1.0 - frac)
        self.qty[key] = q - sell
        if self.qty[key] <= 1e-6:
            self.qty[key] = 0.0
            self.cost[key] = 0.0

    def targets(self, sleeve_budget: float, name_cap: float) -> dict[tuple[str, str], float]:
        total = sum(v for v in self.cost.values() if v > 0)
        if total <= 0 or sleeve_budget <= 0:
            return {}
        out = {}
        for k, c in self.cost.items():
            if c <= 0:
                continue
            out[k] = min(name_cap, c / total * sleeve_budget)
        s = sum(out.values())
        if s > sleeve_budget > 0:
            scale = sleeve_budget / s
            out = {k: v * scale for k, v in out.items()}
        return out

    def zero_ticker(self, ticker: str) -> None:
        for k in list(self.cost):
            if k[0] == ticker:
                self.cost[k] = 0.0
                self.qty[k] = 0.0


def _ticker_basis(sleeves: dict[str, Sleeve]) -> dict[str, float]:
    tot: dict[str, float] = {}
    for sleeve in sleeves.values():
        for (ticker, _side), lot in sleeve.lots.items():
            tot[ticker] = tot.get(ticker, 0.0) + lot.basis
    return tot


def _buy(sleeve: Sleeve, key: tuple[str, str], desired: float, px: float,
         mult: float, room: float) -> str:
    lot = sleeve.lots.get(key)
    cur = lot.basis if lot else 0.0
    target = min(desired, cur + max(0.0, room))
    gap = target - cur
    if gap < 1.0:
        return "small"
    qty = int(gap / px)
    fee = 0.0
    while qty > 0:
        fee = taker_fee(qty, px, mult)
        if qty * px + fee <= sleeve.cash + 1e-9:
            break
        qty -= 1
    if qty < 1:
        return "cash"
    sleeve.cash -= qty * px + fee
    sleeve.fees += fee
    if lot is None:
        sleeve.lots[key] = Lot(qty=qty, basis=qty * px, fee=fee)
    else:
        lot.qty += qty
        lot.basis += qty * px
        lot.fee += fee
    return "fill"


def _sell(sleeve: Sleeve, key: tuple[str, str], desired: float, px: float, mult: float) -> str:
    lot = sleeve.lots.get(key)
    if lot is None or lot.qty <= 0:
        return "flat"
    if desired >= lot.basis - 1.0:
        return "small"
    if desired <= 0.0:
        qty = lot.qty
    else:
        frac = (lot.basis - desired) / lot.basis
        qty = int(round(lot.qty * frac))
        qty = max(1, min(lot.qty, qty))
    fee = taker_fee(qty, px, mult)
    proceeds = qty * px - fee
    frac_q = qty / lot.qty
    basis_rel = lot.basis * frac_q
    fee_rel = lot.fee * frac_q
    sleeve.cash += proceeds
    sleeve.fees += fee
    pnl = proceeds - basis_rel - fee_rel
    sleeve.closes.append(pnl)
    sleeve.log.append({
        "ticker": key[0], "side": key[1], "pnl": round(pnl, 4), "kind": "sell",
    })
    lot.qty -= qty
    lot.basis -= basis_rel
    lot.fee -= fee_rel
    if lot.qty <= 0:
        del sleeve.lots[key]
    return "fill"


def _settle(sleeve: Sleeve, ticker: str, result: str) -> None:
    for key in list(sleeve.lots):
        t, side = key
        if t != ticker:
            continue
        lot = sleeve.lots[key]
        payout = float(lot.qty) if result == side else 0.0
        sleeve.cash += payout
        pnl = payout - lot.basis - lot.fee
        sleeve.closes.append(pnl)
        sleeve.log.append({
            "ticker": ticker, "side": side, "pnl": round(pnl, 4),
            "kind": "settle", "result": result,
        })
        del sleeve.lots[key]


def _ref_price(poly_vwap: float, leader_side: str, our: str) -> float:
    """Polymarket price of the side we are actually buying."""
    if our == leader_side:
        return poly_vwap
    return 1.0 - poly_vwap


def simulate(
    buckets: list[Bucket],
    candles: dict[str, list[Candle]],
    metas: dict[str, tuple[int | None, str | None, float]],
    weights: dict[str, float],
    *,
    bankroll: float,
    lag_s: int = LAG_S,
    max_spread: float = MAX_SPREAD,
    max_name_frac: float = MAX_NAME_FRAC,
    max_ticker_frac: float = MAX_TICKER_FRAC,
    price_gate: float | None = None,
    fade: bool = False,
    fill: str = "close",
    grace_s: int = FILL_GRACE_S,
) -> dict:
    """Paper-copy ``buckets`` for ``weights``. No orders leave this function."""
    if fill not in ("close", "adverse"):
        raise ValueError(fill)
    name_cap = max_name_frac * bankroll
    ticker_cap = max_ticker_frac * bankroll
    sleeves = {w: Sleeve(cash0=bankroll * wt, cash=bankroll * wt) for w, wt in weights.items()}
    leaders = {w: LeaderBook() for w in weights}
    skips: dict[str, int] = {}
    fills = 0
    peak = bankroll
    max_dd = 0.0

    def skip(reason: str) -> None:
        skips[reason] = skips.get(reason, 0) + 1

    def mark_dd() -> None:
        nonlocal peak, max_dd
        eq = sum(s.equity_at_cost() for s in sleeves.values())
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    events: list[tuple] = []
    for b in buckets:
        if b.wallet not in sleeves:
            continue
        events.append((b.ts_end, 1, "trade", b))
    seen_settle: set[str] = set()
    for b in buckets:
        if b.ticker in seen_settle:
            continue
        close_ts, result, _mult = metas.get(b.ticker, (b.close_ts, b.result, b.fee_multiplier))
        if close_ts and result in ("yes", "no"):
            events.append((close_ts, 0, "settle", (b.ticker, result)))
            seen_settle.add(b.ticker)
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    for _ts, _ord, kind, payload in events:
        if kind == "settle":
            ticker, result = payload
            for sleeve in sleeves.values():
                _settle(sleeve, ticker, result)
            for leader in leaders.values():
                leader.zero_ticker(ticker)
            mark_dd()
            continue
        b: Bucket = payload
        close_ts, result, mult = metas.get(
            b.ticker, (b.close_ts, b.result, b.fee_multiplier))
        mult = b.fee_multiplier or mult or 1.0
        if close_ts is not None and b.ts_end + lag_s >= close_ts:
            skip("after_close")
            leaders[b.wallet].apply(b)
            continue
        leaders[b.wallet].apply(b)
        targets = leaders[b.wallet].targets(sleeves[b.wallet].cash0, name_cap)
        sleeve = sleeves[b.wallet]
        copy_key = (b.ticker, our_side(b.kalshi_side, fade))
        allowed_buy = {copy_key} if b.action == "buy" else set()
        desired_by_our: dict[tuple[str, str], float] = {}
        for lk, dollars in targets.items():
            ok = (lk[0], our_side(lk[1], fade))
            desired_by_our[ok] = desired_by_our.get(ok, 0.0) + dollars
        keys = set(desired_by_our) | set(sleeve.lots)
        basis_now = _ticker_basis(sleeves)
        c = first_candle(
            candles.get(b.ticker) or [], b.ts_end + lag_s, close_ts, grace_s, max_spread)
        # A sell of a different ticker needs that ticker's book. Look up per key.
        for key in keys:
            desired = desired_by_our.get(key, 0.0)
            lot = sleeve.lots.get(key)
            cur = lot.basis if lot else 0.0
            ticker, side = key
            book = c if ticker == b.ticker else first_candle(
                candles.get(ticker) or [], b.ts_end + lag_s,
                metas.get(ticker, (None, None, 1.0))[0], grace_s, max_spread)
            if book is None:
                if abs(desired - cur) >= 1.0:
                    skip("no_book")
                continue
            buy_px, sell_px = quote_prices(book, side, fill)
            if desired > cur + 1.0:
                if key not in allowed_buy:
                    skip("reshuffle")
                    continue
                if not _px_in_band(buy_px):
                    skip("price_band")
                    continue
                ref = _ref_price(b.poly_vwap, b.kalshi_side, side)
                if price_gate is not None and buy_px is not None and buy_px - ref > price_gate:
                    skip("price_gate")
                    continue
                room = ticker_cap - basis_now.get(ticker, 0.0)
                status = _buy(sleeve, key, desired, float(buy_px), mult if ticker == b.ticker else metas.get(ticker, (None, None, 1.0))[2], room)
                if status == "fill":
                    fills += 1
                    basis_now[ticker] = basis_now.get(ticker, 0.0) + (
                        sleeve.lots[key].basis - cur)
                else:
                    skip(status)
            elif desired < cur - 1.0:
                if not _px_in_band(sell_px):
                    skip("price_band")
                    continue
                status = _sell(sleeve, key, desired, float(sell_px), mult if ticker == b.ticker else 1.0)
                if status == "fill":
                    fills += 1
                else:
                    skip(status)
        mark_dd()

    asof_cash = sum(s.cash for s in sleeves.values())
    open_basis = sum(lot.basis for s in sleeves.values() for lot in s.lots.values())
    mtm_extra = 0.0
    open_positions = []
    for w, sleeve in sleeves.items():
        for (ticker, side), lot in sleeve.lots.items():
            book = candles.get(ticker) or []
            last = None
            for c in book:
                if _two_sided(c, max_spread):
                    last = c
            sell_px = None
            if last is not None:
                _buy_px, sell_px = quote_prices(last, side, "close")
            if sell_px is not None and _px_in_band(sell_px):
                mtm_value = lot.qty * sell_px
            else:
                mtm_value = lot.basis
                sell_px = None
            mtm_extra += mtm_value
            open_positions.append({
                "wallet": w, "ticker": ticker, "side": side, "qty": lot.qty,
                "basis": round(lot.basis, 4),
                "mtm": round(mtm_value, 4),
                "sell_px": None if sell_px is None else round(sell_px, 4),
            })
    closes = [p for s in sleeves.values() for p in s.closes]
    realized = sum(closes)
    # Flat P&L equals sum of closes. Open positions: cash + mtm - bankroll.
    mtm_equity = asof_cash + mtm_extra
    cost_equity = asof_cash + open_basis
    return {
        "bankroll": bankroll,
        "pnl_settled": round(realized, 4),
        "pnl_mtm": round(mtm_equity - bankroll, 4),
        "pnl_mark_cost": round(cost_equity - bankroll, 4),
        "equity_mtm": round(mtm_equity, 4),
        "max_dd": round(max_dd, 4),
        "max_dd_pct": round(max_dd / bankroll, 6) if bankroll else None,
        "n_closes": len(closes),
        "n_fills": fills,
        "fees": round(sum(s.fees for s in sleeves.values()), 4),
        "open_basis": round(open_basis, 4),
        "n_open": len(open_positions),
        "skips": skips,
        "closes": [round(p, 4) for p in closes],
        "open": open_positions,
        "hit_rate": (round(sum(1 for p in closes if p > 0) / len(closes), 4)
                     if closes else None),
        "t_stat": _t_stat(closes),
        "by_ticker": _by_ticker(sleeves),
    }


def _by_ticker(sleeves: dict[str, Sleeve]) -> list[dict]:
    from collections import defaultdict
    agg: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0})
    for sleeve in sleeves.values():
        for row in sleeve.log:
            slot = agg[row["ticker"]]
            slot["pnl"] += row["pnl"]
            slot["n"] += 1
            slot["wins"] += 1 if row["pnl"] > 0 else 0
    rows = [
        {"ticker": t, "pnl": round(v["pnl"], 4), "n": v["n"], "wins": v["wins"]}
        for t, v in agg.items()
    ]
    rows.sort(key=lambda r: -r["pnl"])
    return rows


def _t_stat(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    if var <= 0:
        return None
    return round(mean / math.sqrt(var / n), 4)
