"""Reference strategies. These set the bar the tournament swarm must beat.

Every function is causal: values at row t depend only on data at rows <= t.
Positions are fractions of bankroll in [0, 1] (Robinhood crypto is long-only).
Hysteresis matters more than signal quality at a 0.93%-per-side venue: entry
and exit thresholds are deliberately separated to cut turnover.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register


@register("buy_and_hold")
def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index)


@register("ma_cross")
def ma_cross(df: pd.DataFrame, fast: int = 24 * 2, slow: int = 24 * 20) -> pd.Series:
    """Classic golden-cross trend filter on hourly bars."""
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    return (f > s).astype(float)


@register("donchian")
def donchian(df: pd.DataFrame, entry: int = 24 * 20, exit_: int = 24 * 10) -> pd.Series:
    """Donchian channel breakout with asymmetric exit (turtle-style)."""
    upper = df["close"].rolling(entry).max().shift(1)
    lower = df["close"].rolling(exit_).min().shift(1)
    pos = np.full(len(df), np.nan)
    close = df["close"].to_numpy()
    up, lo = upper.to_numpy(), lower.to_numpy()
    holding = 0.0
    for i in range(len(df)):
        if not np.isnan(up[i]) and close[i] >= up[i]:
            holding = 1.0
        elif not np.isnan(lo[i]) and close[i] <= lo[i]:
            holding = 0.0
        pos[i] = holding
    return pd.Series(pos, index=df.index)


@register("tsmom")
def tsmom(df: pd.DataFrame, lookback: int = 24 * 30, band: float = 0.0) -> pd.Series:
    """Time-series momentum: long when trailing return positive by > band."""
    mom = df["close"].pct_change(lookback)
    pos = pd.Series(np.nan, index=df.index)
    pos[mom > band] = 1.0
    pos[mom < -band] = 0.0
    return pos.ffill().fillna(0.0)


@register("vol_target_hold")
def vol_target_hold(df: pd.DataFrame, target_ann_vol: float = 0.35,
                    vol_window: int = 24 * 30) -> pd.Series:
    """Always-long BTC scaled to a target annualised volatility."""
    ret = df["close"].pct_change()
    ann_vol = ret.rolling(vol_window).std() * np.sqrt(24 * 365)
    pos = (target_ann_vol / ann_vol).clip(0, 1)
    # round to coarse steps so vol drift doesn't cause constant rebalancing
    return (pos * 4).round() / 4


@register("trend_vol_composite")
def trend_vol_composite(df: pd.DataFrame, fast: int = 24 * 3, slow: int = 24 * 30,
                        target_ann_vol: float = 0.45, vol_window: int = 24 * 20) -> pd.Series:
    """Trend filter gated by vol targeting — trade only with the trend, sized
    down in chaos. The composite most likely to survive costs per literature."""
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    trend = (f > s).astype(float)
    ret = df["close"].pct_change()
    ann_vol = ret.rolling(vol_window).std() * np.sqrt(24 * 365)
    size = (target_ann_vol / ann_vol).clip(0, 1)
    pos = trend * (size * 4).round() / 4
    return pos
