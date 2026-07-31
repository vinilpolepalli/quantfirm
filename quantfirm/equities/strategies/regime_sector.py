"""Regime-gated sector rotation (BIAS-FREE track, ETF-only).

Thesis: sector SPDR momentum harvests medium-term persistence in sector
leadership, but its drawdowns cluster in bear/volatile regimes. An explicit
regime layer — SPY trend (price vs 200d SMA) plus a realized-vol gate (20d
ann. vol vs cap) — scales the risky sleeve's gross 0 / 0.5 / 1. The risky
sleeve is core-satellite: a SPY core (only when trend is on) plus top-N
sector SPDRs by blended 3/6/12m momentum with an absolute filter. Whatever
is not risky goes 60% to a defensive menu (XLP/XLU/TLT/GLD/IEF) picked by
its own 3m momentum (>0 required) and 40%+ to cash — in 2022 both bonds and
low-beta equity failed, so risk-off must include real cash. Monthly
rebalance (faster regime rechecks tested and REJECTED: they whipsaw in
choppy bears); <= 6 positions; ETF-only so no survivorship haircut.

Contract: (closes, **params) -> long-only weight rows at rebalance dates,
row t uses closes <= t (traded next close by the backtester).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
           "XLRE", "XLC"]
DEFAULT_DEFENSIVE = ["XLP", "XLU", "TLT", "GLD", "IEF"]


def _blend_momentum(closes: pd.DataFrame, lookbacks) -> pd.DataFrame:
    """Average of simple returns over several horizons (all causal)."""
    parts = [closes.pct_change(lb) for lb in lookbacks]
    return sum(parts) / len(parts)


@register("regime_sector")
def regime_sector(closes: pd.DataFrame,
                  top_n: int = 2,
                  every: int = 21,
                  lookbacks: tuple = (63, 126, 252),
                  trend_sma: int = 200,
                  vol_window: int = 20,
                  vol_cap: float = 0.25,
                  regime_mode: str = "sum",
                  def_menu: tuple = ("XLP", "XLU", "TLT", "GLD", "IEF"),
                  def_k: int = 2,
                  def_lookback: int = 63,
                  abs_filter: bool = True,
                  core_frac: float = 0.8,
                  core_asset: str = "SPY",
                  core_requires_trend: bool = True,
                  def_gross: float = 0.6,
                  regime_every: int = 0) -> pd.DataFrame:
    """Regime-gated sector momentum.

    risk_frac per regime_mode:
      "and_half": 1.0 if SPY>SMA and vol<=cap; 0.5 if SPY>SMA and vol>cap;
                  0.0 if SPY<=SMA.
      "sum":      0.5*trend_on + 0.5*vol_ok  (0 / 0.5 / 1)
      "trend_only": 1.0 if SPY>SMA else 0.0
    Risky sleeve: top_n sectors by blended momentum (optionally >0), equal
    weight of risk_frac. Everything not allocated risky goes to the top def_k
    of def_menu by def_lookback momentum (>0 required), else cash.
    """
    idx = closes.index
    spy = closes["SPY"]
    sma = spy.rolling(trend_sma).mean()
    trend_on = (spy > sma)
    rv = spy.pct_change().rolling(vol_window).std() * np.sqrt(252)
    vol_ok = (rv <= vol_cap)

    if regime_mode == "and_half":
        risk_frac = pd.Series(0.0, index=idx)
        risk_frac[trend_on & vol_ok] = 1.0
        risk_frac[trend_on & ~vol_ok] = 0.5
    elif regime_mode == "sum":
        risk_frac = 0.5 * trend_on.astype(float) + 0.5 * vol_ok.astype(float)
    elif regime_mode == "trend_only":
        risk_frac = trend_on.astype(float)
    else:
        raise ValueError(f"unknown regime_mode {regime_mode}")
    # no signal until the SMA exists
    risk_frac[sma.isna()] = 0.0

    universe = [s for s in SECTORS if s in closes.columns]
    mom = _blend_momentum(closes[universe], lookbacks)
    dmenu = [s for s in def_menu if s in closes.columns]
    dmom = closes[dmenu].pct_change(def_lookback)

    pick_dates = set(idx[::every])
    if regime_every and regime_every > 0:
        all_dates = idx[::regime_every]
        all_dates = all_dates.union(pd.DatetimeIndex(sorted(pick_dates)))
    else:
        all_dates = idx[::every]

    rows, row_dates = [], []
    picks: list = []  # sector picks, refreshed at monthly pick dates
    last_row = None
    for d in all_dates:
        rf = float(risk_frac.at[d])
        if d in pick_dates:
            vals = mom.loc[d].dropna().sort_values(ascending=False)
            picks = [s for s in vals.index[:top_n]
                     if (not abs_filter or vals[s] > 0)]
        row = pd.Series(0.0, index=closes.columns)
        filled = 0.0
        if rf > 0:
            core_ok = (core_asset in closes.columns
                       and (not core_requires_trend or bool(trend_on.at[d])))
            core = rf * core_frac if core_ok else 0.0
            sat = rf - rf * core_frac  # trend-off core share goes to defense
            if core > 0:
                row[core_asset] += core
                filled += core
            for s in picks:
                row[s] += sat / top_n
            filled += sat * len(picks) / top_n
        def_alloc = (1.0 - filled) * def_gross
        if def_alloc > 1e-9 and dmenu:
            dv = dmom.loc[d].dropna().sort_values(ascending=False)
            dpicks = [s for s in dv.index[:def_k] if dv[s] > 0]
            for s in dpicks:
                row[s] += def_alloc / def_k
        # unfilled defensive share stays in cash
        if last_row is None or (row - last_row).abs().sum() > 1e-9:
            rows.append(row)
            row_dates.append(d)
            last_row = row
    return pd.DataFrame(rows, index=pd.DatetimeIndex(row_dates),
                        columns=closes.columns)
