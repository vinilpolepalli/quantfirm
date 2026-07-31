"""Volatility-regime allocation (vol-regime desk).

Thesis: BTC crash losses are concentrated in high-realized-vol regimes, so
sizing long exposure inversely to realized vol dodges most drawdown cheaply
while keeping the low-vol grind-up beta. A vol-expansion gate (short vol
blowing out vs. base vol — a cheap vol-of-vol proxy) cuts exposure faster at
crash onset than a slow vol estimate alone.

Turnover control (0.93%/side venue): coarse position steps, an asymmetric
dead-band (de-risk on a small band immediately; re-risk only on a larger band
and after a minimum hold), so the position ratchets down fast in chaos and
climbs back lazily.

Causality: rolling windows only; the stateful dead-band loop only reads the
current bar's signal and past state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

HOURS_PER_YEAR = 24 * 365


@register("vol_regime")
def vol_regime(
    df: pd.DataFrame,
    vol_window: int = 24 * 30,
    target_ann_vol: float = 0.30,
    step: float = 0.25,
    band_down: float = 0.15,
    band_up: float = 0.25,
    vov_short: int = 24 * 5,
    vov_ratio: float = 2.0,
    vov_scale: float = 0.5,
    min_hold_up: int = 96,
) -> pd.Series:
    """Inverse-realized-vol sizing with vol-expansion gate and hysteresis.

    Parameters
    ----------
    vol_window : base realized-vol lookback (hours).
    target_ann_vol : annualised vol target; position = target/vol, capped at 1.
    step : coarse position grid (e.g. 0.25 -> quarters of bankroll).
    band_down : reduce exposure when raw target sits this far BELOW current
        position (small -> de-risk fast).
    band_up : increase exposure only when raw target sits this far ABOVE
        current position (larger -> re-risk slow, cuts whipsaw).
    vov_short : short vol lookback for the expansion gate (hours).
    vov_ratio : gate trips when short vol > vov_ratio * base vol.
    vov_scale : multiply raw target by this while the gate is tripped.
    min_hold_up : minimum bars since last position change before an INCREASE
        is allowed (decreases are always allowed immediately).
    """
    close = df["close"]
    ret = close.pct_change()

    base_vol = ret.rolling(vol_window).std() * np.sqrt(HOURS_PER_YEAR)
    raw = (target_ann_vol / base_vol).clip(0.0, 1.0)

    if vov_scale < 1.0:
        short_vol = ret.rolling(vov_short).std() * np.sqrt(HOURS_PER_YEAR)
        expanding = (short_vol > vov_ratio * base_vol).to_numpy()
    else:
        expanding = np.zeros(len(df), dtype=bool)

    r = raw.to_numpy(copy=True)
    r[expanding] *= vov_scale

    pos = np.zeros(len(r))
    p = 0.0
    last_change = -(10**9)
    inv_step = 1.0 / step
    for i in range(len(r)):
        ri = r[i]
        if not np.isnan(ri):
            target = np.round(ri * inv_step) / inv_step
            target = min(max(target, 0.0), 1.0)
            if target < p and (p - ri) >= band_down:
                p = target
                last_change = i
            elif target > p and (ri - p) >= band_up and (i - last_change) >= min_hold_up:
                p = target
                last_change = i
        pos[i] = p
    return pd.Series(pos, index=df.index)
