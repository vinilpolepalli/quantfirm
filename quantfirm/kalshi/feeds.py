"""Live underlying feeds for the 15M metals desk.

Swissquote's public bboquotes endpoint is keyless and was measured within
~0.6 bp of the actual Pyth gold settlement print at a window boundary — it
is effectively the settlement feed for XAU/XAG. Copper has no accurate
keyless realtime feed (gold-api's HG is ~1% off); the copper feed here is
Kalshi-anchored (last window-open print) and is only good enough for marks,
NOT for entries — the live engine keeps copper disabled by default.
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
