"""Daily bars and funding for the perps research pass.

Kalshi perps are three months old (crypto since 2026-06-03, gold/silver since
2026-09-10), so every multi-year number in this desk is measured on a PROXY
and says so:

  * crypto price  : Coinbase Exchange spot daily candles, one product per
                    listed perp (BTC-USD 2015→, ETH-USD 2016→, LTC 2016→,
                    … HYPE-USD 2026→; see COINBASE_PRODUCTS). Kalshi crypto
                    perps settle and fund on the CF Benchmarks spot
                    composite, so spot is the right proxy for the perp's
                    price path; the live loop uses the same source, so
                    backtest and production see the same series.
  * metals price  : Yahoo front-month futures (GC=F, SI=F), daily. Kalshi's
                    metals perps reference the Pyth spot index; at a daily
                    horizon the futures/spot basis is a slow drift (≈ the
                    interest rate), which is exactly what perp funding would
                    charge — so it is booked, not ignored (see backtest).
  * funding proxy : Binance USDT-perp 8h funding history (2020→) run through
                    Kalshi's rounding/cap rule as a STRESS scenario. Kalshi's
                    own funding (2026-06→) is ~zero for the reason specs.py
                    explains, and is loaded as the base scenario.
  * Kalshi native : /margin candlesticks (1m/60m/1d) + funding history for
                    the live-period comparison.

Splits follow the firm convention (quantfirm/backtest.py): DEV before
2025-07-01, HOLDOUT from 2025-07-01, opened once by the judge.

BREADTH. Kalshi lists 23 perps and they did not all list on the same day;
neither did their proxies. A universe whose members appear (and, on
Coinbase, sometimes disappear) over time cannot be backtested off `align()`
alone, because `align()` forward-fills: a delisted asset keeps printing its
last close and reads as a zero-return, zero-vol, infinitely attractive
holding. `first_bar()` and `availability()` below are the fix — they report
where the NATIVE bars are, so a strategy can refuse to hold what the venue
was not quoting. `align()`'s ffill is deliberately left alone; the mask, not
the price frame, carries the tradability information.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import time
import zipfile

import pandas as pd
import requests

from .specs import SPECS, kalshi_funding

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("QF_PERPS_DATA", os.path.join(ROOT, "data", "perps"))

HOLDOUT_START = "2025-07-01"
DEV_START = "2016-01-01"

COINBASE = "https://api.exchange.coinbase.com"

# One Coinbase spot product per listed Kalshi crypto perp. Keys are the asset
# short names, which follow the venue's own ticker (KX<ASSET>PERP → <asset>);
# that rule reproduces every pre-existing name, including "kshib" for
# KXKSHIBPERP. Its underlying is kSHIB — title "1K kSHIB", contract_size 1000
# and underlying_multiplier 1000, so one contract is 1,000,000 SHIB (~$5.21 on
# 2026-09-15) and SHIB-USD spot is still the right price path. Ordered by
# Kalshi 24h notional volume on 2026-09-15, so the table doubles as the
# liquidity ranking the next campaign has to respect.
COINBASE_PRODUCTS = {
    "btc": "BTC-USD", "eth": "ETH-USD", "xrp": "XRP-USD", "sol": "SOL-USD",
    "zec": "ZEC-USD", "near": "NEAR-USD", "hype": "HYPE-USD", "vvv": "VVV-USD",
    "ada": "ADA-USD", "sui": "SUI-USD", "bch": "BCH-USD", "ltc": "LTC-USD",
    "doge": "DOGE-USD", "bnb": "BNB-USD", "link": "LINK-USD", "wld": "WLD-USD",
    "kshib": "SHIB-USD", "aave": "AAVE-USD",
    # listed on Kalshi but with zero open interest, zero 24h volume and no
    # two-sided quote on 2026-09-15: history is fetched so breadth studies can
    # include them the day they start quoting, NOT because they are tradable.
    "dot": "DOT-USD", "hbar": "HBAR-USD", "xlm": "XLM-USD",
}

# Earliest daily candle each product actually has, probed 2026-09-15. Only an
# optimisation: fetch_coinbase_daily pages backwards until it runs out of data,
# and these bounds stop it burning ~15 empty round trips per young product.
COINBASE_START = {
    "btc": "2015-01-01", "eth": "2016-01-01", "ltc": "2016-01-01", "bch": "2017-06-01",
    "xrp": "2018-10-01", "xlm": "2018-10-01", "link": "2019-01-01", "zec": "2020-06-01",
    "aave": "2020-06-01", "ada": "2020-10-01", "doge": "2021-01-01", "dot": "2021-01-01",
    "sol": "2021-01-01", "kshib": "2021-03-01", "near": "2022-03-01", "hbar": "2022-04-01",
    "sui": "2022-11-01", "vvv": "2024-07-01", "wld": "2024-10-01", "bnb": "2025-04-01",
    "hype": "2025-08-01",
}

YAHOO = {"gold": "GC=F", "silver": "SI=F"}

# Binance USDT-perp symbol for the funding STRESS scenario. Not every Kalshi
# perp has a Binance counterpart (VVV has none), and the ones that do start at
# very different dates; a missing symbol yields an empty frame, not an error.
BINANCE_FUNDING = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
    "ltc": "LTCUSDT", "bch": "BCHUSDT", "xlm": "XLMUSDT", "link": "LINKUSDT",
    "zec": "ZECUSDT", "aave": "AAVEUSDT", "ada": "ADAUSDT", "doge": "DOGEUSDT",
    "dot": "DOTUSDT", "kshib": "1000SHIBUSDT", "near": "NEARUSDT", "hbar": "HBARUSDT",
    "sui": "SUIUSDT", "wld": "WLDUSDT", "bnb": "BNBUSDT", "hype": "HYPEUSDT",
}

# Accepted spellings for an asset, resolved on every read. The venue ticker
# rule gives "kshib"; "shib" is the obvious thing a caller will type.
ASSET_ALIASES = {"shib": "kshib"}

_S = requests.Session()
_S.headers["User-Agent"] = "quantfirm-perps/0.1"


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def resolve_asset(asset: str) -> str:
    """Canonical short name for an asset ("shib" → "kshib")."""
    return ASSET_ALIASES.get(asset, asset)


def proxy_assets() -> tuple[str, ...]:
    """Every asset this module can fetch and load a long-history proxy for."""
    return tuple(COINBASE_PRODUCTS) + tuple(YAHOO)


def _read_csv(name: str) -> pd.DataFrame | None:
    for p in (_path(name + ".gz"), _path(name)):
        if os.path.exists(p):
            return pd.read_csv(p)
    return None


def _write_csv(df: pd.DataFrame, name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    p = _path(name + ".gz")
    with gzip.open(p, "wt") as f:
        df.to_csv(f, index=False)
    return p


# ------------------------------------------------------------------ loaders
def load_daily(asset: str) -> pd.DataFrame:
    """OHLCV indexed by UTC midnight timestamps; columns open/high/low/close/volume.

    Every row here is a NATIVE bar: no forward fill, no reindex onto anyone
    else's calendar. Absent days are absent, which is what `availability()`
    reads.
    """
    asset = resolve_asset(asset)
    df = _read_csv(f"{asset}_1d.csv")
    if df is None:
        raise FileNotFoundError(f"no daily bars for {asset} in {DATA_DIR}; run "
                                f"python -m quantfirm.perps.cli update-data")
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601").dt.normalize()
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])
    return df[["open", "high", "low", "close", "volume"]]


def load_panel(assets=None, skip_missing: bool = False) -> dict[str, pd.DataFrame]:
    """Native daily bars per asset. ``skip_missing`` drops assets with no file
    instead of raising — useful when a universe is declared ahead of its data."""
    assets = assets or tuple(SPECS)
    panel = {}
    for a in assets:
        try:
            panel[a] = load_daily(a)
        except FileNotFoundError:
            if not skip_missing:
                raise
    return panel


def load_funding_proxy(asset: str) -> pd.Series | None:
    """Binance 8h funding as a Series indexed by funding time (UTC). None if absent."""
    df = _read_csv(f"{resolve_asset(asset)}_funding_binance.csv")
    if df is None:
        return None
    s = pd.Series(pd.to_numeric(df["rate"], errors="coerce").values,
                  index=pd.to_datetime(df["ts"], utc=True, format="ISO8601"), name="rate").dropna()
    return s.sort_index()


def load_kalshi_funding(asset: str) -> pd.Series | None:
    df = _read_csv(f"{resolve_asset(asset)}_funding_kalshi.csv")
    if df is None:
        return None
    s = pd.Series(pd.to_numeric(df["rate"], errors="coerce").values,
                  index=pd.to_datetime(df["ts"], utc=True, format="ISO8601"), name="rate").dropna()
    return s.sort_index()


def daily_funding(rates_8h: pd.Series | None, index: pd.DatetimeIndex,
                  apply_kalshi_rule: bool = True, asset_class: str = "crypto") -> pd.Series:
    """Sum of per-interval funding rates falling on each UTC day of ``index``.

    A long position pays this fraction of notional per day when positive.
    Days with no rows (pre-history, outages) are 0.
    """
    if rates_8h is None or len(rates_8h) == 0:
        return pd.Series(0.0, index=index)
    r = rates_8h.copy()
    if apply_kalshi_rule:
        r = r.map(lambda x: kalshi_funding(x, asset_class))
    d = r.groupby(r.index.normalize()).sum()
    return d.reindex(index).fillna(0.0)


def split(df: pd.DataFrame, which: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(HOLDOUT_START, tz="UTC")
    if which == "dev":
        d = df.loc[DEV_START:]
        return d[d.index < cutoff]
    if which == "holdout":
        return df[df.index >= cutoff]
    if which == "all":
        return df
    raise ValueError("split must be dev|holdout|all")


def align(panel: dict[str, pd.DataFrame], how: str = "outer") -> pd.DataFrame:
    """Close prices as one wide frame (columns = assets), forward-filled over
    metals holidays so a Saturday BTC bar does not orphan gold. Weekend metals
    returns are therefore zero, which is what the venue would show too."""
    closes = pd.concat({a: d["close"] for a, d in panel.items()}, axis=1)
    return closes.sort_index().ffill()


# ------------------------------------------------------- listing / availability
# `align()` forward-fills, on purpose: a Saturday BTC bar must not orphan gold.
# The cost of that convenience is that a forward-filled price is
# indistinguishable from a real one, and on a 23-asset universe that is not a
# rounding error — XRP was delisted from Coinbase 2021-01-19 → 2023-07-13 (SEC
# suit), and a ffilled XRP over those 905 days is a flat line: zero return,
# zero vol, and therefore the largest position any vol-targeted or
# minimum-variance book would ever take, funded entirely by a price that did
# not exist. HYPE has 223 bars against BTC's 4,076; treating its pre-listing
# NaNs as "no opinion" instead of "not tradable" invents 10 years of history.
#
# So tradability is carried by a separate boolean mask, not by the price frame.

def first_bar(asset: str) -> pd.Timestamp:
    """Timestamp of the first NATIVE daily bar for ``asset`` (UTC midnight).

    This is when the proxy's history begins — the earliest date a strategy may
    claim to have known anything about the asset.
    """
    idx = load_daily(asset).index
    if not len(idx):
        raise ValueError(f"{resolve_asset(asset)} has no daily bars")
    return idx[0]


def last_bar(asset: str) -> pd.Timestamp:
    """Timestamp of the most recent NATIVE daily bar for ``asset``."""
    idx = load_daily(asset).index
    if not len(idx):
        raise ValueError(f"{resolve_asset(asset)} has no daily bars")
    return idx[-1]


def availability(panel: dict[str, pd.DataFrame], max_stale_days: int = 7,
                 index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Boolean frame on the aligned index: was each asset actually quoting?

    ``True`` on a date iff that asset printed a NATIVE bar within the previous
    ``max_stale_days`` (0 days stale — a bar that very day — counts). So:

      * before an asset's first bar → False (nothing to know, nothing to hold);
      * inside a delisting gap → False from ``max_stale_days`` after the last
        native bar until the feed comes back, which is exactly the window where
        `align()` is showing a flat forward-filled price;
      * over a metals weekend or holiday → True, because a 2–4 day gap is the
        contract's calendar, not an outage. That is why the default is 7 and
        not 1.

    The default tolerates a short data outage (the venue kept quoting, our
    fetch missed a day) while still catching a real delisting, which on this
    universe lasts months. Pass ``index`` to score the mask on the exact frame
    the caller trades; it defaults to ``align(panel).index``.
    """
    if max_stale_days < 0:
        raise ValueError("max_stale_days must be >= 0")
    idx = align(panel).index if index is None else pd.DatetimeIndex(index)
    tol = pd.Timedelta(days=max_stale_days)
    cols = {}
    for a, d in panel.items():
        # value at each native bar = that bar's own timestamp; ffill carries
        # "the last time this asset actually printed" across the aligned index.
        last_native = pd.Series(d.index, index=d.index).reindex(idx).ffill()
        cols[a] = last_native.notna() & ((idx - last_native) <= tol)
    return pd.DataFrame(cols, index=idx)[list(panel)].fillna(False).astype(bool)


def listing_table(assets=None) -> pd.DataFrame:
    """One row per asset: first/last native bar, row count, longest gap in days.

    The coverage evidence a breadth campaign has to cite before it claims a
    cross-sectional result.
    """
    assets = assets or proxy_assets()
    rows = []
    for a in assets:
        try:
            d = load_daily(a)
        except FileNotFoundError:
            rows.append({"asset": a, "first_bar": pd.NaT, "last_bar": pd.NaT,
                         "n_rows": 0, "max_gap_days": float("nan")})
            continue
        gaps = d.index.to_series().diff().dt.days
        rows.append({"asset": resolve_asset(a), "first_bar": d.index[0], "last_bar": d.index[-1],
                     "n_rows": len(d),
                     "max_gap_days": float(gaps.max()) if len(d) > 1 else 0.0})
    return pd.DataFrame(rows).set_index("asset")


# ----------------------------------------------------------------- fetchers
def fetch_coinbase_daily(product: str, start: str = "2015-01-01") -> pd.DataFrame:
    """Coinbase Exchange public candles, 300 per call, paged backwards."""
    end = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = pd.Timestamp(start, tz="UTC")
    rows = []
    cur_end = end + dt.timedelta(days=1)
    while cur_end > start_ts:
        cur_start = max(cur_end - dt.timedelta(days=299), start_ts.to_pydatetime())
        r = _S.get(f"{COINBASE}/products/{product}/candles",
                   params={"granularity": 86400, "start": cur_start.isoformat(),
                           "end": cur_end.isoformat()}, timeout=60)
        if r.status_code == 429:
            time.sleep(2)
            continue
        r.raise_for_status()
        data = r.json()
        if not data:
            cur_end = cur_start
            if cur_start <= start_ts:
                break
            continue
        rows += data
        cur_end = cur_start
        time.sleep(0.25)
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["t", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df = df.drop_duplicates("ts").sort_values("ts")
    return df[["ts", "open", "high", "low", "close", "volume"]]


def fetch_yahoo_daily(symbol: str, start: str = "2000-01-01") -> pd.DataFrame:
    import yfinance as yf
    d = yf.download(symbol, start=start, interval="1d", progress=False, auto_adjust=False)
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    d = d.rename(columns=str.lower)
    d.index = pd.to_datetime(d.index, utc=True)
    d.index.name = "ts"
    d = d.reset_index()
    return d[["ts", "open", "high", "low", "close", "volume"]]


def fetch_binance_funding(symbol: str, start_ym: tuple[int, int] = (2020, 1)) -> pd.DataFrame:
    """Monthly zips from data.binance.vision (no auth, not geo-blocked)."""
    y, m = start_ym
    now = dt.datetime.now(dt.timezone.utc)
    frames = []
    while (y, m) <= (now.year, now.month):
        url = (f"https://data.binance.vision/data/futures/um/monthly/fundingRate/"
               f"{symbol}/{symbol}-fundingRate-{y:04d}-{m:02d}.zip")
        r = _S.get(url, timeout=60)
        if r.status_code == 200:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0]).decode()
            first = raw.splitlines()[0].split(",")[0].strip()
            header = None if first.lstrip("-").isdigit() else 0
            df = pd.read_csv(io.StringIO(raw), header=header)
            if header is None:
                df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][:df.shape[1]]
            df.columns = [c.strip() for c in df.columns]
            frames.append(df)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if not frames:
        return pd.DataFrame(columns=["ts", "rate"])
    df = pd.concat(frames, ignore_index=True)
    t = df["calc_time"].astype("int64")
    t = t.where(t < 10**14, t // 1000)  # 2025+ dumps are microseconds
    out = pd.DataFrame({"ts": pd.to_datetime(t, unit="ms", utc=True),
                        "rate": pd.to_numeric(df["last_funding_rate"], errors="coerce")})
    return out.dropna().drop_duplicates("ts").sort_values("ts")


def fetch_kalshi_funding(ticker: str) -> pd.DataFrame:
    from .client import MarginClient
    rows = MarginClient("prod").funding_history(ticker)
    if not rows:
        return pd.DataFrame(columns=["ts", "rate", "mark"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({"ts": pd.to_datetime(df["funding_time"], utc=True),
                         "rate": pd.to_numeric(df["funding_rate"], errors="coerce"),
                         "mark": pd.to_numeric(df["mark_price"], errors="coerce")}
                        ).dropna(subset=["rate"]).sort_values("ts")


def fetch_kalshi_candles(ticker: str, period: int = 1440, start_ts: int = 1780000000) -> pd.DataFrame:
    from .client import MarginClient
    c = MarginClient("prod").candlesticks(ticker, start_ts, int(time.time()), period)
    rows = []
    for x in c:
        p = x.get("price") or {}
        b = x.get("bid") or {}
        a = x.get("ask") or {}
        rows.append({"end_ts": x.get("end_period_ts"), "open": p.get("open"), "high": p.get("high"),
                     "low": p.get("low"), "close": p.get("close"), "vwap": p.get("mean"),
                     "bid_close": b.get("close"), "ask_close": a.get("close"),
                     "volume": x.get("volume"), "volume_usd": x.get("volume_notional_value_dollars"),
                     "oi": x.get("open_interest"), "oi_usd": x.get("open_interest_notional_value_dollars")})
    df = pd.DataFrame(rows)
    if len(df):
        df["ts"] = pd.to_datetime(df["end_ts"].astype("int64"), unit="s", utc=True)
    return df


def update_all(assets=None, kalshi: bool = True, funding: bool = True, log=print) -> dict:
    """Refresh every cached file. Idempotent; safe to run daily.

    ``assets`` defaults to the research universe (``SPECS``); pass
    ``proxy_assets()`` (or the string ``"all"``) to refresh every listed perp's
    proxy, including the three with no live quote. Assets outside ``SPECS``
    simply skip the Kalshi leg — there is no spec to read a ticker from.
    """
    if assets == "all":
        assets = proxy_assets()
    assets = tuple(assets) if assets else tuple(SPECS)
    written = {}
    for a in (resolve_asset(x) for x in assets):
        if a in COINBASE_PRODUCTS:
            df = fetch_coinbase_daily(COINBASE_PRODUCTS[a], COINBASE_START.get(a, "2015-01-01"))
        elif a in YAHOO:
            df = fetch_yahoo_daily(YAHOO[a])
        else:
            continue
        if len(df):
            written[f"{a}_1d"] = _write_csv(df, f"{a}_1d.csv")
            log(f"{a}: {len(df)} daily bars {df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()}")
        if funding and a in BINANCE_FUNDING:
            try:
                f = fetch_binance_funding(BINANCE_FUNDING[a])
                if len(f):
                    written[f"{a}_funding_binance"] = _write_csv(f, f"{a}_funding_binance.csv")
                    log(f"{a}: {len(f)} binance funding rows")
            except Exception as e:  # noqa: BLE001 — a proxy feed is not load-bearing
                log(f"{a}: binance funding failed: {e}")
        if kalshi and a in SPECS:
            spec = SPECS[a]
            try:
                kf = fetch_kalshi_funding(spec.ticker)
                if len(kf):
                    written[f"{a}_funding_kalshi"] = _write_csv(kf, f"{a}_funding_kalshi.csv")
                kc = fetch_kalshi_candles(spec.ticker, 1440)
                if len(kc):
                    written[f"{a}_kalshi_1d"] = _write_csv(kc, f"{a}_kalshi_1d.csv")
                log(f"{a}: kalshi funding {len(kf)} rows, daily candles {len(kc)}")
            except Exception as e:  # noqa: BLE001
                log(f"{a}: kalshi fetch failed: {e}")
    meta = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "files": sorted(written)}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_path("META.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return meta


# ------------------------------------------------------------ auxiliary series
# Options-world and macro inputs for the research campaign. All keyless.
#   dvol_btc / dvol_eth : Deribit DVOL implied-vol index (daily close, since 2021-03)
#   macro               : VIX, DXY, US10Y yield, TIP ETF closes (Yahoo)
#   premium_btc/eth     : Binance USDT-perp premium index vs spot, daily mean (basis gauge)
AUX_FILES = {
    "dvol_btc": "aux_dvol_btc.csv", "dvol_eth": "aux_dvol_eth.csv",
    "macro": "aux_macro.csv", "premium_btc": "aux_premium_btc.csv", "premium_eth": "aux_premium_eth.csv",
}


def fetch_deribit_dvol(currency: str = "BTC", start: str = "2021-03-24") -> pd.DataFrame:
    """Deribit DVOL index, daily candles, paged in ~300-day windows."""
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end = int(time.time() * 1000)
    rows = []
    while t0 < end:
        t1 = min(t0 + 300 * 86400 * 1000, end)
        r = _S.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                   params={"currency": currency, "start_timestamp": t0, "end_timestamp": t1,
                           "resolution": 86400}, timeout=60)
        r.raise_for_status()
        data = (r.json().get("result") or {}).get("data") or []
        rows += data
        t0 = t1 + 1
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close"])
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.normalize()
    return df.drop_duplicates("ts").sort_values("ts")[["ts", "open", "high", "low", "close"]]


def fetch_macro() -> pd.DataFrame:
    import yfinance as yf
    cols = {}
    for name, sym in (("vix", "^VIX"), ("dxy", "DX-Y.NYB"), ("us10y", "^TNX"), ("tip", "TIP")):
        d = yf.download(sym, start="2010-01-01", interval="1d", progress=False, auto_adjust=False)
        if d is None or len(d) == 0:
            continue
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]
        s = d["Close"]
        s.index = pd.to_datetime(s.index, utc=True).normalize()
        cols[name] = s
        time.sleep(0.5)
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "ts"
    return df.reset_index()


def fetch_binance_premium_daily(symbol: str, start_ym: tuple[int, int] = (2020, 1)) -> pd.DataFrame:
    """Binance premiumIndexKlines 1d (perp premium over spot index), monthly zips."""
    y, m = start_ym
    now = dt.datetime.now(dt.timezone.utc)
    frames = []
    while (y, m) <= (now.year, now.month):
        url = (f"https://data.binance.vision/data/futures/um/monthly/premiumIndexKlines/"
               f"{symbol}/1d/{symbol}-1d-{y:04d}-{m:02d}.zip")
        r = _S.get(url, timeout=60)
        if r.status_code == 200:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            raw = z.read(z.namelist()[0]).decode()
            first = raw.splitlines()[0].split(",")[0].strip()
            header = None if first.lstrip("-").isdigit() else 0
            df = pd.read_csv(io.StringIO(raw), header=header)
            df = df.iloc[:, :5]
            df.columns = ["open_time", "open", "high", "low", "close"]
            frames.append(df)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if not frames:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close"])
    df = pd.concat(frames, ignore_index=True)
    t = df["open_time"].astype("int64")
    t = t.where(t < 10**14, t // 1000)
    df["ts"] = pd.to_datetime(t, unit="ms", utc=True).dt.normalize()
    return df.drop_duplicates("ts").sort_values("ts")[["ts", "open", "high", "low", "close"]]


def update_aux(log=print) -> dict:
    written = {}
    for cur in ("BTC", "ETH"):
        try:
            d = fetch_deribit_dvol(cur)
            if len(d):
                written[f"dvol_{cur.lower()}"] = _write_csv(d, AUX_FILES[f"dvol_{cur.lower()}"])
                log(f"dvol {cur}: {len(d)} rows {d['ts'].iloc[0].date()} → {d['ts'].iloc[-1].date()}")
        except Exception as e:  # noqa: BLE001
            log(f"dvol {cur} failed: {e}")
    try:
        m = fetch_macro()
        if len(m):
            written["macro"] = _write_csv(m, AUX_FILES["macro"])
            log(f"macro: {len(m)} rows, cols {list(m.columns)}")
    except Exception as e:  # noqa: BLE001
        log(f"macro failed: {e}")
    for a, sym in (("btc", "BTCUSDT"), ("eth", "ETHUSDT")):
        try:
            p = fetch_binance_premium_daily(sym)
            if len(p):
                written[f"premium_{a}"] = _write_csv(p, AUX_FILES[f"premium_{a}"])
                log(f"premium {a}: {len(p)} rows")
        except Exception as e:  # noqa: BLE001
            log(f"premium {a} failed: {e}")
    return written


def load_aux(name: str) -> pd.DataFrame:
    """Auxiliary daily series indexed by UTC midnight; columns depend on the series."""
    df = _read_csv(AUX_FILES[name])
    if df is None:
        raise FileNotFoundError(f"aux series {name} missing; run cli update-data --aux")
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601").dt.normalize()
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
