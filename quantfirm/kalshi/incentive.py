"""Shared Kalshi Liquidity Incentive Program scoring and selection.

Public endpoints only. Scan, stress, paper and quote all import this so
the walk cannot drift across files.

Rules, from the 2026 help article (13823851), not the 2025 CFTC backup
filing. The filing set Reference Price to the touch. The help article
explicitly says a small order at the top does not set it: Reference Price
is the first level, walking down from the best bid, at which cumulative
size reaches Target Size / 5.

  1. Snapshot once per second. Excluded unless both sides hold
     >= Target Size. Excluded snapshots pay nobody and shrink the pool.
  2. Reference Price = T/5 walk as above.
  3. Only orders that help reach Target Size on that side are scored.
     The UI gray-dot is this rule: once better-priced depth already
     equals Target Size, deeper orders do not qualify.
  4. At or better than the Reference Price: size x 1.0. k ticks below:
     size x DiscountFactor**k.
  5. Payout is your score / everyone's score, per side, each side half
     the pool. Under $1.00 per program is not paid.

`touch_reference` is a sensitivity for the 2025 filing, not the
production rule. Production quotes at the T/5 reference.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROGRAMS = "https://external-api.kalshi.com/trade-api/v2/incentive_programs"

# Paper / quote must share these or the shadow book measures a strategy
# the real one would never run.
MIN_HOURS_LEFT = 48.0
MIN_AGE_HOURS = 12.0
SELECTION = "aged12_qualifying"
MIN_PAYOUT = 1.0


def f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def ts(s) -> dt.datetime:
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def fetch_programs(status="active", incentive_type=None):
    """Page the public incentive_programs endpoint. type= is the wire name."""
    out, cursor = [], ""
    while True:
        q = f"status={status}&limit=1000"
        if incentive_type:
            q += f"&type={urllib.parse.quote(incentive_type)}"
        if cursor:
            q += f"&cursor={urllib.parse.quote(cursor)}"
        d = _get(f"{PROGRAMS}?{q}", timeout=60)
        page = d.get("incentive_programs", [])
        out += page
        cursor = d.get("next_cursor") or ""
        if not cursor or not page:
            return out


def fetch_markets(tickers, chunk=100, timeout=30):
    """GET /markets?tickers=, 100 at a time. Public, no auth."""
    out = {}
    tickers = [t for t in tickers if t]
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        q = "&".join("tickers=" + urllib.parse.quote(t) for t in batch)
        try:
            d = _get(f"{BASE}/markets?{q}", timeout=timeout)
        except Exception:
            continue
        for row in d.get("markets") or []:
            tk = row.get("ticker")
            if tk:
                out[tk] = row
    return out


def fetch_orderbooks(tickers, chunk=100, timeout=30):
    """GET /markets/orderbooks, 100 tickers per call. Public, no auth."""
    out = {}
    tickers = [t for t in tickers if t]
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        q = "&".join("tickers=" + urllib.parse.quote(t) for t in batch)
        try:
            d = _get(f"{BASE}/markets/orderbooks?{q}", timeout=timeout)
        except Exception:
            continue
        for row in d.get("orderbooks") or []:
            tk = row.get("ticker")
            if tk:
                out[tk] = row.get("orderbook_fp") or {}
    return out


def levels(ob_side) -> list[tuple[float, float]]:
    return [(f(p), f(s)) for p, s in (ob_side or []) if f(s) > 0]


def sorted_bids(book):
    return sorted(book, key=lambda z: -z[0])


def reference_price(book, target_size):
    """First price, walking down from the best bid, at which cum >= T/5."""
    if target_size <= 0:
        return None
    need = target_size / 5.0
    cum = 0.0
    for price, size in sorted_bids(book):
        cum += size
        if cum >= need:
            return price
    return None


def qualifying_slice(book, target_size):
    """First Target Size contracts from the top, or None if the side is thin.

    Help article: 'scores every resting order that helps reach the Target
    Size'. UI gray-dot: better-priced depth already at Target Size =>
    deeper orders do not qualify. If the walk never reaches Target Size,
    the side is excluded and this returns None.
    """
    if target_size <= 0:
        return None
    left, out = target_size, []
    for price, size in sorted_bids(book):
        take = min(size, left)
        if take > 0:
            out.append((price, take))
            left -= take
        if left <= 1e-9:
            return out
    return None


def better_depth(book, price) -> float:
    """Resting size strictly above `price` (better bids)."""
    return sum(s for p, s in book if p > price + 1e-12)


def order_qualifies(price, book, target_size) -> bool:
    """True iff an order at `price` is inside the Target Size walk."""
    return better_depth(book, price) < target_size


def discounted_score(book, ref, discount) -> float:
    """size x 1.0 at/above ref, size x discount**k ticks below."""
    if ref is None:
        return 0.0
    total = 0.0
    for price, size in book:
        ticks = round((ref - price) * 100)
        total += size * (discount ** ticks) if ticks > 0 else size
    return total


def score_side(book, target_size, discount):
    """Score one side. None if the book cannot set a reference price."""
    ref = reference_price(book, target_size)
    if ref is None:
        return None
    qual = qualifying_slice(book, target_size)
    depth = sum(s for _, s in book)
    return {
        "ref": ref,
        "depth": depth,
        "qual_score": discounted_score(qual, ref, discount) if qual else 0.0,
        "full_score": discounted_score(book, ref, discount),
        "excluded": qual is None,
        "touch": sorted_bids(book)[0][0] if book else None,
    }


def touch_reference(book):
    """2025 filing sensitivity: Reference Price = the touch."""
    bids = sorted_bids(book)
    return bids[0][0] if bids else None


def program_times(prog, now):
    start, end = ts(prog["start_date"]), ts(prog["end_date"])
    duration_h = (end - start).total_seconds() / 3600.0
    left_h = (end - now).total_seconds() / 3600.0
    age_h = (now - start).total_seconds() / 3600.0
    reward = f(prog.get("period_reward")) / 10000.0
    return start, end, duration_h, left_h, age_h, reward


def eligible_program(prog, now, min_hours_left=MIN_HOURS_LEFT,
                     min_age_hours=MIN_AGE_HOURS):
    if prog.get("incentive_type") != "liquidity":
        return False
    _, _, duration_h, left_h, age_h, _ = program_times(prog, now)
    if duration_h <= 0 or left_h < min_hours_left:
        return False
    if age_h < min_age_hours:
        return False
    return True


def price_book(prog, now, ob=None):
    """Price one liquidity program. None when the book cannot be scored."""
    ticker = prog["market_ticker"]
    if ob is None:
        try:
            ob = _get(f"{BASE}/markets/{ticker}/orderbook?depth=100")["orderbook_fp"]
        except Exception:
            return None
    yes, no = levels(ob.get("yes_dollars")), levels(ob.get("no_dollars"))
    if not yes or not no:
        return None
    target = f(prog.get("target_size_fp"))
    discount = (prog.get("discount_factor_bps") or 0) / 10000.0
    ys, ns = score_side(yes, target, discount), score_side(no, target, discount)
    if ys is None or ns is None or ys["ref"] <= 0 or ns["ref"] <= 0:
        return None
    start, end, duration_h, left_h, age_h, reward = program_times(prog, now)
    if duration_h <= 0:
        return None
    unit = ys["ref"] + ns["ref"]
    collateral = (sum(p * s for p, s in yes) + sum(p * s for p, s in no))
    return dict(
        ticker=ticker, target=target, discount=discount,
        yes_ref=ys["ref"], no_ref=ns["ref"], unit=unit,
        yes_depth=ys["depth"], no_depth=ns["depth"],
        yes_score=ys["qual_score"], no_score=ns["qual_score"],
        yes_full=ys["full_score"], no_full=ns["full_score"],
        yes_excluded=ys["excluded"], no_excluded=ns["excluded"],
        yes_touch=ys["touch"], no_touch=ns["touch"],
        reward=reward, duration_h=duration_h, left_h=left_h, age_h=age_h,
        reward_per_hour=reward / duration_h,
        ends=prog["end_date"], starts=prog["start_date"],
        collateral=collateral,
        yes_book=yes, no_book=no,
    )


def share_for_size(size, yes_score, no_score) -> float:
    if size <= 0:
        return 0.0
    return 0.5 * (size / (size + yes_score) + size / (size + no_score))


def rate_per_hour(m, capital):
    """$/hour for `capital` split across both legs at the T/5 ref.

    Zero if our size still cannot get both sides over Target Size.
    Competition is the qualifying-depth score, not the whole book.
    """
    if m["unit"] <= 0:
        return 0.0, 0.0, 0.0, True
    size = capital / m["unit"]
    excluded = (m["yes_depth"] + size < m["target"] or
                m["no_depth"] + size < m["target"])
    if excluded:
        return 0.0, size, 0.0, True
    share = share_for_size(size, m["yes_score"], m["no_score"])
    return m["reward_per_hour"] * share, size, share, False


def plan_market(m, budget, min_payout=MIN_PAYOUT):
    """Size a two-sided quote, or None if it cannot earn the $1 minimum."""
    size = float(int(budget / m["unit"])) if m["unit"] > 0 else 0.0
    if size < 1:
        return None
    if m["yes_depth"] + size < m["target"] or m["no_depth"] + size < m["target"]:
        return None
    if not order_qualifies(m["yes_ref"], m.get("yes_book") or [], m["target"]):
        return None
    if not order_qualifies(m["no_ref"], m.get("no_book") or [], m["target"]):
        return None
    share = share_for_size(size, m["yes_score"], m["no_score"])
    expected = m["reward"] * share * min(1.0, m["left_h"] / m["duration_h"])
    if expected < min_payout:
        return None
    return dict(size=size, yes_cost=size * m["yes_ref"], no_cost=size * m["no_ref"],
                share=share, expected=expected)


def price_many(progs, now, workers=16):
    """Batch-fetch books, then score. Drops unreadable markets."""
    books = fetch_orderbooks([p["market_ticker"] for p in progs])
    def one(p):
        ob = books.get(p["market_ticker"])
        if ob is None:
            return None
        return price_book(p, now, ob=ob)
    if workers <= 1:
        return [m for m in (one(p) for p in progs) if m]
    with ThreadPoolExecutor(workers) as ex:
        return [m for m in ex.map(one, progs) if m]


def board_pool(progs, now, horizon_h=24.0) -> float:
    """Reward dollars accruing in the next horizon_h, board-wide."""
    end_h = now + dt.timedelta(hours=horizon_h)
    total = 0.0
    for p in progs:
        start, end, duration_h, _, _, reward = program_times(p, now)
        if duration_h <= 0:
            continue
        ov = max(0.0, (min(end, end_h) - max(start, now)).total_seconds() / 3600.0)
        total += reward * (ov / duration_h)
    return total
