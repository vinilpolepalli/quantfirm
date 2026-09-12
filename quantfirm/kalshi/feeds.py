"""Live underlying feeds for the 15M commodity desk.

Preferred: Kalshi event live_data (1-second, settlement-aligned) via
KalshiLiveFeed. Swissquote XAU/XAG is the fallback if live_data is empty.
KalshiAnchoredFeed (strike only) is marks-only and must not drive entries.
"""

from __future__ import annotations

import time

import requests

SQ_URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{sym}/USD"


class SwissquoteFeed:
    """Best bid/offer mid for XAU or XAG, polled; ~1 bp of the Pyth index."""

    def __init__(self, sym: str, timeout: float = 5.0):
        assert sym in ("XAU", "XAG")
        self.sym = sym
        self.timeout = timeout
        self.s = requests.Session()
        self.last: tuple[float, float] | None = None  # (ts, mid)

    def price(self) -> tuple[float, float] | None:
        """(ts, mid) or None on failure; caches last good tick."""
        try:
            r = self.s.get(SQ_URL.format(sym=self.sym), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            best_bid, best_ask = None, None
            for platform in data:
                for prof in platform.get("spreadProfilePrices", []):
                    b, a = prof.get("bid"), prof.get("ask")
                    if b and a:
                        if best_bid is None or b > best_bid:
                            best_bid = b
                        if best_ask is None or a < best_ask:
                            best_ask = a
            if best_bid and best_ask:
                self.last = (time.time(), (best_bid + best_ask) / 2)
        except Exception:
            pass
        return self.last


class KalshiLiveFeed:
    """Settlement-aligned 1-second print from Kalshi event live_data.

    This is the correct live S for every commodity 15M series: gold, silver,
    copper, WTI, natgas. Swissquote remains a fallback for XAU/XAG only.
    """

    def __init__(self, client, series: str, timeout: float = 8.0):
        self.client = client
        self.series = series
        self.timeout = timeout
        self.last: tuple[float, float] | None = None
        self._event: str | None = None
        self._event_exp: float = 0.0

    def _event_ticker(self) -> str | None:
        now = time.time()
        if self._event and now < self._event_exp:
            return self._event
        try:
            m = self.client.open_market_for_series(self.series)
        except Exception:
            return self._event
        if not m:
            return self._event
        self._event = m.get("event_ticker")
        # refresh a bit before window close
        try:
            from .client import parse_market_times
            _, close_ts = parse_market_times(m)
            self._event_exp = min(now + 120.0, close_ts)
        except Exception:
            self._event_exp = now + 60.0
        return self._event

    def price(self) -> tuple[float, float] | None:
        et = self._event_ticker()
        if not et:
            return self.last
        try:
            d = self.client.get_event_live_data(et)
            details = (d.get("live_data") or {}).get("details") or {}
            series = details.get("timeseries") or []
            if not series:
                return self.last
            last = series[-1]
            ts = float(last["t"]) / 1000.0
            self.last = (ts, float(last["v"]))
        except Exception:
            pass
        return self.last


class KalshiAnchoredFeed:
    """Copper stand-in: the strike of the newest 15M window IS the latest
    settlement print; between boundaries we have no intra-window signal.
    Only usable for marks/diagnostics — never for entry decisions."""

    def __init__(self, client, series: str = "KXCOPPER15M"):
        self.client = client
        self.series = series
        self.last: tuple[float, float] | None = None

    def price(self) -> tuple[float, float] | None:
        try:
            m = self.client.open_market_for_series(self.series)
            if m and m.get("floor_strike") is not None:
                self.last = (time.time(), float(m["floor_strike"]))
        except Exception:
            pass
        return self.last
