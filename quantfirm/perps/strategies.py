"""Pre-registered perps strategies: (panel, **params) -> target weights.

A strategy maps a dict of daily OHLCV frames (one per asset) to a DataFrame of
TARGET NOTIONAL WEIGHTS — signed fraction of account equity per asset, decided
at the close of day t. The backtester executes them at the NEXT day's open,
holds contracts (not weights) between rebalances, and charges fees, funding,
interest and liquidation. Nothing here knows about fills.

Every function is causal by construction (rolling windows and shifts only);
``tests/test_perps.py`` checks that appending future bars does not change
past rows. Parameters are frozen here; sweeping them is a registered trial
(the tournament counts every grid point for the deflated Sharpe).

Economic priors (external to this sample):
  * Time-series momentum works across asset classes for a century
    (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017) and in crypto at
    1–4 week horizons (Liu-Tsyvinski 2021). Its edge is a handful of trades a
    year, which is what a 12 bps taker fee needs.
  * Vol targeting lowers drawdowns and raises Sharpe where vol is persistent
    (Moreira-Muir 2017); crypto vol is very persistent.
  * Funding carry is not a strategy on Kalshi: rates below 0.01%/interval
    (≈11%/yr) round to zero and 55–97% of historical intervals ARE zero.
  * Short-horizon mean reversion / market making are excluded by arithmetic:
    the tier-0 round trip is 24–29 bps of notional.
Controls (buy_hold, vol_target_hold, flat, coin_flip) set the bar: a
candidate that cannot beat vol-scaled long-only out of sample has no edge.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import align
from .specs import SPECS, max_weight_for_distance

REGISTRY: dict = {}
BARS_PER_YEAR = {"crypto": 365, "metals": 252}


def register(name: str, control: bool = False):
    def deco(fn):
        REGISTRY[name] = fn
        fn.strategy_name = name
        fn.is_control = control
        return fn
    return deco


# ----------------------------------------------------------------- helpers
def asset_vol(panel: dict[str, pd.DataFrame], window: int = 30,
              floor: float = 0.05) -> pd.DataFrame:
    """Annualised realised vol per asset on its NATIVE bars (metals do not
    trade weekends, so their vol must not be diluted by zero returns),
    reindexed to the union calendar and forward-filled."""
    idx = align(panel).index
    out = {}
    for a, d in panel.items():
        bpy = BARS_PER_YEAR[SPECS[a].asset_class] if a in SPECS else 365
        r = d["close"].pct_change()
        v = r.rolling(window).std() * np.sqrt(bpy)
        out[a] = v.reindex(idx).ffill().clip(lower=floor)
    return pd.DataFrame(out)


def portfolio_vol(weights: pd.DataFrame, returns: pd.DataFrame, window: int = 60) -> pd.Series:
    """Ex-ante annualised portfolio vol using the trailing covariance (causal)."""
    cols = list(weights.columns)
    R = returns[cols].fillna(0.0).to_numpy()
    W = weights[cols].fillna(0.0).to_numpy()
    n = len(W)
    out = np.full(n, np.nan)
    for t in range(window, n):
        block = R[t - window + 1:t + 1]
        cov = np.cov(block, rowvar=False)
        if np.ndim(cov) == 0:
            cov = np.array([[cov]])
        w = W[t]
        out[t] = np.sqrt(max(float(w @ cov @ w), 0.0) * 365)
    return pd.Series(out, index=weights.index)


def cap_weights(w: pd.DataFrame, max_gross: float = 1.5, max_asset: float = 0.75,
                min_liq_distance: float = 0.35) -> pd.DataFrame:
    """Per-asset cap (incl. the liquidation-distance cap from the venue's
    maintenance rate) then a proportional gross-leverage cap."""
    w = w.copy()
    for a in w.columns:
        m = SPECS[a].maint_rate if a in SPECS else 0.35
        cap_long = min(max_asset, max_weight_for_distance(min_liq_distance, m, short=False))
        cap_short = min(max_asset, max_weight_for_distance(min_liq_distance, m, short=True))
        w[a] = w[a].clip(lower=-cap_short, upper=cap_long)
    gross = w.abs().sum(axis=1)
    scale = (max_gross / gross).where(gross > max_gross, 1.0).fillna(1.0)
    return w.mul(scale, axis=0).fillna(0.0)


def vol_target(signal: pd.DataFrame, panel: dict[str, pd.DataFrame], target_vol: float,
               vol_window: int = 60, cov_window: int = 120, max_gross: float = 1.5,
               max_asset: float = 0.75, min_liq_distance: float = 0.35,
               max_scale: float = 3.0, step: float = 0.05) -> pd.DataFrame:
    """Signal in [-1, 1] per asset → notional weights.

    1. equal risk per asset: raw_i = signal_i / σ_i / N
    2. scale the book so a REFERENCE fully-long book (all signals = 1) has
       ex-ante vol ``target_vol`` under the trailing covariance. Scaling off
       the reference rather than the live signal means a weak or mixed signal
       yields a SMALLER book, never a levered-up one; a mixed long/short book
       then runs below target vol, which is the conservative side.
    3. round to ``step`` of equity so vol drift alone does not trade, then
       apply the venue/risk caps.
    Everything is causal (rolling windows only).
    """
    closes = align(panel)
    rets = closes.pct_change()
    vol = asset_vol(panel, vol_window)
    n = len(signal.columns)
    ref = (1.0 / vol) / n
    pv_ref = portfolio_vol(ref, rets, cov_window)
    k = (target_vol / pv_ref).clip(upper=max_scale)
    raw = signal.div(vol).div(n).fillna(0.0)
    w = raw.mul(k, axis=0).fillna(0.0)
    if step and step > 0:
        w = (w / step).round() * step
    return cap_weights(w, max_gross, max_asset, min_liq_distance)


def _tsmom_signal(closes: pd.DataFrame, lookbacks=(21, 63, 126, 252)) -> pd.DataFrame:
    sig = sum(np.sign(closes / closes.shift(lb) - 1.0) for lb in lookbacks) / len(lookbacks)
    return sig.fillna(0.0)


def _ma_signal(closes: pd.DataFrame, pairs=((10, 50), (20, 100), (50, 200)),
               band: float = 0.0) -> pd.DataFrame:
    out = 0
    for f, s in pairs:
        gap = closes.rolling(f).mean() / closes.rolling(s).mean() - 1.0
        out = out + np.sign(gap.where(gap.abs() > band, 0.0))
    return (out / len(pairs)).fillna(0.0)


def _breakout_signal(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex,
                     entry: int = 55, exit_: int = 20) -> pd.DataFrame:
    """Turtle-style Donchian: enter on an ``entry``-day high/low breakout,
    exit when price crosses the ``exit_``-day channel the other way."""
    cols = {}
    for a, d in panel.items():
        hi = d["high"].rolling(entry).max().shift(1)
        lo = d["low"].rolling(entry).min().shift(1)
        xhi = d["high"].rolling(exit_).max().shift(1)
        xlo = d["low"].rolling(exit_).min().shift(1)
        c = d["close"].to_numpy()
        h, l, xh, xl = hi.to_numpy(), lo.to_numpy(), xhi.to_numpy(), xlo.to_numpy()
        pos = np.zeros(len(c))
        p = 0.0
        for i in range(len(c)):
            if not np.isnan(h[i]) and c[i] > h[i]:
                p = 1.0
            elif not np.isnan(l[i]) and c[i] < l[i]:
                p = -1.0
            elif p > 0 and not np.isnan(xl[i]) and c[i] < xl[i]:
                p = 0.0
            elif p < 0 and not np.isnan(xh[i]) and c[i] > xh[i]:
                p = 0.0
            pos[i] = p
        cols[a] = pd.Series(pos, index=d.index).reindex(idx).ffill().fillna(0.0)
    return pd.DataFrame(cols)


def _finish(sig: pd.DataFrame, panel, target_vol, long_only=False, **kw) -> pd.DataFrame:
    if long_only:
        sig = sig.clip(lower=0.0)
    return vol_target(sig, panel, target_vol, **kw)


# -------------------------------------------------------------- candidates
@register("tsmom")
def tsmom(panel, lookbacks=(21, 63, 126, 252), target_vol: float = 0.12,
          long_only: bool = False, **kw) -> pd.DataFrame:
    """Multi-horizon time-series momentum (average sign of 1/3/6/12-month
    returns), equal risk per asset, vol-targeted."""
    closes = align(panel)
    return _finish(_tsmom_signal(closes, lookbacks), panel, target_vol, long_only, **kw)


@register("ma_trend")
def ma_trend(panel, pairs=((10, 50), (20, 100), (50, 200)), band: float = 0.0,
             target_vol: float = 0.12, long_only: bool = False, **kw) -> pd.DataFrame:
    """Three moving-average crossovers averaged (Baz et al. 2015 style)."""
    closes = align(panel)
    return _finish(_ma_signal(closes, pairs, band), panel, target_vol, long_only, **kw)


@register("breakout")
def breakout(panel, entry: int = 55, exit_: int = 20, target_vol: float = 0.12,
             long_only: bool = False, **kw) -> pd.DataFrame:
    closes = align(panel)
    return _finish(_breakout_signal(panel, closes.index, entry, exit_), panel,
                   target_vol, long_only, **kw)


@register("trend_ensemble")
def trend_ensemble(panel, target_vol: float = 0.12, long_only: bool = False,
                   lookbacks=(21, 63, 126, 252), pairs=((10, 50), (20, 100), (50, 200)),
                   entry: int = 55, exit_: int = 20, **kw) -> pd.DataFrame:
    """Average of the three trend signals. The primary candidate: three weakly
    correlated trend definitions trade less often than any one of them."""
    closes = align(panel)
    sig = (_tsmom_signal(closes, lookbacks) + _ma_signal(closes, pairs)
           + _breakout_signal(panel, closes.index, entry, exit_)) / 3.0
    return _finish(sig, panel, target_vol, long_only, **kw)


@register("trend_long_only")
def trend_long_only(panel, target_vol: float = 0.12, **kw) -> pd.DataFrame:
    """Ensemble with shorts set to flat. Crypto shorts have paid negative
    drift historically; this asks whether the short side earns its fees."""
    return trend_ensemble(panel, target_vol=target_vol, long_only=True, **kw)


@register("trend_conservative")
def trend_conservative(panel, target_vol: float = 0.08, **kw) -> pd.DataFrame:
    """Ensemble at 8% vol, gross ≤ 1.0. The 'not too risky' rung."""
    kw.setdefault("max_gross", 1.0)
    kw.setdefault("max_asset", 0.5)
    return trend_ensemble(panel, target_vol=target_vol, **kw)


@register("carry_tilt")
def carry_tilt(panel, target_vol: float = 0.12, funding: dict | None = None,
               pay_limit_daily: float = 0.0006, **kw) -> pd.DataFrame:
    """Ensemble, but a position that would PAY funding above
    ``pay_limit_daily`` (≈22%/yr) is cut to zero for that day. On Kalshi the
    rate is ~zero, so this collapses to the ensemble — registered to show it.
    ``funding``: {asset: daily funding Series} (positive = longs pay)."""
    w = trend_ensemble(panel, target_vol=target_vol, **kw)
    if not funding:
        return w
    for a, f in funding.items():
        if a not in w.columns:
            continue
        f = f.reindex(w.index).fillna(0.0)
        pays = ((w[a] > 0) & (f > pay_limit_daily)) | ((w[a] < 0) & (f < -pay_limit_daily))
        w.loc[pays, a] = 0.0
    return w


@register("gold_silver_ratio")
def gold_silver_ratio(panel, window: int = 120, z_entry: float = 2.0, z_exit: float = 0.5,
                      target_vol: float = 0.08, **kw) -> pd.DataFrame:
    """Long gold / short silver when the ratio's z-score is very low, and the
    reverse when very high. A popular idea with weak evidence; registered so
    it is counted, expected to lose to the controls."""
    closes = align(panel)
    if "gold" not in closes or "silver" not in closes:
        return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    lr = np.log(closes["gold"] / closes["silver"])
    z = (lr - lr.rolling(window).mean()) / lr.rolling(window).std()
    zz = z.to_numpy()
    pos = np.zeros(len(zz))
    p = 0.0
    for i in range(len(zz)):
        if np.isnan(zz[i]):
            pos[i] = p
            continue
        if p == 0.0:
            if zz[i] > z_entry:
                p = -1.0   # ratio rich: short gold, long silver
            elif zz[i] < -z_entry:
                p = 1.0
        elif abs(zz[i]) < z_exit:
            p = 0.0
        pos[i] = p
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig["gold"] = pos
    sig["silver"] = -pos
    return _finish(sig, panel, target_vol, **kw)


# ---------------------------------------------------------------- controls
@register("buy_hold", control=True)
def buy_hold(panel, weight: float = 1.0, **_) -> pd.DataFrame:
    """Equal-weight long, gross = ``weight``. Unlevered beta."""
    closes = align(panel)
    n = len(closes.columns)
    return pd.DataFrame(weight / n, index=closes.index, columns=closes.columns)


@register("vol_target_hold", control=True)
def vol_target_hold(panel, target_vol: float = 0.12, **kw) -> pd.DataFrame:
    """Long-only, equal risk, vol-targeted. THE benchmark: a trend strategy
    that cannot beat this out of sample is just levered beta with fees."""
    closes = align(panel)
    sig = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
    return vol_target(sig, panel, target_vol, **kw)


@register("flat", control=True)
def flat(panel, **_) -> pd.DataFrame:
    """Never trades. Earns only the collateral interest."""
    closes = align(panel)
    return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)


@register("coin_flip", control=True)
def coin_flip(panel, target_vol: float = 0.12, hold: int = 21, seed: int = 7, **kw) -> pd.DataFrame:
    """Random ±1 signals held ``hold`` days, same sizing machinery. If the
    candidates do not clearly beat this, the sizing is the 'edge'."""
    closes = align(panel)
    rng = np.random.default_rng(seed)
    n_blocks = len(closes) // hold + 1
    sig = pd.DataFrame(
        np.repeat(rng.choice([-1.0, 1.0], size=(n_blocks, len(closes.columns))), hold, axis=0)[:len(closes)],
        index=closes.index, columns=closes.columns)
    return vol_target(sig, panel, target_vol, **kw)


def load_all() -> dict:
    """The core registry plus every module in quantfirm/perps/families/."""
    from . import families
    families.load_all()
    return REGISTRY


def family_trials() -> dict:
    from . import families
    return families.load_all()
