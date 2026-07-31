"""Candle acquisition.

Historical (backtests): Binance public data dumps (data.binance.vision) —
free, no auth, no geo-block, monthly zipped CSVs.

Live (signals in production): Kraken public OHLC endpoint — no auth. Signals
are computed on Kraken/Binance prices and executed on Robinhood; for the
multi-hour/day horizons we trade, cross-venue drift is negligible relative to
Robinhood's own ~0.9% spread.
"""

from __future__ import annotations

import io
import os
import zipfile

import pandas as pd
import requests

DATA_DIR = os.environ.get("QF_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))

_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]

KRAKEN_PAIRS = {"BTCUSDT": "XBTUSD", "ETHUSDT": "ETHUSD", "SOLUSDT": "SOLUSD"}


def load_history(symbol: str, interval: str = "1h") -> pd.DataFrame:
    """Load cached parquet/csv history produced by scripts/update_data.py."""
    for ext, reader in ((".parquet", pd.read_parquet), (".csv.gz", pd.read_csv)):
        path = os.path.join(DATA_DIR, f"{symbol}_{interval}{ext}")
        if os.path.exists(path):
            df = reader(path)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            return df.set_index("ts").sort_index()
    raise FileNotFoundError(f"no cached history for {symbol}_{interval} in {DATA_DIR}")


def fetch_binance_month(symbol: str, interval: str, ym: str) -> pd.DataFrame | None:
    url = (f"https://data.binance.vision/data/spot/monthly/klines/"
           f"{symbol}/{interval}/{symbol}-{interval}-{ym}.zip")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=_KLINE_COLS)
    if not str(df.iloc[0]["open_time"]).isdigit():
        df = df.iloc[1:].reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c])
    t = pd.to_numeric(df["open_time"])
    # Binance switched file timestamps from ms to us during 2025
    df["ts"] = pd.to_datetime(
        [pd.Timestamp(v, unit="us" if v > 10**14 else "ms") for v in t], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def fetch_kraken_recent(symbol: str, interval_minutes: int = 60) -> pd.DataFrame:
    """Last ~720 candles from Kraken public API (enough for live signals)."""
    pair = KRAKEN_PAIRS[symbol]
    r = requests.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": pair, "interval": interval_minutes},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(f"kraken error: {payload['error']}")
    key = [k for k in payload["result"] if k != "last"][0]
    rows = payload["result"][key]
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "vwap", "volume", "count"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c])
    df["ts"] = pd.to_datetime(pd.to_numeric(df["t"]), unit="s", utc=True)
    # last row is the still-forming candle — drop it so signals use closed bars only
    return df[["ts", "open", "high", "low", "close", "volume"]].iloc[:-1].set_index("ts")
