"""Reference strategies for the equity tournament — the bar to beat.

All causal; rebalance monthly (every 21 trading days) unless noted. ETF
strategies reference the survivorship-free ETF universe; stock strategies use
whatever columns the panel provides.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

ETF_MENU = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]
DEFENSIVE = ["TLT", "IEF", "SHY"]


def _rebalance_dates(index: pd.DatetimeIndex, every: int = 21) -> pd.DatetimeIndex:
    return index[::every]


def _weights_frame(index, columns) -> pd.DataFrame:
    return pd.DataFrame(0.0, index=index, columns=columns)


@register("spy_hold")
def spy_hold(closes: pd.DataFrame) -> pd.DataFrame:
    w = _weights_frame(closes.index[:1], closes.columns)
    if "SPY" in closes.columns:
        w.loc[:, "SPY"] = 1.0
    return w


@register("faber_sma")
def faber_sma(closes: pd.DataFrame, sma_days: int = 210, asset: str = "SPY",
              every: int = 21) -> pd.DataFrame:
    """Faber's classic: hold SPY when above its ~10-month SMA, else cash."""
    px = closes[asset]
    sma = px.rolling(sma_days).mean()
    dates = _rebalance_dates(closes.index, every)
    w = _weights_frame(dates, closes.columns)
    w.loc[:, asset] = (px.reindex(dates) > sma.reindex(dates)).astype(float)
    return w


@register("dual_momentum")
def dual_momentum(closes: pd.DataFrame, lookback: int = 252, every: int = 21,
                  risk_assets: tuple = ("SPY", "EFA"), safe_asset: str = "IEF") -> pd.DataFrame:
    """Antonacci GEM: best of risk assets by 12m momentum if positive, else bonds."""
    dates = _rebalance_dates(closes.index, every)
    w = _weights_frame(dates, closes.columns)
    mom = closes.pct_change(lookback)
    for d in dates:
        m = {a: mom.at[d, a] for a in risk_assets if a in mom.columns and pd.notna(mom.at[d, a])}
        if not m:
            continue
        best = max(m, key=m.get)
        if m[best] > 0:
            w.at[d, best] = 1.0
        elif safe_asset in closes.columns:
            w.at[d, safe_asset] = 1.0
    return w


@register("sector_rotation")
def sector_rotation(closes: pd.DataFrame, lookback: int = 126, top_n: int = 3,
                    every: int = 21, abs_filter: bool = True,
                    safe_asset: str = "IEF") -> pd.DataFrame:
    """Top-N sector SPDRs by momentum, absolute-momentum-gated into bonds."""
    dates = _rebalance_dates(closes.index, every)
    w = _weights_frame(dates, closes.columns)
    universe = [s for s in SECTORS if s in closes.columns]
    mom = closes.pct_change(lookback)
    for d in dates:
        vals = mom.loc[d, universe].dropna().sort_values(ascending=False)
        picks = [s for s in vals.index[:top_n] if (not abs_filter or vals[s] > 0)]
        for s in picks:
            w.at[d, s] = 1.0 / top_n
        rest = (top_n - len(picks)) / top_n
        if rest > 0 and safe_asset in closes.columns:
            w.at[d, safe_asset] = rest
    return w


@register("xsec_momentum")
def xsec_momentum(closes: pd.DataFrame, formation: int = 252, skip: int = 21,
                  top_n: int = 10, every: int = 21,
                  market_filter_sma: int = 0) -> pd.DataFrame:
    """Classic 12-1 cross-sectional momentum, long-only top-N of the stock
    universe, equal weight; optional SPY-SMA regime gate to cash."""
    etf_like = set(ETF_MENU + SECTORS + DEFENSIVE + ["DIA", "HYG", "LQD"])
    stocks = [c for c in closes.columns if c not in etf_like]
    dates = _rebalance_dates(closes.index, every)
    w = _weights_frame(dates, closes.columns)
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    gate = None
    if market_filter_sma and "SPY" in closes.columns:
        spy = closes["SPY"]
        gate = spy > spy.rolling(market_filter_sma).mean()
    for d in dates:
        if gate is not None and not bool(gate.reindex([d]).fillna(False).iloc[0]):
            continue
        vals = mom.loc[d].dropna().sort_values(ascending=False)
        for s in vals.index[:top_n]:
            if vals[s] > 0:
                w.at[d, s] = 1.0 / top_n
    return w
