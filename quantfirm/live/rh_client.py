"""Signed Robinhood Crypto API client.

Auth: Ed25519. Each request signs api_key + timestamp + path + method + body
and sends x-api-key / x-timestamp / x-signature headers.

Credentials come from the environment ONLY (never the repo):
    RH_API_KEY           rh-api-...
    RH_PRIVATE_KEY_B64   base64 of the raw 32-byte Ed25519 seed

Signing uses PyNaCl when importable and falls back to the openssl CLI, so the
client runs both on GitHub Actions runners and in constrained sandboxes.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import uuid

import requests

BASE = "https://trading.robinhood.com"
_ORDER_NS = uuid.UUID("b1e7c9d2-4a5f-4e6b-9c3d-2f8a1b0e7d55")


class RobinhoodCrypto:
    def __init__(self, api_key: str | None = None, private_key_b64: str | None = None):
        self.api_key = api_key or os.environ["RH_API_KEY"]
        self._seed = base64.b64decode(private_key_b64 or os.environ["RH_PRIVATE_KEY_B64"])
        if len(self._seed) != 32:
            raise ValueError("RH_PRIVATE_KEY_B64 must decode to 32 bytes")
        self._signer = self._make_signer()

    # -- signing ----------------------------------------------------------
    def _make_signer(self):
        try:
            from nacl.signing import SigningKey  # type: ignore
            sk = SigningKey(self._seed)
            return lambda msg: sk.sign(msg).signature
        except Exception:
            return self._openssl_sign

    def _openssl_sign(self, msg: bytes) -> bytes:
        der = (bytes.fromhex("302e020100300506032b657004220420") + self._seed)
        with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as kf:
            kf.write(der)
            key_path = kf.name
        with tempfile.NamedTemporaryFile(delete=False) as mf:
            mf.write(msg)
            msg_path = mf.name
        try:
            out = subprocess.run(
                ["openssl", "pkeyutl", "-sign", "-inkey", key_path,
                 "-keyform", "DER", "-rawin", "-in", msg_path],
                capture_output=True, check=True)
            return out.stdout
        finally:
            os.unlink(key_path)
            os.unlink(msg_path)

    # -- transport --------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        ts = str(int(time.time()))
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        msg = f"{self.api_key}{ts}{path}{method}{payload}".encode()
        sig = base64.b64encode(self._signer(msg)).decode()
        headers = {"x-api-key": self.api_key, "x-timestamp": ts, "x-signature": sig}
        if body is not None:
            headers["Content-Type"] = "application/json"
        r = requests.request(method, BASE + path, headers=headers,
                             data=payload if body is not None else None, timeout=30)
        if r.status_code >= 400:
            raise RobinhoodError(r.status_code, r.text)
        return r.json() if r.text else {}

    # -- endpoints --------------------------------------------------------
    def account(self) -> dict:
        return self._request("GET", "/api/v1/crypto/trading/accounts/")

    def best_bid_ask(self, symbol: str = "BTC-USD") -> dict:
        data = self._request("GET", f"/api/v1/crypto/marketdata/best_bid_ask/?symbol={symbol}")
        return data["results"][0]

    def holdings(self) -> list[dict]:
        return self._request("GET", "/api/v1/crypto/trading/holdings/").get("results", [])

    def trading_pair(self, symbol: str) -> dict:
        """Venue-served precision/min rules: min_order_size, asset_increment,
        status. Never hardcode these — they change per symbol."""
        data = self._request("GET", f"/api/v1/crypto/trading/trading_pairs/?symbol={symbol}")
        results = data.get("results", [])
        return results[0] if results else {}

    def orders(self) -> list[dict]:
        return self._request("GET", "/api/v1/crypto/trading/orders/").get("results", [])

    def place_market_order(self, symbol: str, side: str, asset_quantity: str,
                           client_order_id: str) -> dict:
        body = {
            "client_order_id": client_order_id,
            "side": side,
            "type": "market",
            "symbol": symbol,
            "market_order_config": {"asset_quantity": asset_quantity},
        }
        return self._request("POST", "/api/v1/crypto/trading/orders/", body)

    @staticmethod
    def deterministic_order_id(strategy: str, symbol: str, side: str, bar_iso: str) -> str:
        """Same (strategy, symbol, side, bar) always maps to the same UUID, so a
        re-run of the same hour cannot double-submit — the venue rejects the
        duplicate client_order_id."""
        return str(uuid.uuid5(_ORDER_NS, f"{strategy}|{symbol}|{side}|{bar_iso}"))


class RobinhoodError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body
