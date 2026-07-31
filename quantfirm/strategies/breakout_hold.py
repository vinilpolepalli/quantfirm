"""Breakout-hold desk: Donchian-style breakout entries with an enforced
minimum holding period and a WIDE ATR trailing stop.

Thesis: at a 0.93%-per-side venue the classic turtle Donchian (entry channel +
opposite channel exit) churns itself to death (baseline donchian oos ~0.72).
The fix is not a better entry — it is refusing to leave. We enter on a long
channel breakout, then hold through noise: a position cannot be exited before
`min_hold` bars, and afterwards only when price falls `trail_mult` ATRs below
the high-water mark since entry (optionally also below a long Donchian floor).
Wide stop + hold floor => a handful of round trips per year, capturing the
bull legs and skipping the deep 2022-style bear, with cost drag in the noise.

Causality: rolling windows only, channel/ATR shifted one bar; the state
machine reads only current-bar signals and past state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


@register("breakout_hold")
def breakout_hold(
    df: pd.DataFrame,
    entry_len: int = 720,
    atr_len: int = 336,
    trail_mult: float = 18.0,
    min_hold: int = 240,
    exit_len: int = 480,
    cooldown: int = 168,
    size: float = 1.0,
) -> pd.Series:
    """Donchian breakout entry, minimum-hold floor, wide ATR trailing exit.

    Parameters
    ----------
    entry_len : breakout channel length in bars (hours). Enter when close
        makes a new `entry_len`-bar high (channel shifted 1 bar — causal).
    atr_len : ATR lookback for the trailing stop width.
    trail_mult : stop sits this many ATRs below the high-water mark of close
        since entry. Big values = wide stop = few trades.
    min_hold : bars a position must be held before ANY exit is allowed.
    exit_len : optional Donchian floor — if > 0, also exit when close breaks
        the prior `exit_len`-bar low (still gated by min_hold). 0 = off.
    cooldown : bars after an exit during which re-entry is blocked. 0 = off.
    size : position taken when long (coarse; single step in/out).
    """
    close = df["close"].to_numpy()
    upper = df["close"].rolling(entry_len).max().shift(1).to_numpy()
    atr = _atr(df, atr_len).to_numpy()
    if exit_len and exit_len > 0:
        floor = df["close"].rolling(exit_len).min().shift(1).to_numpy()
    else:
        floor = np.full(len(df), -np.inf)
    floor = np.where(np.isnan(floor), -np.inf, floor)

    n = len(df)
    pos = np.zeros(n)
    holding = False
    hwm = 0.0
    bars_held = 0
    last_exit = -(10 ** 9)

    for i in range(n):
        c = close[i]
        if holding:
            bars_held += 1
            if c > hwm:
                hwm = c
            a = atr[i]
            stop = hwm - trail_mult * a if not np.isnan(a) else -np.inf
            if bars_held >= min_hold and (c < stop or c < floor[i]):
                holding = False
                last_exit = i
        else:
            u = upper[i]
            if (not np.isnan(u)) and (not np.isnan(atr[i])) \
                    and c >= u and (i - last_exit) > cooldown:
                holding = True
                hwm = c
                bars_held = 0
        pos[i] = size if holding else 0.0

    return pd.Series(pos, index=df.index).clip(0.0, 1.0)
