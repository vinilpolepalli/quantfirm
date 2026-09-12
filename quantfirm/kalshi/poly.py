"""Public Polymarket 15-minute Up/Down books (read-only).

Kalshi BTC/ETH 15m YES = CF Benchmarks 60s print at window close >= strike
(open). Polymarket ``{btc,eth}-updown-15m-{unix}`` Up = Chainlink 60s TWAP
over the same ET quarter-hour >= the start price. Same clock, different
index and payoff (last print vs TWAP). Do not copy Poly prices onto Kalshi
as fair. Use as a second favorite tape: log it, optionally sit when the
sides disagree.

No Polymarket orders. No API key. SOL/XRP/DOGE 15m exist on Poly and stay
off the live Kalshi book (no harvested Kalshi tape).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
WINDOW_S = 900
POLY_ASSETS = ("btc", "eth")
POLY_LISTED = ("btc", "eth", "sol", "xrp", "doge")


def window_start(ts: float | None = None) -> int:
    t = int(ts if ts is not None else time.time())
    return (t // WINDOW_S) * WINDOW_S


def updown_slug(asset: str, ts: float | None = None) -> str:
    return f"{asset.lower()}-updown-15m-{window_start(ts)}"


def _parse_json_field(v: Any):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def bbo(levels: list | None, side: str) -> tuple[float | None, float | None]:
    """Best bid = max price; best ask = min price. Do not assume sort order."""
    if not levels:
        return None, None
    parsed = []
    for lvl in levels:
        if isinstance(lvl, dict):
            p, sz = lvl.get("price"), lvl.get("size")
        elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            p, sz = lvl[0], lvl[1]
        else:
            continue
        try:
            parsed.append((float(p), float(sz)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None, None
    p, sz = (max(parsed, key=lambda t: t[0]) if side == "bid"
              else min(parsed, key=lambda t: t[0]))
    return p, sz


@dataclass
class PolyQuote:
    """Up token ≈ Kalshi YES; Down token ≈ Kalshi NO."""

    asset: str
    slug: str
    up_bid: float | None
    up_ask: float | None
    down_bid: float | None
    down_ask: float | None
    ts: float
    liquidity: float | None = None

    @property
    def yes_bid(self) -> float | None:
        return self.up_bid

    @property
    def yes_ask(self) -> float | None:
        return self.up_ask

    @property
    def mid(self) -> float | None:
        if self.up_bid is None or self.up_ask is None:
            return None
        return (self.up_bid + self.up_ask) / 2


def poly_favorite(q: PolyQuote | None, price_min: float = 0.55) -> str | None:
    """Kalshi-side label: 'yes' = Poly Up, 'no' = Poly Down. None = coin-flip."""
    if q is None:
        return None
    cands = []
    if q.up_ask is not None and q.up_ask >= price_min:
        cands.append(("yes", q.up_ask))
    no_px = q.down_ask
    if no_px is None and q.up_bid is not None:
        no_px = 1.0 - q.up_bid
    if no_px is not None and no_px >= price_min:
        cands.append(("no", no_px))
    if not cands:
        return None
    return max(cands, key=lambda c: c[1])[0]


class PolymarketFeed:
    """Gamma catalog + CLOB BBO. Token IDs cached for the current window."""

    def __init__(self, timeout: float = 8.0, cache_s: float = 3.0):
        self.timeout = timeout
        self.cache_s = cache_s
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "quantfirm-kalshi-poly/0.1"
        # asset -> (window_start, up_id, down_id, liquidity)
        self._tokens: dict[str, tuple[int, str, str, float | None]] = {}
        self._last: dict[str, tuple[float, PolyQuote]] = {}

    def _get(self, url: str, params: dict | None = None) -> Any:
        r = self.s.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _token_ids(self, asset: str, start: int) -> tuple[str, str, float | None] | None:
        cached = self._tokens.get(asset)
        if cached and cached[0] == start:
            return cached[1], cached[2], cached[3]
        slug = updown_slug(asset, start)
        try:
            m = self._get(f"{GAMMA}/markets/slug/{slug}")
        except Exception:
            return None
        if isinstance(m, list):
            m = m[0] if m else {}
        outcomes = _parse_json_field(m.get("outcomes")) or []
        tokens = _parse_json_field(m.get("clobTokenIds")) or []
        if not isinstance(outcomes, list) or not isinstance(tokens, list):
            return None
        up_id = down_id = None
        for lab, tok in zip(outcomes, tokens):
            name = str(lab).strip().lower()
            if name in ("up", "yes"):
                up_id = str(tok)
            elif name in ("down", "no"):
                down_id = str(tok)
        if not up_id or not down_id:
            return None
        liq = m.get("liquidity")
        try:
            liquidity = float(liq) if liq is not None else None
        except (TypeError, ValueError):
            liquidity = None
        self._tokens[asset] = (start, up_id, down_id, liquidity)
        return up_id, down_id, liquidity

    def _book(self, token_id: str) -> tuple[float | None, float | None]:
        d = self._get(f"{CLOB}/book", params={"token_id": token_id})
        bid, _ = bbo(d.get("bids") or [], "bid")
        ask, _ = bbo(d.get("asks") or [], "ask")
        return bid, ask

    def quote(self, asset: str, now: float | None = None) -> PolyQuote | None:
        asset = asset.lower()
        now = time.time() if now is None else float(now)
        hit = self._last.get(asset)
        if hit and now - hit[0] < self.cache_s:
            return hit[1]
        start = window_start(now)
        ids = self._token_ids(asset, start)
        if not ids:
            return self._last[asset][1] if asset in self._last else None
        up_id, down_id, liquidity = ids
        try:
            up_bid, up_ask = self._book(up_id)
            down_bid, down_ask = self._book(down_id)
        except Exception:
            return self._last[asset][1] if asset in self._last else None
        q = PolyQuote(
            asset=asset, slug=updown_slug(asset, start),
            up_bid=up_bid, up_ask=up_ask, down_bid=down_bid, down_ask=down_ask,
            ts=now, liquidity=liquidity)
        self._last[asset] = (now, q)
        return q


def snapshot(assets: tuple[str, ...] = POLY_ASSETS, feed: PolymarketFeed | None = None
             ) -> dict[str, dict]:
    feed = feed or PolymarketFeed()
    out = {}
    for a in assets:
        q = feed.quote(a)
        if q is None:
            out[a] = {"ok": False}
            continue
        out[a] = {
            "ok": True,
            "slug": q.slug,
            "up": [q.up_bid, q.up_ask],
            "down": [q.down_bid, q.down_ask],
            "favorite": poly_favorite(q),
        }
    return out
