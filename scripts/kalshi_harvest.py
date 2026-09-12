#!/usr/bin/env python3
"""Harvest Kalshi 15M metals history + underlying bars into data/kalshi/.

Resume-safe (skips candle fetches already on disk); public endpoints, no
credentials. Gzip everything at the end with --gzip. Run from repo root:

    python scripts/kalshi_harvest.py [--series KXGOLD15M ...] [--gzip]
"""
import argparse
import csv
import gzip
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime, timezone

import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "kalshi")
BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ["KXGOLD15M", "KXSILVER15M", "KXCOPPER15M", "KXWTI15M", "KXNATGAS15M",
          "KXBTC15M", "KXETH15M"]
YF = {"gold": "GC=F", "silver": "SI=F", "copper": "HG=F",
      "wti": "CL=F", "natgas": "NG=F",
      "btc": "BTC-USD", "eth": "ETH-USD"}

S = requests.Session()
S.headers["User-Agent"] = "quantfirm-research/0.1"


def get(path, params=None, tries=6):
    for i in range(tries):
        try:
            r = S.get(BASE + path, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * 2 ** i + random.random())
                continue
            print(f"HTTP {r.status_code} {path}", flush=True)
            time.sleep(1 + i)
        except Exception as e:
            print(f"ERR {path}: {e}", flush=True)
            time.sleep(1.5 * 2 ** i)
    return None


def gz_aware(path):
    return path + ".gz" if (not os.path.exists(path)
                            and os.path.exists(path + ".gz")) else path


def harvest_markets(series, min_close_ts=None):
    rows, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "settled", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        d = get("/markets", params)
        if d is None:
            break
        batch = d.get("markets", [])
        rows.extend(batch)
        cursor = d.get("cursor")
        if not cursor:
            break
        # Settled lists are newest-first. Stop paging once the whole page is
        # older than --min-close so BTC/ETH last-week pulls stay small.
        if min_close_ts is not None and batch:
            oldest = min(_market_close_ts(m) or 0 for m in batch)
            if oldest < min_close_ts:
                break
        time.sleep(0.15)
    if min_close_ts is not None:
        rows = [m for m in rows if (_market_close_ts(m) or 0) >= min_close_ts]
    fn = os.path.join(OUT, f"markets_{series}.jsonl")
    with open(fn, "w") as f:
        for m in rows:
            f.write(json.dumps(m) + "\n")
    print(f"{series}: {len(rows)} settled markets", flush=True)
    return rows


def _market_close_ts(m):
    raw = m.get("close_time") or m.get("expiration_time")
    if not raw:
        return None
    return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())


CANDLE_FIELDS = ["market_ticker", "end_period_ts",
                 "yes_bid_open", "yes_bid_high", "yes_bid_low", "yes_bid_close",
                 "yes_ask_open", "yes_ask_high", "yes_ask_low", "yes_ask_close",
                 "price_open", "price_high", "price_low", "price_close",
                 "volume", "open_interest"]


def _ohlc(d, key):
    o = d.get(key) or {}
    return [o.get(k + "_dollars") for k in ("open", "high", "low", "close")]


def harvest_candles(series, markets):
    fn = os.path.join(OUT, f"candles_{series}.csv")
    src = gz_aware(fn)
    done = set()
    if os.path.exists(src):
        opener = gzip.open if src.endswith(".gz") else open
        with opener(src, "rt") as f:
            for row in csv.reader(f):
                if row and row[0] != "market_ticker":
                    done.add(row[0])
        if src.endswith(".gz"):  # decompress so we can append
            with gzip.open(src, "rt") as fi, open(fn, "w") as fo:
                shutil.copyfileobj(fi, fo)
            os.remove(src)

    def ts(s):
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())

    todo = [m for m in markets if m["ticker"] not in done]
    print(f"{series}: fetching candles for {len(todo)} markets"
          f" ({len(done)} cached)", flush=True)
    mode = "a" if done else "w"
    with open(fn, mode, newline="") as f:
        w = csv.writer(f)
        if mode == "w":
            w.writerow(CANDLE_FIELDS)
        for i, m in enumerate(todo):
            d = get(f"/series/{series}/markets/{m['ticker']}/candlesticks",
                    {"start_ts": ts(m["open_time"]), "end_ts": ts(m["close_time"]),
                     "period_interval": 1})
            if d is None:
                continue
            for c in d.get("candlesticks", []):
                w.writerow([m["ticker"], c.get("end_period_ts")]
                           + _ohlc(c, "yes_bid") + _ohlc(c, "yes_ask")
                           + _ohlc(c, "price")
                           + [c.get("volume_fp"), c.get("open_interest_fp")])
            if i and i % 200 == 0:
                f.flush()
                print(f"{series}: {i}/{len(todo)}", flush=True)
            time.sleep(0.12)


def harvest_yf():
    import pandas as pd
    import yfinance as yf
    import yfinance._http as yh
    yh.HAS_CURL_CFFI = False  # agent-proxy compatibility
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    for metal, sym in YF.items():
        chunks = []
        for k in range(4):
            end = now - dt.timedelta(days=7 * k)
            try:
                df = yf.download(sym, start=end - dt.timedelta(days=7), end=end,
                                 interval="1m", progress=False,
                                 auto_adjust=False, prepost=True)
                if len(df):
                    chunks.append(df)
            except Exception as e:
                print(f"{sym} chunk {k}: {e}", flush=True)
        if not chunks:
            continue
        allb = pd.concat(chunks).sort_index()
        allb = allb[~allb.index.duplicated(keep="first")]
        allb.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                        for c in allb.columns]
        fn = os.path.join(OUT, f"yf_{metal}_1m.csv")
        old = gz_aware(fn)
        if os.path.exists(old):  # merge with previous harvest
            prev = pd.read_csv(old, index_col=0, parse_dates=True)
            prev.index = pd.to_datetime(prev.index, utc=True)
            allb.index = pd.to_datetime(allb.index, utc=True)
            allb = pd.concat([prev, allb]).sort_index()
            allb = allb[~allb.index.duplicated(keep="last")]
            if old.endswith(".gz"):
                os.remove(old)
        allb.to_csv(fn)
        print(f"{sym}: {len(allb)} 1m bars -> {fn}", flush=True)


def gzip_all():
    for name in os.listdir(OUT):
        p = os.path.join(OUT, name)
        if p.endswith((".csv", ".jsonl")):
            with open(p, "rb") as fi, gzip.open(p + ".gz", "wb") as fo:
                shutil.copyfileobj(fi, fo)
            os.remove(p)
            print(f"gzipped {name}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", nargs="*", default=SERIES)
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument("--skip-yf", action="store_true")
    ap.add_argument(
        "--min-close",
        default=None,
        help="ISO timestamp; drop settled markets that closed before this",
    )
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    min_close_ts = None
    if a.min_close:
        min_close_ts = int(datetime.fromisoformat(
            a.min_close.replace("Z", "+00:00")).timestamp())
    for s in a.series:
        harvest_candles(s, harvest_markets(s, min_close_ts=min_close_ts))
    if not a.skip_yf:
        harvest_yf()
    if a.gzip:
        gzip_all()
    print("done", flush=True)
