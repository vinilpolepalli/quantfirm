"""Kalshi Perps (margin) API client.

Same auth as the event-contract API (RSA-PSS over ``ts_ms + METHOD + path``
with the /trade-api/v2 prefix and no query string; KALSHI-ACCESS-* headers),
different hosts and a ``/margin`` namespace:

    REST prod  https://external-api.kalshi.com/trade-api/v2/margin/...
    REST demo  https://external-api.demo.kalshi.co/trade-api/v2/margin/...

Public market data (markets, orderbook, candlesticks, trades, funding
history/estimate, risk parameters, exchange status) needs NO credentials.
Balance, positions, risk, fee tiers and every order write need a key.

Vocabulary: ``side`` is ``bid`` (buy / go long) or ``ask`` (sell / go short).
Prices are fixed-point dollar strings with up to 4 decimals per contract
(KXBTCPERP is 0.0001 BTC, so ~$7.8 a contract); counts are fixed-point
strings with 2 decimals. There is no market order type: emulate with an
aggressive limit inside the price band + immediate_or_cancel.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any

import requests

from ..kalshi.client import KalshiApiError, _RsaSigner, normalize_pem
from .specs import (API_PREFIX, DEMO_BASE, MARGIN, PRICE_BAND_PCT, PRICE_BAND_TICKS,
                    PROD_BASE)


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    return Decimal(str(v))


@dataclass
class PerpQuote:
    ticker: str
    bid: Decimal | None
    ask: Decimal | None
    bid_size: Decimal | None
    ask_size: Decimal | None
    ts: float

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> float | None:
        m = self.mid
        if m is None or m == 0 or self.bid is None or self.ask is None:
            return None
        return float((self.ask - self.bid) / m * 10000)


def banded_price(side: str, best_bid: Decimal | None, best_ask: Decimal | None,
                 tick: Decimal, slack_ticks: int = 20) -> Decimal | None:
    """Aggressive limit that crosses the touch by ``slack_ticks`` but stays
    inside Kalshi's price band, so an IOC behaves like a bounded market order.

    Bids must be ≥ lower(80% of best bid, best bid − 1000 ticks); asks ≤
    higher(120% of best ask, best ask + 1000 ticks). We cross the far touch
    by a few ticks — never the whole band — because that slack IS our slippage
    ceiling.
    """
    if side == "bid":
        if best_ask is None:
            return None
        p = best_ask + tick * slack_ticks
        return p.quantize(tick, rounding=ROUND_UP)
    if side == "ask":
        if best_bid is None:
            return None
        p = best_bid - tick * slack_ticks
        if p <= 0:
            p = tick
        return p.quantize(tick, rounding=ROUND_DOWN)
    raise ValueError(side)


def inside_band(side: str, price: Decimal, best_bid: Decimal | None,
                best_ask: Decimal | None, tick: Decimal) -> bool:
    """Client-side replica of the venue's price band (rejects are cheap; a
    surprise reject inside an execution loop is not)."""
    if side == "bid":
        if best_bid is None:
            return True
        floor = min(best_bid * Decimal(1 - PRICE_BAND_PCT), best_bid - tick * PRICE_BAND_TICKS)
        return price >= floor
    if best_ask is None:
        return True
    ceil = max(best_ask * Decimal(1 + PRICE_BAND_PCT), best_ask + tick * PRICE_BAND_TICKS)
    return price <= ceil


class MarginClient:
    """Thin typed wrapper over the /margin surface."""

    def __init__(self, env: str = "prod", key_id: str | None = None,
                 private_key_pem: str | None = None, timeout: float = 15.0):
        assert env in ("prod", "demo")
        self.env = env
        self.base = PROD_BASE if env == "prod" else DEMO_BASE
        self.timeout = timeout
        # Kalshi recommends a dedicated key for perps; fall back to the
        # event-contract key names so one key can serve both while testing.
        if env == "prod":
            self.key_id = key_id or os.environ.get("KALSHI_PERPS_KEY_ID") or os.environ.get("KALSHI_PROD_KEY_ID")
        else:
            self.key_id = key_id or os.environ.get("KALSHI_PERPS_DEMO_KEY_ID") or os.environ.get("KALSHI_DEMO_KEY_ID")
        pem = private_key_pem or self._pem_from_env()
        self._signer = _RsaSigner(normalize_pem(pem)) if pem else None
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "quantfirm-perps/0.1"

    def _pem_from_env(self) -> str | None:
        names = (["KALSHI_PERPS_PRIVATE_KEY", "KALSHI_PROD_PRIVATE_KEY"] if self.env == "prod"
                 else ["KALSHI_PERPS_DEMO_PRIVATE_KEY", "KALSHI_DEMO_PRIVATE_KEY"])
        for var in names:
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
    def _headers(self, method: str, full_path: str) -> dict[str, str]:
        if not self.can_trade:
            return {}
        ts = str(int(time.time() * 1000))
        msg = ts + method + full_path.split("?")[0]
        return {"KALSHI-ACCESS-KEY": self.key_id,
                "KALSHI-ACCESS-SIGNATURE": self._signer.sign(msg),
                "KALSHI-ACCESS-TIMESTAMP": ts}

    def _req(self, method: str, path: str, params: dict | None = None,
             body: dict | None = None, auth: bool = False, tries: int = 4) -> dict:
        """``path`` is relative to /trade-api/v2 (e.g. "/margin/markets")."""
        full = API_PREFIX + path
        url = self.base + full
        last: Exception | None = None
        for i in range(tries):
            headers = self._headers(method, full) if auth else {}
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
        return self._req("GET", f"{MARGIN}/exchange/status")

    def markets(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return self._req("GET", f"{MARGIN}/markets", params=params).get("markets", [])

    def market(self, ticker: str) -> dict:
        d = self._req("GET", f"{MARGIN}/markets/{ticker}")
        return d.get("market", d)

    def quote(self, ticker: str, depth: int = 5) -> PerpQuote:
        d = self._req("GET", f"{MARGIN}/markets/{ticker}/orderbook", params={"depth": depth})
        ob = d.get("orderbook") or d
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        # levels arrive as [price, size]; best bid = max price, best ask = min price
        best_bid = max(bids, key=lambda l: Decimal(l[0])) if bids else None
        best_ask = min(asks, key=lambda l: Decimal(l[0])) if asks else None
        return PerpQuote(ticker,
                         _dec(best_bid[0]) if best_bid else None,
                         _dec(best_ask[0]) if best_ask else None,
                         _dec(best_bid[1]) if best_bid else None,
                         _dec(best_ask[1]) if best_ask else None,
                         time.time())

    def candlesticks(self, ticker: str, start_ts: int, end_ts: int,
                     period_interval: int = 60) -> list[dict]:
        assert period_interval in (1, 60, 1440)
        d = self._req("GET", f"{MARGIN}/markets/{ticker}/candlesticks",
                      params={"start_ts": start_ts, "end_ts": end_ts,
                              "period_interval": period_interval})
        return d.get("candlesticks", [])

    def trades(self, ticker: str, limit: int = 100, cursor: str | None = None) -> dict:
        params = {"ticker": ticker, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._req("GET", f"{MARGIN}/trades", params=params)

    def funding_history(self, ticker: str | None = None, start_ts: int | None = None,
                        end_ts: int | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if start_ts is not None:
            params["start_ts"] = start_ts
        if end_ts is not None:
            params["end_ts"] = end_ts
        d = self._req("GET", f"{MARGIN}/funding_rates/historical", params=params or None)
        return d.get("funding_rates", [])

    def funding_estimate(self, ticker: str) -> dict:
        return self._req("GET", f"{MARGIN}/funding_rates/estimate", params={"ticker": ticker})

    def risk_parameters(self) -> dict:
        return self._req("GET", f"{MARGIN}/risk_parameters")

    # -------------------------------------------------------------- account
    def enabled(self) -> dict:
        return self._req("GET", f"{MARGIN}/enabled", auth=True)

    def balance(self, compute_available: bool = False) -> dict:
        params = {"compute_available_balance": "true"} if compute_available else None
        return self._req("GET", f"{MARGIN}/balance", params=params, auth=True)

    def positions(self, ticker: str | None = None, subaccount: int | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if subaccount is not None:
            params["subaccount"] = subaccount
        return self._req("GET", f"{MARGIN}/positions", params=params or None,
                         auth=True).get("positions", [])

    def risk(self) -> dict:
        return self._req("GET", f"{MARGIN}/risk", auth=True)

    def fee_tiers(self) -> dict:
        return self._req("GET", f"{MARGIN}/fee_tiers", auth=True)

    def api_limits(self) -> dict:
        return self._req("GET", "/account/limits/perps", auth=True)

    def fills(self, **params) -> dict:
        return self._req("GET", f"{MARGIN}/fills", params=params or None, auth=True)

    def orders(self, **params) -> dict:
        return self._req("GET", f"{MARGIN}/orders", params=params or None, auth=True)

    # ----------------------------------------------------------- order flow
    def create_order(self, ticker: str, side: str, count: Decimal | int | str,
                     price: Decimal | str, time_in_force: str = "immediate_or_cancel",
                     post_only: bool = False, reduce_only: bool = False,
                     client_order_id: str | None = None,
                     expiration_time: int | None = None,
                     cancel_on_pause: bool = True) -> dict:
        """side: 'bid' buys (long), 'ask' sells (short). price in $/contract.

        reduce_only is only accepted with IOC/FOK (venue rule) — exits use it
        so a stale book can never flip a position.
        """
        assert side in ("bid", "ask")
        assert time_in_force in ("fill_or_kill", "good_till_canceled", "immediate_or_cancel")
        if reduce_only and time_in_force == "good_till_canceled":
            raise ValueError("reduce_only requires immediate_or_cancel or fill_or_kill")
        body: dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "side": side,
            "count": f"{Decimal(count):.2f}",
            "price": f"{Decimal(price):.4f}",
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "cancel_order_on_pause": bool(cancel_on_pause),
        }
        if post_only:
            body["post_only"] = True
        if reduce_only:
            body["reduce_only"] = True
        if expiration_time is not None:
            body["expiration_time"] = int(expiration_time)
        return self._req("POST", f"{MARGIN}/orders", body=body, auth=True, tries=1)

    def cancel_order(self, order_id: str) -> dict:
        return self._req("DELETE", f"{MARGIN}/orders/{order_id}", auth=True)

    def cancel_all(self) -> dict:
        return self._req("DELETE", f"{MARGIN}/orders", auth=True)

    def notional_risk_limit(self) -> dict:
        """Per-account notional cap set by the FCM (default ~$5,000/market)."""
        return self._req("GET", f"{MARGIN}/notional_risk_limit", auth=True)

    def _trigger_path(self, ticker: str, mode: str) -> str:
        assert mode in ("isolated", "cross")
        return f"{MARGIN}/{mode}/positions/{ticker}/exit_trigger"

    def set_bracket(self, ticker: str, stop_loss_price: Decimal | None = None,
                    take_profit_price: Decimal | None = None, mode: str = "cross",
                    client_trigger_id: str | None = None) -> dict:
        """Server-side stop/take-profit on the open position; fires reduce-only
        orders when the LIQUIDATION MARK crosses the level. This is the orphan
        protection: a dead bot still leaves a stop behind. API accounts are
        portfolio-margined, so ``cross`` is the default; the Kalshi apps use
        ``isolated``."""
        body: dict[str, Any] = {"kind": "bracket"}
        if stop_loss_price is not None:
            body["stop_loss_price"] = f"{Decimal(stop_loss_price):.4f}"
        if take_profit_price is not None:
            body["take_profit_price"] = f"{Decimal(take_profit_price):.4f}"
        if len(body) == 1:
            raise ValueError("bracket needs a stop_loss_price and/or take_profit_price")
        if client_trigger_id:
            body["client_trigger_id"] = client_trigger_id
        return self._req("PUT", self._trigger_path(ticker, mode), body=body, auth=True, tries=1)

    def set_trailing(self, ticker: str, trail_bps: int, mode: str = "cross") -> dict:
        body = {"kind": "trailing", "trail_bps": int(trail_bps)}
        return self._req("PUT", self._trigger_path(ticker, mode), body=body, auth=True, tries=1)

    def get_exit_triggers(self, ticker: str, mode: str = "cross") -> dict:
        return self._req("GET", self._trigger_path(ticker, mode), auth=True)

    def cancel_exit_trigger(self, ticker: str, mode: str = "cross") -> dict:
        return self._req("DELETE", self._trigger_path(ticker, mode), auth=True)


def parse_market(m: dict) -> dict:
    """Numeric view of a /margin/markets row (strings → floats)."""
    def f(k, default=None):
        v = m.get(k)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default
    lev = m.get("leverage_estimates") or {}
    return {
        "ticker": m.get("ticker"),
        "status": m.get("status"),
        "asset_class": (m.get("asset_class") or "").lower(),
        "contract_size": f("contract_size"),
        "tick_size": f("tick_size"),
        "bid": f("bid"), "ask": f("ask"), "last": f("price"),
        "reference": _nested_price(m, "reference_price"),
        "settlement_mark": _nested_price(m, "settlement_mark_price"),
        "liquidation_mark": _nested_price(m, "liquidation_mark_price"),
        "leverage_1k": float(lev.get("1000")) if lev.get("1000") else f("leverage_estimate"),
        "oi_usd": f("open_interest_notional_value_dollars"),
        "vol24h_usd": f("volume_24h_notional_value_dollars"),
        "schedule": m.get("schedule"),
    }


def _nested_price(m: dict, key: str) -> float | None:
    d = m.get(key) or {}
    try:
        return float(d.get("price")) if d.get("price") is not None else None
    except (TypeError, ValueError):
        return None
