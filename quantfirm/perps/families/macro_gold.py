"""macro_gold — macro-conditioned gold and silver positioning.

Registered 2026-09-15 by the macro_gold designer BEFORE the first backtest.

HYPOTHESIS
----------
Gold has two dominant drivers: US real yields and the dollar. Gold is a
zero-coupon real asset, so falling real yields lower its opportunity cost;
it is priced in dollars, so a weaker dollar lifts its USD price. Both
drivers trend at the 1-3 month horizon (macro momentum), so a metals sleeve
that is long only while the drivers point the right way should keep most of
gold's up-months, skip part of its drawdowns and beat an always-long metals
sleeve at the same risk budget. Kalshi lists gold and silver perps at ~15x /
~8x leverage with funding that prints zero on most days, so a conditional
metals long is cheap to hold and cheap to switch off. Silver is treated as
a higher-beta gold (same drivers, same gate). Crypto (btc, eth) is held at
the plain vol-targeted long weight, so on the four-asset universe the family
IS the benchmark plus a macro-gated metals sleeve: any difference vs
``vol_target_hold`` is the sleeve. Gold's real price mean-reverts over
decades (Erb & Harvey), so no unconditional long premium is assumed; the
family bets on the conditional relationship only.

MECHANISM
---------
Inputs from ``load_aux("macro")``: DXY (dollar index) and TIP (iShares TIPS
ETF close; a rising TIP price = falling real yields, with a small upward
bias from inflation accrual that favours the long gate). Trend = the
``lookback``-trading-day percentage change of each series.
    dollar_down    = DXY_t / DXY_{t-lookback} - 1 < 0
    real_yield_down = TIP_t / TIP_{t-lookback} - 1 > 0
    vix_spike      = VIX_t > rolling ``vix_window``-day ``vix_pct`` quantile
Variants (one string parameter so the grid is exactly five points):
    "and"            gold, silver = 1 if dollar_down AND real_yield_down else 0
    "or"             gold, silver = 1 if dollar_down OR  real_yield_down else 0
    "and_vix_haven"  "and", plus gold forced to 1 while vix_spike (haven bid)
    "and_vix_cut"    "and", plus gold forced to 0 while vix_spike
                     (dash-for-cash: gold is sold with everything else)
    "score"          gold, silver = (-sign(DXY trend) + sign(TIP trend)) / 2:
                     long when both agree bullish, SHORT when both agree
                     bearish (dollar up AND real yields up), flat when mixed
btc, eth: signal 1 in every variant. Sizing: ``vol_target`` (equal risk per
asset, 12% target, venue caps). Because ``vol_target`` scales off the
all-ones reference book, a flat metals sleeve leaves the crypto weights
exactly equal to the benchmark's and never levers them up.

CAUSALITY
---------
Macro rows are stamped by UTC date and known at that day's close at the
earliest. Indicators are computed on the macro series' own trading-day index
(NaN holidays forward-filled), reindexed to the price calendar, forward-
filled over weekends, then SHIFTED BY ONE DAY before touching a weight: the
weight decided at close t uses macro data through t-1, and the backtester
fills it at t+1's open. Rolling windows only; the VIX threshold is a rolling
quantile, never a full-sample one. Rows before the macro history (2010) or
before the windows fill are NaN and mean a flat metals sleeve.

EXTERNAL EVIDENCE
-----------------
* Erb & Harvey (2013), "The Golden Dilemma", Financial Analysts Journal 69(4)
  (NBER WP 18706): the real price of gold mean-reverts; no reliable
  short-run inflation hedge; gold's long-run real return is about zero.
* O'Connor, Lucey, Batten & Baur (2015), "The financial economics of gold -
  a survey", Int. Review of Financial Analysis 41: the negative gold /
  real-yield relationship, strongest since the mid-2000s, and the negative
  gold / dollar relationship (Capie, Mills & Wood 2005, J. Int. Fin. Markets
  Inst. & Money 15; Pukthuanthong & Roll 2011, J. Banking & Finance 35).
* Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", J. Financial
  Economics 104(2): gold and silver futures show positive 12-month trend in
  the 1985-2009 sample.
* Brooks (2017), "A Half Century of Macro Momentum", AQR white paper: trends
  in macro fundamentals (growth, inflation, monetary policy, risk aversion)
  forecast returns across asset classes at 1-12 month horizons.
* Baur & Lucey (2010), "Is Gold a Hedge or a Safe Haven?", Financial Review
  45(2); Baur & McDermott (2010), J. Banking & Finance 34: gold is a short-
  lived safe haven (about 15 trading days) after equity shocks, but was sold
  with everything else in the worst liquidity events (Oct 2008, Mar 2020) -
  hence both signs of the VIX overlay are tested.

REGISTERED GRID (5 configurations) + 1 metals-only run = 6
-----------------------------------------------------------
    params = {"target_vol": 0.12, "lookback": 60, "vix_window": 504, "vix_pct": 0.9}
    grid   = {"variant": ["and", "or", "and_vix_haven", "and_vix_cut", "score"]}
    6th    = the selected variant with --universe gold,silver (metals-only
             contribution; the registry key is universe-blind, so it shares
             the selected variant's key)
Selection rule, fixed in advance: the fixed dev run (--yearly --stress), the
robust report and the metals-only run all use the variant the walk-forward
selects in its LAST fold (the tournament's own stress-test rule); ties are
broken toward "and", the a-priori primary. Control (not a trial):
``vol_target_hold`` at the same target on gold,silver, whose registry key
already exists, is run once so the metals-only sleeve has a comparator.
Anything else run after seeing results is a new trial and will be declared.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align, load_aux
from ..strategies import register, vol_target

METALS = ("gold", "silver")

# variant -> (how the two macro gates combine, sign of the VIX overlay on gold)
VARIANTS: dict[str, tuple[str, int]] = {
    "and": ("and", 0),
    "or": ("or", 0),
    "and_vix_haven": ("and", +1),
    "and_vix_cut": ("and", -1),
    "score": ("score", 0),
}


def _macro_indicators(idx: pd.DatetimeIndex, lookback: int, vix_window: int,
                      vix_pct: float) -> pd.DataFrame:
    """DXY trend, TIP trend and VIX-spike flag on ``idx``, lagged one day.

    Everything is computed on the macro series' own trading-day index, then
    reindexed to the price calendar, forward-filled over non-trading days and
    shifted by one day, so row t holds values known at the close of t-1.
    """
    m = load_aux("macro").ffill()               # holiday NaNs inside the trading-day index
    dxy_tr = m["dxy"] / m["dxy"].shift(lookback) - 1.0
    tip_tr = m["tip"] / m["tip"].shift(lookback) - 1.0
    q = min(max(float(vix_pct), 0.5), 0.99)     # keep a perturbed quantile inside (0, 1)
    thr = m["vix"].rolling(vix_window, min_periods=max(vix_window // 2, 20)).quantile(q)
    spike = (m["vix"] > thr).astype(float).where(thr.notna())
    ind = pd.DataFrame({"dxy_tr": dxy_tr, "tip_tr": tip_tr, "vix_spike": spike})
    return ind.reindex(idx).ffill().shift(1)


@register("macro_gold")
def macro_gold(panel, variant: str = "and", lookback: int = 60, vix_window: int = 504,
               vix_pct: float = 0.90, target_vol: float = 0.12, **kw) -> pd.DataFrame:
    """Benchmark crypto book plus a macro-gated (or macro-signed) metals sleeve."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; one of {sorted(VARIANTS)}")
    combine, vix_sign = VARIANTS[variant]
    closes = align(panel)
    ind = _macro_indicators(closes.index, int(lookback), int(vix_window), vix_pct)
    dollar_down = ind["dxy_tr"] < 0          # NaN compares False -> flat
    real_yield_down = ind["tip_tr"] > 0
    if combine == "and":
        metal = (dollar_down & real_yield_down).astype(float)
    elif combine == "or":
        metal = (dollar_down | real_yield_down).astype(float)
    else:  # "score": symmetric long/short
        metal = ((-np.sign(ind["dxy_tr"]) + np.sign(ind["tip_tr"])) / 2.0).fillna(0.0)
    sig = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
    for a in METALS:
        if a in sig.columns:
            sig[a] = metal
    if vix_sign != 0 and "gold" in sig.columns:
        spike = (ind["vix_spike"] > 0.5).to_numpy()
        sig.loc[spike, "gold"] = 1.0 if vix_sign > 0 else 0.0
    return vol_target(sig, panel, target_vol, **kw)


TRIALS = {
    "macro_gold": {
        "params": {"target_vol": 0.12, "lookback": 60, "vix_window": 504, "vix_pct": 0.9},
        "grid": {"variant": ["and", "or", "and_vix_haven", "and_vix_cut", "score"]},
    }
}
