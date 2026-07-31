"""All-weather trend (BIAS-FREE ETF track) — allweather-trend desk.

Permanent diversified base (US large/growth/small equity + long bonds + gold
+ commodities) with a PER-ASSET trend filter: each sleeve holds its
vol-balanced strategic weight while its own trend is up, and goes to cash
when its trend breaks. No cross-sectional ranking, no canaries — every sleeve
stands on its own trend, which keeps turnover low and drawdowns shallow.

Tuned champion (dev 4-fold walk-forward, 39 evaluations total): menu
SPY/QQQ/IWM/TLT/GLD/DBC, blend filter (SMA-200 x 11-month momentum sign,
half-weight on disagreement), inverse-126d-vol budgets over the full menu,
monthly rebalance, off-trend budget stays in cash. Dev OOS Sharpe 0.90
(folds 0.49/1.36/0.50/1.20 — all positive incl. the 2022 bond crash fold),
max DD -12%, annual turnover 2.5x, 0.88 at 10 bps/side stress. Findings that
got here: cash cushion beats renorm-to-survivors (renorm ~halves Sharpe and
doubles DD); SHY/IEF cash proxies only add drag + turnover; DBC's inflation
sleeve is what turns the 2022 fold positive; equal-weight ties inv_vol
(robust to weighting choice); sma/mom neighbors within 0.05 (stable plateau).

Design:
  * menu: fixed sleeve list (all bias-free ETFs with 2016+ history).
  * strategic weights: inverse trailing vol over the FULL menu (vol-balanced
    risk budget), or equal weight. Weights are computed over all menu members,
    so a sleeve that is trend-off leaves its budget in cash (de-risking the
    book) unless renorm=True redistributes to surviving sleeves.
  * trend filter per sleeve: price vs its own SMA, its own total-return
    momentum sign, or a 50/50 blend of the two (blend gives half-weight when
    the signals disagree — fewer whipsaw round-trips, lower turnover).
  * optional cash proxy: the trend-off fraction of the book parks in a
    short-duration bond ETF, itself gated by its own trend (so 2022-style
    bond selloffs push it to true cash).

Causal: row t uses closes <= t only (rolling / pct_change look strictly
backward); the backtester trades row t at close t+1. Rows are emitted only on
rebalance dates (every `every` bars) and ffill between them.

Account fit: <= 7 ETF positions (well under 15), monthly cadence, long-only,
fractional-dollar friendly, annual turnover ~1-2x.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

CHAMPION_MENU = ("SPY", "QQQ", "IWM", "TLT", "GLD", "DBC")


@register("allweather_trend")
def allweather_trend(closes: pd.DataFrame,
                     menu=CHAMPION_MENU,
                     sma_days: int = 200,
                     mom_days: int = 231,
                     filter_mode: str = "blend",
                     vol_days: int = 126,
                     weighting: str = "inv_vol",
                     every: int = 21,
                     renorm: bool = False,
                     cash_proxy: str = "",
                     max_sleeve: float = 0.5) -> pd.DataFrame:
    """Vol-balanced permanent portfolio with per-asset trend gates.

    filter_mode: "sma" (price > SMA), "mom" (mom_days total return > 0), or
    "blend" (average of the two indicators -> sleeve scale in {0, .5, 1}).
    """
    menu = [s for s in menu if s in closes.columns]
    px = closes[menu]

    # --- per-sleeve trend indicator in [0, 1] ---
    sma_on = (px > px.rolling(sma_days).mean()).astype(float)
    mom_on = (px.pct_change(mom_days) > 0).astype(float)
    valid = px.rolling(max(sma_days, mom_days)).count() >= max(sma_days, mom_days)
    if filter_mode == "sma":
        on = sma_on
    elif filter_mode == "mom":
        on = mom_on
    else:  # blend
        on = 0.5 * sma_on + 0.5 * mom_on
    on = on.where(valid, 0.0)  # warmup -> off

    # --- strategic (risk-budget) weights over the FULL menu ---
    if weighting == "inv_vol":
        vol = px.pct_change(fill_method=None).rolling(vol_days).std()
        iv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
        base = iv.div(iv.sum(axis=1), axis=0)
    else:  # equal
        base = pd.DataFrame(1.0 / len(menu), index=px.index, columns=menu)
    base = base.clip(upper=max_sleeve)
    base = base.div(base.sum(axis=1).where(base.sum(axis=1) > 0, 1.0), axis=0)

    dates = closes.index[::every]
    w_menu = (base * on).reindex(dates).fillna(0.0)

    if renorm:
        tot = w_menu.sum(axis=1)
        w_menu = w_menu.div(tot.where(tot > 0, 1.0), axis=0)

    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    w[menu] = w_menu

    # --- park the trend-off fraction in a short-duration proxy, itself
    #     gated by its own trend so it can't bleed in a bond selloff ---
    if cash_proxy and cash_proxy in closes.columns and not renorm:
        cp = closes[cash_proxy]
        cp_ok = ((cp > cp.rolling(sma_days).mean()) &
                 (cp.rolling(sma_days).count() >= sma_days)).reindex(dates)
        off = (1.0 - w.sum(axis=1)).clip(lower=0.0)
        park = off.where(cp_ok.fillna(False), 0.0)
        w[cash_proxy] = w[cash_proxy] + park

    return w
