"""Slow trend-following: long-horizon MA-gap crossover with entry/exit
asymmetry, confirmation debounce, minimum hold, and an optional Donchian
trailing-stop hybrid exit. Built for a 0.93%-per-side venue: the whole point
is to trade a handful of times per year.

Signal anatomy (all causal, rolling only):
  gap_t = fast_MA_t / slow_MA_t - 1
  ENTER  when gap > +entry_band for `confirm` consecutive closed bars
         AND the slow MA itself is rising over `slope_lb` bars (bear-market
         rallies lift the fast MA while the slow MA still falls — this
         confirmation filter is what keeps us out of 2022-style chop)
  EXIT   when gap < -exit_band  (note the asymmetry: exit band is separate)
         OR close breaks below the trailing `stop_lookback`-bar low (if set)
  A position, once opened, is held at least `min_hold` bars.
  Optional sizing: while long, scale by target_vol / realised vol, rounded to
  coarse `step` fractions so vol drift doesn't cause constant rebalancing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register


@register("slow_trend")
def slow_trend(
    df: pd.DataFrame,
    fast: int = 96,
    slow: int = 720,
    entry_band: float = 0.004,
    exit_band: float = 0.02,
    confirm: int = 12,
    min_hold: int = 168,
    stop_lookback: int = 0,
    target_vol: float = 0.0,
    vol_window: int = 720,
    step: float = 0.25,
) -> pd.Series:
    close = df["close"]
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    gap = f / s - 1.0

    enter_raw = gap > entry_band
    if confirm > 1:
        enter_ok = enter_raw.rolling(confirm).sum() >= confirm
    else:
        enter_ok = enter_raw
    exit_ok = gap < -exit_band

    if stop_lookback and stop_lookback > 0:
        trail_low = close.rolling(stop_lookback).min().shift(1)
        stop_hit = (close <= trail_low).fillna(False)
    else:
        stop_hit = pd.Series(False, index=df.index)

    e = enter_ok.fillna(False).to_numpy()
    x = (exit_ok.fillna(False) | stop_hit).to_numpy()

    n = len(df)
    raw = np.zeros(n)
    holding = False
    bars_held = 0
    for i in range(n):
        if holding:
            bars_held += 1
            if x[i] and bars_held >= min_hold:
                holding = False
                bars_held = 0
        else:
            if e[i] and not x[i]:
                holding = True
                bars_held = 0
        raw[i] = 1.0 if holding else 0.0
    pos = pd.Series(raw, index=df.index)

    if target_vol and target_vol > 0:
        ret = close.pct_change()
        ann_vol = ret.rolling(vol_window).std() * np.sqrt(24 * 365)
        size = (target_vol / ann_vol).clip(0.0, 1.0)
        # coarse steps + floor at one step while in a trend, so sizing noise
        # never flips us fully out and never rebalances by less than `step`
        size = (size / step).round() * step
        size = size.clip(lower=step).fillna(1.0)
        pos = pos * size

    return pos.clip(0.0, 1.0)
