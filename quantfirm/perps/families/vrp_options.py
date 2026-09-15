"""vrp_options — options-market information (Deribit DVOL) as a perps signal.

HYPOTHESIS AND MECHANISM (registered 2026-09-15, before the first backtest)
--------------------------------------------------------------------------
Kalshi perps have no options, but Deribit's DVOL index (30-day constant-
maturity implied volatility for BTC and ETH, daily since 2021-03-24, in vol
points) prices the same underlyings. The variance-risk premium
VRP = implied vol − realised vol is what option buyers pay to bear variance
risk. In equities a HIGH VRP predicts HIGH subsequent index returns
(Bollerslev, Tauchen & Zhou 2009, "Expected Stock Returns and Variance Risk
Premia", RFS 22(11) 4463–4492, https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787;
Bollerslev, Marrone, Xu & Zhou 2014, JFQA, international evidence): when
fear is priced richly the risk premium on the underlying is high too.
Alexander & Imeraj (2021, "The Bitcoin VIX and its Variance Risk Premium",
J. Alternative Investments 23(4) 84–109, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734)
build the VIX construction for bitcoin from Deribit options and document a
large, time-varying bitcoin VRP; its return-predictive SIGN in crypto is not
settled, so both signs are registered. DVOL methodology (30-day, variance-
swap style, two nearest expiries): https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/

Three mechanisms, all on the desk's long-only vol-targeted book:
  (a) VRP gate on the crypto legs: long only when the VRP z-score is above
      +k (`vrp_high`, the BTZ sign) or, as the mirror, below −k (`vrp_low`);
      `vrp_raw` is the parameter-free version (long iff DVOL > realised vol);
      `vrp_tilt` stays invested — full size when z > 0, half size otherwise.
  (b) "sell fear, buy the dip": full size when DVOL is in the top quintile of
      its trailing year AND price is above its 200-day mean, else half size
      (`fear_dip`).
  (c) forward-looking vol targeting: size the crypto legs on
      max(implied, realised) vol instead of realised vol alone (`iv_size`);
      implemented as signal = min(1, realised σ used by the sizer / DVOL).

Gold and silver have no DVOL and are held at the plain vol-targeted long
weight (signal = 1) in every mode, so any difference from `vol_target_hold`
comes from the crypto legs' options signal and nothing else. (The VIX is an
equity fear gauge, not a metals one; a VIX-gated gold book would test a
safe-haven story, which is a different family.) Wherever a mode's options
input is undefined — before 2021-03-24, or before the normalisation window
has its minimum history — the mode holds the benchmark book (signal = 1), so
the family is only informative from mid-2021 on. Evaluate it with
`--start 2021-04-01` and `walkforward --warmup 250 --folds 4`.

DATA AND CAUSALITY
------------------
DVOL close stamped day t (= close of UTC day t) is reindexed to the panel
calendar, forward-filled and SHIFTED BY ONE DAY before use, so the weight
decided at close t uses the print of t−1 (CAMPAIGN.md rule 4). Realised vol
is the panel's own trailing std of daily returns, annualised and ×100 to
DVOL's vol points. The VRP, its z-score and the DVOL quantile are computed
on same-stamped series and the finished feature is shifted by one day. The
200-day mean and the sizer's 60-day vol use closes ≤ t (panel data, as every
other strategy does). Rolling windows and shifts only; row t never sees t+1.

REGISTERED GRID — 6 configurations, `mode` is the only swept parameter
---------------------------------------------------------------------
TRIALS = {"vrp_options": {"params": {"target_vol": 0.12},
          "grid": {"mode": ["vrp_high", "vrp_low", "vrp_tilt", "vrp_raw", "fear_dip", "iv_size"]}}}
Fixed a priori: k = 0.5 (a half-sigma gate is on ~30% of days for any
z-score; a signal-only frequency check on the dev window — no returns —
gave 32%/29% for BTC/ETH), rv_window = 30 (DVOL's horizon), lookback = 252
with a 63-day minimum history, quantile = 0.8, trend_window = 200,
base = 0.5. Nothing is tuned after seeing a backtest; any later change is a
new trial and will be added here and to the report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align, load_aux
from ..specs import SPECS
from ..strategies import BARS_PER_YEAR, asset_vol, register, vol_target

DVOL_ASSETS = ("btc", "eth")
MODES = ("vrp_high", "vrp_low", "vrp_tilt", "vrp_raw", "fear_dip", "iv_size")


def _dvol(asset: str, idx: pd.DatetimeIndex) -> pd.Series:
    """DVOL close on the panel calendar (vol points), NaN where unavailable.
    Stamped day t; callers shift the finished feature by one day."""
    try:
        s = load_aux(f"dvol_{asset}")["close"]
    except (FileNotFoundError, KeyError):
        return pd.Series(np.nan, index=idx)
    return s.reindex(idx).ffill()


def _realised_vol_points(panel, asset: str, idx: pd.DatetimeIndex, window: int) -> pd.Series:
    """Trailing realised vol on the asset's native bars, annualised, in vol points."""
    bpy = BARS_PER_YEAR[SPECS[asset].asset_class] if asset in SPECS else 365
    r = panel[asset]["close"].pct_change()
    return (r.rolling(window).std() * np.sqrt(bpy) * 100.0).reindex(idx).ffill()


def vrp_signal(panel, mode: str = "vrp_high", k: float = 0.5, rv_window: int = 30,
               lookback: int = 252, quantile: float = 0.8, trend_window: int = 200,
               base: float = 0.5, vol_window: int = 60) -> pd.DataFrame:
    """Signal in [0, 1] per asset. Metals = 1 always; crypto per ``mode``;
    1 (benchmark) wherever the options input is undefined."""
    if mode not in MODES:
        raise ValueError(f"vrp_options: unknown mode {mode!r}; expected one of {MODES}")
    closes = align(panel)
    idx = closes.index
    sig = pd.DataFrame(1.0, index=idx, columns=closes.columns)
    min_hist = max(int(lookback) // 4, 20)
    sizer_vol = asset_vol(panel, vol_window) if mode == "iv_size" else None
    for a in DVOL_ASSETS:
        if a not in sig.columns:
            continue
        iv = _dvol(a, idx)                                        # stamped t
        if mode == "iv_size":
            ratio = sizer_vol[a] / (iv.shift(1) / 100.0)          # realised σ (sizer) / implied σ (t−1)
            ratio = ratio.replace([np.inf, -np.inf], np.nan)
            rule, defined = ratio.clip(lower=0.0, upper=1.0), ratio.notna()
        elif mode == "fear_dip":
            q = iv.rolling(lookback, min_periods=min_hist).quantile(quantile)
            fear = (iv >= q).astype(float).where(q.notna()).shift(1)
            ma = closes[a].rolling(trend_window).mean()
            up = closes[a] > ma
            rule = pd.Series(np.where((fear == 1.0) & up, 1.0, base), index=idx)
            defined = fear.notna() & ma.notna()
        else:
            rv = _realised_vol_points(panel, a, idx, rv_window)   # stamped t
            vrp = iv - rv                                         # stamped t
            if mode == "vrp_raw":
                feat = vrp.shift(1)
                rule = (feat > 0).astype(float)
            else:
                mu = vrp.rolling(lookback, min_periods=min_hist).mean()
                sd = vrp.rolling(lookback, min_periods=min_hist).std()
                feat = ((vrp - mu) / sd).replace([np.inf, -np.inf], np.nan).shift(1)
                if mode == "vrp_high":
                    rule = (feat > k).astype(float)
                elif mode == "vrp_low":
                    rule = (feat < -k).astype(float)
                else:  # vrp_tilt
                    rule = pd.Series(np.where(feat > 0, 1.0, base), index=idx)
            defined = feat.notna()
        sig[a] = pd.Series(rule, index=idx).where(defined, 1.0).astype(float)
    return sig


@register("vrp_options")
def vrp_options(panel, target_vol: float = 0.12, mode: str = "vrp_high", k: float = 0.5,
                rv_window: int = 30, lookback: int = 252, quantile: float = 0.8,
                trend_window: int = 200, base: float = 0.5, **kw) -> pd.DataFrame:
    """Options-market (DVOL) signal on the crypto legs of the vol-targeted long
    book; see the module docstring for the registered hypothesis and grid."""
    sig = vrp_signal(panel, mode, k, rv_window, lookback, quantile, trend_window, base,
                     vol_window=kw.get("vol_window", 60))
    return vol_target(sig, panel, target_vol, **kw)


TRIALS = {
    "vrp_options": {
        "params": {"target_vol": 0.12},
        "grid": {"mode": list(MODES)},
    }
}
