"""Public Polymarket and Kalshi reads for the copy-trade study.

No API key. No order endpoints. Responses cache under research/copytrade_cache
so a rerun prices the same tape.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone

import requests

from quantfirm.kalshi.copytrade import (
    CUTOFF_TS,
    LEAGUE_SERIES,
    Candle,
    KMarket,
)

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
SELECT_DAYS = 30
CLOSED_PAGE = 50
CLOSED_PAGES = 20
ACTIVITY_PAGE = 500
# data-api rejects offset >= 5000. Newest pages are the copy window.
ACTIVITY_MAX_OFFSET = 4500

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "research", "copytrade_cache")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "quantfirm-copytrade/0.1"
    s.headers["Accept"] = "application/json"
    return s


def _cache_path(url: str, params: dict | None) -> str:
    key = url + "?" + json.dumps(params or {}, sort_keys=True, default=str)
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return os.path.join(CACHE, digest + ".json")


def get_json(session: requests.Session, url: str, params: dict | None = None,
             tries: int = 4, use_cache: bool = True):
    os.makedirs(CACHE, exist_ok=True)
    path = _cache_path(url, params)
    if use_cache and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    last = None
    for i in range(tries):
        try:
            r = session.get(url, params=params, timeout=45)
        except requests.RequestException as e:
            last = e
            time.sleep(0.4 * (2 ** i))
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError as e:
                last = e
                time.sleep(0.4 * (2 ** i))
                continue
            with open(path, "w") as f:
                json.dump(data, f)
            return data
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503):
            last = r.status_code
            time.sleep(0.5 * (2 ** i))
            continue
        raise RuntimeError(f"HTTP {r.status_code} {url} {r.text[:180]}")
    raise RuntimeError(f"GET failed {url}: {last}")


def leaderboard(session, period: str, order: str, limit: int = 25) -> list[dict]:
    data = get_json(session, f"{DATA}/v1/leaderboard", {
        "category": "OVERALL",
        "timePeriod": period,
        "orderBy": order,
        "limit": limit,
    })
    return data or []


def closed_positions(session, wallet: str) -> tuple[list[dict], bool]:
    """Newest first. ``truncated`` is true if the page cap hit before the window."""
    rows: list[dict] = []
    start = CUTOFF_TS - SELECT_DAYS * 86400
    truncated = False
    for page in range(CLOSED_PAGES):
        batch = get_json(session, f"{DATA}/closed-positions", {
            "user": wallet,
            "limit": CLOSED_PAGE,
            "offset": page * CLOSED_PAGE,
        }) or []
        if not batch:
            return rows, False
        rows.extend(batch)
        oldest = min(int(r.get("timestamp") or 0) for r in batch)
        if len(batch) < CLOSED_PAGE or oldest < start:
            return rows, False
    return rows, True


def activity(session, wallet: str, stop_before: int, use_cache: bool = True) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()
    offset = 0
    while offset <= ACTIVITY_MAX_OFFSET:
        try:
            batch = get_json(session, f"{DATA}/activity", {
                "user": wallet,
                "limit": ACTIVITY_PAGE,
                "offset": offset,
                "type": "TRADE",
            }, use_cache=use_cache) or []
        except RuntimeError as e:
            if "400" in str(e) or "offset" in str(e):
                break
            raise
        if not batch:
            break
        oldest = None
        for row in batch:
            ts = int(row.get("timestamp") or 0)
            oldest = ts if oldest is None else min(oldest, ts)
            key = (row.get("transactionHash"), row.get("asset"), ts,
                   row.get("side"), row.get("size"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        if len(batch) < ACTIVITY_PAGE or (oldest is not None and oldest < stop_before):
            break
        offset += ACTIVITY_PAGE
    return rows


def gamma_event(session, slug: str) -> dict | None:
    data = get_json(session, f"{GAMMA}/events", {"slug": slug})
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict) and data.get("slug"):
        return data
    return None


def _iso(s: str | None) -> int | None:
    if not s:
        return None
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _result(v) -> str | None:
    if v is None:
        return None
    text = str(v).strip().lower()
    if text in ("yes", "no"):
        return text
    return None


def series_fee(session, series: str) -> float | None:
    data = get_json(session, f"{KALSHI}/series/{series}")
    if not data:
        return None
    ser = data.get("series")
    if isinstance(ser, dict):
        try:
            return float(ser.get("fee_multiplier") or 1.0)
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def kalshi_markets(session, series: str, min_close: int, max_close: int,
                   fee_multiplier: float) -> list[KMarket]:
    out: list[KMarket] = []
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(30):
        params = {
            "series_ticker": series,
            "limit": 200,
            "min_close_ts": min_close,
            "max_close_ts": max_close,
        }
        if cursor:
            params["cursor"] = cursor
        data = get_json(session, f"{KALSHI}/markets", params)
        if not data:
            break
        for m in data.get("markets") or []:
            subtitle = m.get("yes_sub_title") or m.get("yes_subtitle") or ""
            out.append(KMarket(
                ticker=m.get("ticker") or "",
                event_ticker=m.get("event_ticker") or "",
                series=series,
                subtitle=subtitle,
                result=_result(m.get("result")),
                close_ts=_iso(m.get("close_time")),
                fee_multiplier=fee_multiplier,
            ))
        cursor = data.get("cursor") or ""
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    return out


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_candle(raw: dict) -> Candle | None:
    try:
        end = int(raw["end_period_ts"])
    except (KeyError, TypeError, ValueError):
        return None
    bid = raw.get("yes_bid") or {}
    ask = raw.get("yes_ask") or {}
    vol = _num(raw.get("volume_fp")) or 0.0
    return Candle(
        end_ts=end,
        yes_bid_low=_num(bid.get("low_dollars")),
        yes_bid_close=_num(bid.get("close_dollars")),
        yes_ask_high=_num(ask.get("high_dollars")),
        yes_ask_close=_num(ask.get("close_dollars")),
        volume=vol,
    )


def candlesticks(session, series: str, ticker: str, start: int, end: int) -> list[Candle]:
    """1-minute candles, chunked so a long game week is not one huge call."""
    out: list[Candle] = []
    step = 2 * 86400
    cursor_ts = start
    while cursor_ts < end:
        chunk_end = min(end, cursor_ts + step)
        data = get_json(session, f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks", {
            "start_ts": cursor_ts,
            "end_ts": chunk_end,
            "period_interval": 1,
        })
        for raw in (data or {}).get("candlesticks") or []:
            c = parse_candle(raw)
            if c is not None:
                out.append(c)
        cursor_ts = chunk_end
    out.sort(key=lambda c: c.end_ts)
    # drop duplicate ends
    dedup = []
    seen = set()
    for c in out:
        if c.end_ts in seen:
            continue
        seen.add(c.end_ts)
        dedup.append(c)
    return dedup


def orderbook_touch(session, ticker: str) -> tuple[float | None, float | None]:
    """(yes_bid, yes_ask) from the public book. None if one side is missing."""
    data = get_json(session, f"{KALSHI}/markets/{ticker}/orderbook", use_cache=False)
    if not data:
        return None, None
    book = data.get("orderbook") or {}
    fp = book.get("orderbook_fp") or data.get("orderbook_fp") or {}
    yes = fp.get("yes_dollars") or []
    no = fp.get("no_dollars") or []

    def _top(levels, want_max: bool):
        parsed = []
        for lvl in levels:
            try:
                parsed.append(float(lvl[0]))
            except (TypeError, ValueError, IndexError):
                continue
        if not parsed:
            return None
        return max(parsed) if want_max else min(parsed)

    yes_bid = _top(yes, True)
    no_bid = _top(no, True)
    yes_ask = None if no_bid is None else 1.0 - no_bid
    return yes_bid, yes_ask


def load_books(session, min_close: int, max_close: int) -> tuple[list[KMarket], dict[str, float]]:
    markets: list[KMarket] = []
    fees: dict[str, float] = {}
    for series in sorted(set(LEAGUE_SERIES.values())):
        fee = series_fee(session, series)
        if fee is None:
            print(f"series {series} not listed", flush=True)
            continue
        fees[series] = fee
        batch = kalshi_markets(session, series, min_close, max_close, fee)
        print(f"kalshi {series} markets {len(batch)} fee x{fee}", flush=True)
        markets.extend(batch)
    return markets, fees
