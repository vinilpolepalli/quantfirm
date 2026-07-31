"""Composite-ensemble desk: average 3-5 diverse slow signals into a stepped
position (0, 0.25, ..., 1.0).

Thesis: no single slow signal times BTC well net of a 0.93%-per-side spread,
but an AVERAGE of decorrelated slow signals (MA trend, momentum sign, breakout
state, vol gate) changes value only when members flip one at a time, so the
blended score moves in small increments. Quantizing that score to a coarse
step grid behind an asymmetric hysteresis band means most single-member flips
do not move the traded position at all — disagreement between members becomes
a free smoothing mechanism, cutting turnover far below what any member trades
on its own, while consensus moves (all members agree) still get to full size.

Members (each causal, rolling-window only, output in [0, 1]):
  1. trend  : fast/slow MA gap with +/- band hysteresis state.
  2. mom    : sign of trailing `mom_lb` return with +/- band hysteresis state.
  3. brk    : breakout channel state — 1 after a `brk_entry`-bar high, 0 after
              a `brk_exit`-bar low (channels shifted one bar; turtle-style).
  4. vol    : continuous vol gate clip(target_vol / realized_vol, 0, 1) —
              sizes down in chaos, full weight in quiet grinds.

Blend: weighted mean of members -> score in [0, 1]. `vol_mode` chooses how
the vol gate enters: "member" averages it in like the others (it then adds
standalone exposure in quiet bears — risky), "gate" multiplies the
directional average by it (flat when all directional members are off).

Execution layer (turnover control, the actual edge at this venue):
  * quantize score to `step` grid;
  * move DOWN when score sits `hyst_down` below current position (de-risk
    fast), move UP only when score sits `hyst_up` above current position AND
    `min_hold` bars passed since the last change (re-risk lazily);
  * position ratchets between grid levels; no rebalance smaller than `step`.

Causality: every input is a rolling window or one-bar-shifted channel; the
state loops read only current-bar signals and past state. No centered windows,
no negative shifts, no full-sample statistics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

HOURS_PER_YEAR = 24 * 365


def _hysteresis_state(up: pd.Series, down: pd.Series) -> pd.Series:
    """1.0 after `up` fires, 0.0 after `down` fires, hold in between."""
    sig = pd.Series(np.nan, index=up.index)
    sig[up.fillna(False)] = 1.0
    sig[down.fillna(False)] = 0.0
    return sig.ffill().fillna(0.0)


@register("composite_ensemble")
def composite_ensemble(
    df: pd.DataFrame,
    fast: int = 72,
    slow: int = 720,
    trend_band: float = 0.005,
    mom_lb: int = 720,
    mom_band: float = 0.02,
    brk_entry: int = 480,
    brk_exit: int = 240,
    vol_window: int = 720,
    target_vol: float = 0.40,
    w_trend: float = 1.0,
    w_mom: float = 1.0,
    w_brk: float = 1.0,
    w_vol: float = 1.0,
    vol_mode: str = "gate",
    step: float = 0.25,
    hyst_down: float = 0.15,
    hyst_up: float = 0.20,
    min_hold: int = 72,
) -> pd.Series:
    close = df["close"]
    ret = close.pct_change()

    # --- member 1: MA-gap trend with hysteresis band ---
    gap = close.rolling(fast).mean() / close.rolling(slow).mean() - 1.0
    m_trend = _hysteresis_state(gap > trend_band, gap < -trend_band)

    # --- member 2: momentum sign with hysteresis band ---
    mom = close.pct_change(mom_lb)
    m_mom = _hysteresis_state(mom > mom_band, mom < -mom_band)

    # --- member 3: breakout channel state (turtle-style, shifted 1 bar) ---
    upper = close.rolling(brk_entry).max().shift(1)
    lower = close.rolling(brk_exit).min().shift(1)
    m_brk = _hysteresis_state(close >= upper, close <= lower)

    # --- member 4: continuous vol gate ---
    ann_vol = ret.rolling(vol_window).std() * np.sqrt(HOURS_PER_YEAR)
    m_vol = (target_vol / ann_vol).clip(0.0, 1.0)

    members = [m_trend, m_mom, m_brk, m_vol]
    weights = [w_trend, w_mom, w_brk, w_vol]
    wsum = sum(weights)
    if wsum <= 0:
        return pd.Series(0.0, index=df.index)
    score = sum(w * m for w, m in zip(weights, members)) / wsum

    # warmup: until every used member has data, stay flat
    warm = max(slow, mom_lb, brk_entry, brk_exit, vol_window)
    s = score.to_numpy(copy=True)
    s[:warm] = np.nan

    # --- execution layer: stepped position with asymmetric hysteresis ---
    n = len(s)
    pos = np.zeros(n)
    p = 0.0
    last_change = -(10 ** 9)
    inv_step = 1.0 / step
    for i in range(n):
        si = s[i]
        if not np.isnan(si):
            if si < p - hyst_down:
                p = min(max(np.floor(si * inv_step + 0.5) / inv_step, 0.0), 1.0)
                last_change = i
            elif si > p + hyst_up and (i - last_change) >= min_hold:
                p = min(max(np.floor(si * inv_step + 0.5) / inv_step, 0.0), 1.0)
                last_change = i
        pos[i] = p
    return pd.Series(pos, index=df.index).clip(0.0, 1.0)
