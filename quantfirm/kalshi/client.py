"""Kalshi Trade API v2 client (prod public data + demo/prod authed trading).

Auth: per-request RSA-PSS(SHA-256, MGF1-SHA256, salt=digest length) over
``f"{ts_ms}{METHOD}{path}"`` where path INCLUDES the /trade-api/v2 prefix and
EXCLUDES the query string. Headers: KALSHI-ACCESS-KEY / -SIGNATURE /
-TIMESTAMP. Keys never expire; there is no session token (legacy /login is
dead, returns 404).

Order writes use the V2 surface only — POST /portfolio/events/orders — the
legacy /portfolio/orders returns HTTP 410 on both envs. V2 vocabulary is
YES-legged: side "bid" buys YES, side "ask" sells YES (= long NO). Prices are
YES-price dollar strings ("0.5600"), counts are fixed-point strings ("20.00").
There is no market order type; emulate with an aggressive limit + IOC.

All prices/counts in API responses are decimal strings (*_dollars / *_fp);
the legacy integer-cent fields come back null. Parse the string fields.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests

PROD_BASE = "https://api.elections.kalshi.com"
DEMO_BASE = "https://demo-api.kalshi.co"
API_PREFIX = "/trade-api/v2"


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


def normalize_pem(raw: str) -> str:
    """Cloud secret stores often flatten PEMs to one line.

    Accepts real newlines, literal ``\\n``, or a single line with spaces
    between the BEGIN/END banners. Does not log the body.
    """
    import re
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return s
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    if "BEGIN" in s and "\n" not in s:
        m = re.match(
            r"^(-----BEGIN [^-]+-----)\s+(.+?)\s+(-----END [^-]+-----)$",
            s,
        )
        if m:
            header, body, footer = m.group(1), m.group(2), m.group(3)
            body = "".join(body.split())
            wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
            s = f"{header}\n{wrapped}\n{footer}\n"
    return s


@dataclass
class Quote:
    """Top of book for one binary market, YES-price terms."""

    ticker: str
    yes_bid: Decimal | None  # best resting bid for YES
    yes_ask: Decimal | None  # implied: 1 - best NO bid
    yes_bid_size: Decimal | None
    yes_ask_size: Decimal | None
    ts: float

    @property
    def mid(self) -> Decimal | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2


class KalshiClient:
    """Thin typed wrapper. Public market data needs no credentials on either env."""

    def __init__(self, env: str = "prod", key_id: str | None = None,
                 private_key_pem: str | None = None, timeout: float = 15.0):
        assert env in ("prod", "demo")
        self.env = env
        self.base = PROD_BASE if env == "prod" else DEMO_BASE
        self.timeout = timeout
        self.key_id = key_id or os.environ.get(
            "KALSHI_PROD_KEY_ID" if env == "prod" else "KALSHI_DEMO_KEY_ID")
        pem = private_key_pem or self._pem_from_env()
        self._signer = _RsaSigner(normalize_pem(pem)) if pem else None
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "quantfirm-kalshi/0.1"

    def _pem_from_env(self) -> str | None:
        var = "KALSHI_PROD_PRIVATE_KEY" if self.env == "prod" else "KALSHI_DEMO_PRIVATE_KEY"
        raw = os.environ.get(var)
        if raw:
            return normalize_pem(raw)
        path = os.environ.get(var + "_PATH")
        if path and os.path.exists(path):
            with open(path) as f:
                return normalize_pem(f.read())
        return None

    @property
    def can_trade(self) -> bool:
        return bool(self.key_id and self._signer)

    # ------------------------------------------------------------------ http
    def _headers(self, method: str, path: str) -> dict[str, str]:
        if not self.can_trade:
            return {}
        ts = str(int(time.time() * 1000))
        msg = ts + method + path.split("?")[0]
        sig = self._signer.sign(msg)
        return {"KALSHI-ACCESS-KEY": self.key_id,
                "KALSHI-ACCESS-SIGNATURE": sig,
                "KALSHI-ACCESS-TIMESTAMP": ts}

    def _req(self, method: str, path: str, params: dict | None = None,
             body: dict | None = None, auth: bool = False, tries: int = 4) -> dict:
        url = self.base + API_PREFIX + path
        last = None
        for i in range(tries):
            headers = self._headers(method, API_PREFIX + path) if auth else {}
            try:
                r = self.s.request(method, url, params=params, headers=headers,
                                   json=body, timeout=self.timeout)
            except requests.RequestException as e:
                last = e
                time.sleep(0.5 * 2 ** i)
                continue
            if r.status_code in (200, 201):
                return r.json() if r.text else {}
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(0.5 * 2 ** i)
                continue
            raise KalshiApiError(r.status_code, r.text[:500])
        raise KalshiApiError(0, f"retries exhausted: {last}")

    # ----------------------------------------------------------- market data
    def exchange_status(self) -> dict:
        return self._req("GET", "/exchange/status")

    def get_market(self, ticker: str) -> dict:
        return self._req("GET", f"/markets/{ticker}")["market"]

    def get_markets(self, **params) -> dict:
        return self._req("GET", "/markets", params=params)

    def open_market_for_series(self, series_ticker: str) -> dict | None:
        d = self.get_markets(series_ticker=series_ticker, status="open", limit=10)
        mkts = d.get("markets") or []
        return min(mkts, key=lambda m: m["close_time"]) if mkts else None

    def get_quote(self, ticker: str) -> Quote:
        d = self._req("GET", f"/markets/{ticker}/orderbook")
        fp = (d.get("orderbook") or {}).get("orderbook_fp") or d.get("orderbook_fp") or {}
        yes = fp.get("yes_dollars") or []
        no = fp.get("no_dollars") or []
        yes_bid = _dec(yes[-1][0]) if yes else None
        yes_bid_size = _dec(yes[-1][1]) if yes else None
        no_bid = _dec(no[-1][0]) if no else None
        no_bid_size = _dec(no[-1][1]) if no else None
        yes_ask = (Decimal(1) - no_bid) if no_bid is not None else None
        return Quote(ticker, yes_bid, yes_ask, yes_bid_size, no_bid_size, time.time())

    def get_event_live_data(self, event_ticker: str) -> dict:
        """1-second settlement-aligned timeseries for a 15M event.

        GET /live_data/events/{event_ticker} returns
        live_data.details.timeseries = [{t: epoch_ms, v: price}, ...].
        This is the same publisher the contract settles on (Pyth metals /
        PYTHOIL / NATGAS, exposed by Kalshi). Prefer it over any proxy.
        """
        return self._req("GET", f"/live_data/events/{event_ticker}")

    def get_trades(self, ticker: str, limit: int = 100) -> list[dict]:
        """Public trade tape, newest first. Fields: yes_price_dollars,
        count_fp, taker_side ('yes'|'no'), created_time, trade_id."""
        d = self._req("GET", "/markets/trades",
                      params={"ticker": ticker, "limit": limit})
        return d.get("trades", [])

    def get_candlesticks(self, series_ticker: str, ticker: str,
                         start_ts: int, end_ts: int, period_interval: int = 1) -> list[dict]:
        d = self._req("GET", f"/series/{series_ticker}/markets/{ticker}/candlesticks",
                      params={"start_ts": start_ts, "end_ts": end_ts,
                              "period_interval": period_interval})
        return d.get("candlesticks", [])

    # -------------------------------------------------------------- portfolio
    def balance(self) -> Decimal:
        d = self._req("GET", "/portfolio/balance", auth=True)
        # balance_dollars preferred; fall back to integer cents if present
        if d.get("balance_dollars") is not None:
            return _dec(d["balance_dollars"])
        return Decimal(d.get("balance", 0)) / 100

    def positions(self, **params) -> dict:
        return self._req("GET", "/portfolio/positions", params=params, auth=True)

    def fills(self, **params) -> dict:
        return self._req("GET", "/portfolio/fills", params=params, auth=True)

    def orders(self, **params) -> dict:
        return self._req("GET", "/portfolio/events/orders", params=params, auth=True)

    # ------------------------------------------------------------- order flow
    def create_order(self, ticker: str, side: str, count: Decimal | int,
                     price: Decimal, time_in_force: str = "immediate_or_cancel",
                     post_only: bool = False, client_order_id: str | None = None,
                     expiration_time: int | None = None) -> dict:
        """side: 'bid' = buy YES / long yes; 'ask' = sell YES / long no.

        price is ALWAYS the YES price in dollars, whichever side you take.
        """
        assert side in ("bid", "ask")
        body = {
            "ticker": ticker,
            "side": side,
            "count": f"{Decimal(count):.2f}",
            "price": f"{Decimal(price):.4f}",
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        if post_only:
            body["post_only"] = True
        if expiration_time is not None:
            body["expiration_time"] = expiration_time
        return self._req("POST", "/portfolio/events/orders", body=body, auth=True)

    def cancel_order(self, order_id: str) -> dict:
        return self._req("DELETE", f"/portfolio/events/orders/{order_id}", auth=True)


class KalshiApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Kalshi API error {status}: {body}")
        self.status = status
        self.body = body


class _RsaSigner:
    def __init__(self, pem: str):
        from cryptography.hazmat.primitives import serialization
        self._key = serialization.load_pem_private_key(
            normalize_pem(pem).encode(), password=None)

    def sign(self, msg: str) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        sig = self._key.sign(
            msg.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=hashes.SHA256().digest_size),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()


def parse_market_times(m: dict) -> tuple[int, int]:
    """(open_ts, close_ts) unix seconds from a market object."""
    from datetime import datetime

    def ts(s: str) -> int:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())

    return ts(m["open_time"]), ts(m["close_time"])
