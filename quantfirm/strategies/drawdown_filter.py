"""Crash-avoidance overlay: long by default, flat only when a crash fires.

Thesis: BTC's long-run edge is being long, but the equity-curve killers are a
handful of deep crashes (COVID Mar-2020, May-2021, the 2022 bear legs, FTX).
We hold 1.0 except when close falls more than `exit_depth` below its trailing
`high_window`-bar high — a genuine crash, not a routine bull-market dip.

Re-entry is deliberately hysteretic and slow (turnover is the enemy at 0.93%
per side): after a minimum flat period we re-enter only when the drawdown has
healed to within `reenter_depth` of the trailing high AND the trailing
`reenter_mom_lb` return is non-negative — so we never buy a falling knife
just because the rolling max rolled off, and bear-market rallies (which stall
below the trailing high with negative monthly momentum) don't chop us.

A secondary momentum+vol-spike trigger (fast panic legs the depth trigger can
lag) is retained in the code but DISABLED by default (`mom_exit=-9.9`): in
dev walk-forward it only added turnover without improving out-of-sample
Sharpe.

Dev walk-forward (BTC, rh_market, 5 folds): oos_sharpe 1.32 vs buy-and-hold
1.12, annual turnover ~1.9, max drawdown -0.66 vs -0.77. ETH same params:
1.10 vs 0.96, max drawdown -0.64 vs -0.81.

All windows are trailing/rolling; row t uses data <= t only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register


@register("drawdown_filter")
def drawdown_filter(
    df: pd.DataFrame,
    high_window: int = 24 * 35,     # trailing-high window for drawdown depth
    exit_depth: float = 0.30,       # go flat when dd below trailing high exceeds this
    reenter_depth: float = 0.05,    # re-enter only when dd has healed to within this
    mom_lookback: int = 24 * 7,     # trailing-return window for the momentum trigger
    mom_exit: float = -9.9,         # momentum trigger threshold (disabled by default)
    mom_reenter: float = 0.0,       # require trailing momentum >= this to re-enter
    reenter_mom_lb: int = 24 * 30,  # lookback for the re-entry momentum confirmation
    vol_window: int = 24 * 7,       # short-horizon realised vol
    vol_ref_window: int = 24 * 90,  # long rolling median as the vol baseline
    vol_mult: float = 1.6,          # spike = short vol > mult x baseline
    min_hold: int = 24 * 10,        # minimum bars to stay flat after an exit
) -> pd.Series:
    close = df["close"]
    n = len(close)

    roll_max = close.rolling(high_window, min_periods=1).max()
    dd = (close / roll_max - 1.0).to_numpy()

    mom = close.pct_change(mom_lookback).to_numpy()
    mom_re = close.pct_change(reenter_mom_lb).to_numpy()

    ret = close.pct_change()
    vol = ret.rolling(vol_window).std()
    vol_ref = vol.rolling(vol_ref_window, min_periods=vol_window).median()
    spike = (vol > vol_mult * vol_ref).to_numpy()

    crash = (dd <= -exit_depth) | ((mom <= mom_exit) & spike)
    healed = (dd >= -reenter_depth) & (mom_re >= mom_reenter)

    pos = np.ones(n)
    holding = 1.0
    bars_flat = 0
    for i in range(n):
        if holding > 0.5:
            if crash[i]:
                holding = 0.0
                bars_flat = 0
        else:
            bars_flat += 1
            if bars_flat >= min_hold and healed[i] and not crash[i]:
                holding = 1.0
        pos[i] = holding
    return pd.Series(pos, index=df.index)
