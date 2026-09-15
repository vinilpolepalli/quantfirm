"""basis_crowding — perp basis / funding as a positioning (crowding) gauge for
the long book.

HYPOTHESIS. The vol-targeted long book (``vol_target_hold``) can be improved
by reading Binance's USDT-perp basis (premium index) and funding as a gauge of
retail long crowding: when the 30-day basis is high relative to its own
trailing year, leveraged longs are crowded and the forward return
distribution is left-skewed (crash risk), so we cut BTC/ETH weight; when the
7-day basis has collapsed inside an uptrend (a positioning washout without a
trend break), we add. Rising funding (crowding building) is a third, faster
gauge. Gold and silver have no basis series on the venue or in this repo, so
they keep the plain vol-targeted long weight throughout — the family only
modifies BTC and ETH.

MECHANISM. Perp funding is what trend-chasing retail leverage pays to be
long; a high basis is therefore a positioning measure, not a valuation one.
Crowded longs are liquidated into declines (cascade), which is why high carry
predicts crashes rather than mean drift. The gate acts on the LEVEL relative
to a trailing distribution because the basis has compressed structurally
(2020-21 annualized funding 18-38%, 2022-25 4-13%): an absolute threshold
would never fire after 2021.

EXTERNAL EVIDENCE.
  * Schmeling, Schrimpf, Todorov, "Crypto carry", BIS Working Paper 1087
    (2023): crypto carry averaged >10%/yr, spikes are driven by trend-chasing
    retail leverage, and high carry predicts subsequent price crashes.
  * CF Benchmarks research note: perp basis correlates ~0.5 with momentum
    z-scores — it is partly a momentum proxy. Measured here before any
    backtest: corr(30d premium, 90d momentum z) = 0.40 BTC / 0.55 ETH on the
    dev window, and P(uptrend | crowded at q90) = 1.00 BTC / 0.99 ETH. So the
    de-risk gate fires ONLY inside uptrends, i.e. it does something trend
    cannot (it cuts the most euphoric ~21% of uptrend days); the family adds
    beyond trend only if that cut is paid for by what follows. 6 crowded
    episodes (~40 days each) in the dev window — a small sample, stated.

DATA AND CAUSALITY. ``load_aux("premium_btc"/"premium_eth")`` daily close of
the Binance premium index (fraction, 2020-01→) and ``load_funding_proxy``
(Binance 8h funding, summed per UTC day, RAW — this is the offshore crowding
gauge, not Kalshi's zeroed rate). Both are stamped by UTC day t and are moved
to t+1 (``index + 1 day``) BEFORE any use, then reindexed to the price
calendar and forward-filled over the 8 missing premium days. Everything else
is trailing windows: rolling means, rolling quantiles (min_periods = half the
window), a rolling SMA of close. Rows before the aux history (or before a
window fills) carry signal 1.0 = the benchmark weight.

BRIEF DEVIATION (decided before the first run, from the data's shape, not
from returns): the brief's capitulation trigger "7-day mean premium < 0" is
the NORMAL state on Binance (the premium close is negative on 69% of BTC
days / 63% of ETH days; median -3.7 bps), so it is registered instead as
"7-day mean premium below its trailing 1-year 10th percentile" (mirror of
the q90 crowding gate; ~11-13% of days, ~3.5% jointly with the uptrend).

REGISTERED GRID (6 configurations, one walk-forward, selection by IS Sharpe):
  variant                      | rule for BTC and ETH (gold/silver always 1.0)
  derisk_q90_flat              | 30d mean premium > trailing-365d q90 → weight 0.0
  derisk_q90_half              | same gate → weight 0.5
  derisk_q80_half              | 30d mean premium > trailing-365d q80 → weight 0.5
  capitulation                 | 7d mean premium < trailing-365d q10 AND close > SMA100 → 1.5
  funding_mom_half             | 30d mean daily funding rose over 14 days → weight 0.5
  derisk_q90_half+capitulation | both; when both fire the de-risk (risk-off) wins
Fixed: target_vol 0.12, gauge_window 30, pct_window 365, capit_window 7,
trend_window 100, chg_window 14, capit_pct 0.10, capit_boost 1.5, fmom_to
0.5. The 1.5 boost deliberately runs that asset above the reference book
("add to longs up to the cap"); venue caps still apply through vol_target.
Evaluation as instructed: walkforward --start 2020-06-01 --warmup 300 --folds 5;
backtest/robust --start 2020-06-01 (basis data begin 2020-01).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align, load_aux, load_funding_proxy
from ..strategies import register, vol_target

BASIS_ASSETS = ("btc", "eth")
_RISING_TOL = 1e-9          # numerical guard on the funding change, not a deadband

# name → which gauges are on and the de-risk gate's percentile / cut weight
VARIANTS: dict[str, dict] = {
    "derisk_q90_flat": {"derisk": True, "derisk_pct": 0.90, "derisk_to": 0.0, "capitulation": False, "funding_mom": False},
    "derisk_q90_half": {"derisk": True, "derisk_pct": 0.90, "derisk_to": 0.5, "capitulation": False, "funding_mom": False},
    "derisk_q80_half": {"derisk": True, "derisk_pct": 0.80, "derisk_to": 0.5, "capitulation": False, "funding_mom": False},
    "capitulation": {"derisk": False, "capitulation": True, "funding_mom": False},
    "funding_mom_half": {"derisk": False, "capitulation": False, "funding_mom": True},
    "derisk_q90_half+capitulation": {"derisk": True, "derisk_pct": 0.90, "derisk_to": 0.5, "capitulation": True, "funding_mom": False},
}

_CACHE: dict[str, pd.Series] = {}


def _premium(asset: str) -> pd.Series:
    """Daily close of the Binance premium index, stamped day t, moved to t+1."""
    key = f"premium_{asset}"
    if key not in _CACHE:
        s = load_aux(key)["close"].astype(float)
        s.index = s.index + pd.Timedelta(days=1)
        _CACHE[key] = s
    return _CACHE[key]


def _funding_daily(asset: str) -> pd.Series:
    """Raw Binance funding summed per UTC day (longs pay when positive), moved to t+1."""
    key = f"funding_{asset}"
    if key not in _CACHE:
        f = load_funding_proxy(asset)
        if f is None:
            raise FileNotFoundError(f"no Binance funding proxy for {asset}")
        d = f.groupby(f.index.normalize()).sum()
        d.index = d.index + pd.Timedelta(days=1)
        _CACHE[key] = d
    return _CACHE[key]


@register("basis_crowding")
def basis_crowding(panel, target_vol: float = 0.12, variant: str = "derisk_q90_half",
                   gauge_window: int = 30, pct_window: int = 365, capit_window: int = 7,
                   trend_window: int = 100, chg_window: int = 14, capit_pct: float = 0.10,
                   capit_boost: float = 1.5, fmom_to: float = 0.5,
                   derisk_pct: float | None = None, derisk_to: float | None = None, **kw) -> pd.DataFrame:
    """Vol-targeted long book with BTC/ETH weights tilted by basis crowding.

    ``variant`` selects the registered rule set (see module docstring);
    ``derisk_pct`` / ``derisk_to`` override the variant's gate when given.
    Signal 1.0 everywhere the gauges are unavailable → identical to
    ``vol_target_hold``.
    """
    v = VARIANTS[variant]
    d_pct = v.get("derisk_pct") if derisk_pct is None else derisk_pct
    d_to = v.get("derisk_to") if derisk_to is None else derisk_to
    closes = align(panel)
    idx = closes.index
    sig = pd.DataFrame(1.0, index=idx, columns=closes.columns)
    minp = max(int(pct_window) // 2, 30)
    for a in closes.columns:
        if a not in BASIS_ASSETS:
            continue                                   # metals: plain vol-targeted long
        s = pd.Series(1.0, index=idx)
        prem = _premium(a).reindex(idx).ffill()
        crowded = pd.Series(False, index=idx)
        if v["derisk"]:
            g = prem.rolling(gauge_window).mean()
            hi = g.rolling(pct_window, min_periods=minp).quantile(d_pct)
            crowded = (g > hi).fillna(False)          # NaN gauge or threshold → not crowded
            s = s.where(~crowded, float(d_to))
        if v["capitulation"]:
            g7 = prem.rolling(capit_window).mean()
            lo = g7.rolling(pct_window, min_periods=minp).quantile(capit_pct)
            up = closes[a] > closes[a].rolling(trend_window).mean()
            capit = ((g7 < lo) & up).fillna(False) & ~crowded   # risk-off wins a tie
            s = s.where(~capit, float(capit_boost))
        if v["funding_mom"]:
            f = _funding_daily(a).reindex(idx).ffill()
            f30 = f.rolling(gauge_window).mean()
            rising = ((f30 - f30.shift(chg_window)) > _RISING_TOL).fillna(False)
            s = s.where(~rising, np.minimum(s, float(fmom_to)))
        sig[a] = s
    return vol_target(sig, panel, target_vol, **kw)


TRIALS = {
    "basis_crowding": {
        "params": {"target_vol": 0.12},
        "grid": {"variant": ["derisk_q90_flat", "derisk_q90_half", "derisk_q80_half",
                             "capitulation", "funding_mom_half", "derisk_q90_half+capitulation"]},
    }
}
