"""Refresh repo candle caches: Binance daily dumps for history + Kraken for
the freshest bars. Run nightly by CI (research.yml)."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from quantfirm.data import DATA_DIR, fetch_kraken_recent, load_history, _KLINE_COLS  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def fetch_binance_day(symbol: str, interval: str, day: date) -> pd.DataFrame | None:
    url = (f"https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}/"
           f"{symbol}-{interval}-{day.isoformat()}.zip")
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
    df["ts"] = pd.to_datetime(
        [pd.Timestamp(v, unit="us" if v > 10**14 else "ms") for v in t], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def main() -> None:
    for sym in SYMBOLS:
        hist = load_history(sym, "1h").reset_index()
        last = hist["ts"].max()
        frames = [hist]
        day = last.date()
        while day <= date.today():
            got = fetch_binance_day(sym, "1h", day)
            if got is not None:
                frames.append(got)
            day += timedelta(days=1)
        try:
            frames.append(fetch_kraken_recent(sym, 60).reset_index())
        except Exception as e:  # Kraken hiccups must not block the refresh
            print(f"{sym}: kraken top-up failed: {e}")
        full = pd.concat(frames).drop_duplicates(subset="ts").sort_values("ts")
        out = os.path.join(DATA_DIR, f"{sym}_1h.csv.gz")
        full.to_csv(out, index=False, compression="gzip")
        print(f"{sym}: {len(full)} rows through {full['ts'].max()}")


if __name__ == "__main__":
    main()
