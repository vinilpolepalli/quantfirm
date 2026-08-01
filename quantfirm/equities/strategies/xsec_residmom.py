"""Residual momentum ranking A/B on the xsec_refined chassis (STOCK track).

IDEA_BACKLOG 1.5 XSEC-RESIDMOM. Pure feature experiment: the ONLY change vs
the incumbent `xsec_refined` is the cross-sectional ranking score. Everything
else — top_n selection, rank-band holding, per-name absolute-momentum filter
(still computed on RAW momentum, as in the incumbent), inverse-vol weighting
(still RAW realized vol), defensive ETF rotation, rebalance cadence — is
copied verbatim from xsec_refined and left untouched.

Ranking score (Blitz/Huij/Martens residual momentum, SSRN 2319861, adapted to
a single-factor market model since we carry no factor data):
  1. beta_i(t): rolling OLS beta of stock i's daily returns on SPY daily
     returns over `beta_window` (=252d, the brief's spec; min_periods =
     beta_window // 2 so residuals exist during early warmup — a warmup
     detail, not a tuned parameter).
  2. resid_i(t) = r_i(t) - beta_i(t) * r_SPY(t)   (causal: beta at t uses
     returns <= t only).
  3. score = rolling sum of resid over (formation - skip) days, shifted by
     skip (6-1 shape identical to the incumbent's), divided by rolling
     residual vol over vol_days.

Pre-declared parameter surface (NO sweeping, per the brief): beta_window=252;
all other params inherited from the incumbent champion (formation=189,
skip=21, vol_days=63, top_n=6, band_mult=3, inv_vol, every=21,
abs_filter=True, gate_mode="none", def_menu=IEF/TLT/GLD/SHY, def_lookback=63,
def_k=1). One variant, one trial.

Causality: identical to the incumbent — every signal at row t uses closes
<= t (pct_change / rolling / shift look strictly backward); the backtester
trades row t at close t+1.

SURVIVORSHIP NOTE: same 200-stock universe as the incumbent, same haircut.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# The 25 bias-free ETFs in the panel (from universe.json) — excluded from the
# stock ranking universe, used for the regime gate and defensive sleeve.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD",
}

DEFAULT_DEF_MENU = ("IEF", "TLT", "GLD", "SHY")


@register("xsec_residmom")
def xsec_residmom(closes: pd.DataFrame,
                  formation: int = 189,
                  skip: int = 21,
                  vol_days: int = 63,
                  beta_window: int = 252,
                  top_n: int = 6,
                  band_mult: float = 3.0,
                  weighting: str = "inv_vol",
                  every: int = 21,
                  vol_scale: bool = True,
                  abs_filter: bool = True,
                  gate_sma: int = 200,
                  gate_mode: str = "none",
                  vol_window: int = 20,
                  vol_cap: float = 0.25,
                  def_menu: tuple = DEFAULT_DEF_MENU,
                  def_lookback: int = 63,
                  def_k: int = 1) -> pd.DataFrame:
    """xsec_refined chassis with the ranking score replaced by vol-scaled
    residual (market-beta-hedged) momentum. See module docstring."""
    stocks = [c for c in closes.columns if c not in ETFS]
    rets = closes[stocks].pct_change(fill_method=None)
    # raw momentum retained ONLY for the per-name absolute filter (module
    # kept identical to the incumbent)
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    vol = rets.rolling(vol_days).std()   # raw vol for inv_vol weighting

    # --- residual momentum ranking score (the ONE changed module) ---
    spy_ret = closes["SPY"].pct_change(fill_method=None)
    minp = max(2, beta_window // 2)
    cov = rets.rolling(beta_window, min_periods=minp).cov(spy_ret)
    var = spy_ret.rolling(beta_window, min_periods=minp).var()
    beta = cov.div(var.replace(0.0, np.nan), axis=0)
    resid = rets.sub(beta.mul(spy_ret, axis=0))
    resid_mom = resid.rolling(formation - skip).sum().shift(skip)
    if vol_scale:
        resid_vol = resid.rolling(vol_days).std()
        score = resid_mom / resid_vol.replace(0.0, np.nan)
    else:
        score = resid_mom

    # --- everything below is copied verbatim from xsec_refined ---
    idx = closes.index
    if gate_mode != "none" and gate_sma and "SPY" in closes.columns:
        spy = closes["SPY"]
        sma = spy.rolling(gate_sma).mean()
        trend_on = spy > sma
        if gate_mode == "half":
            rv = spy.pct_change().rolling(vol_window).std() * np.sqrt(252)
            vol_ok = rv <= vol_cap
            risk_frac = pd.Series(0.0, index=idx)
            risk_frac[trend_on & vol_ok] = 1.0
            risk_frac[trend_on & ~vol_ok] = 0.5
        else:  # binary
            risk_frac = trend_on.astype(float)
        risk_frac[sma.isna()] = 1.0  # no gate before SMA exists
    else:
        risk_frac = pd.Series(1.0, index=idx)

    dmenu = [s for s in def_menu if s in closes.columns]
    dmom = closes[dmenu].pct_change(def_lookback) if dmenu else None

    dates = idx[::every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    band = max(top_n, int(round(band_mult * top_n)))
    holdings: list = []

    for d in dates:
        s_row = score.loc[d].dropna()
        m_row = mom.loc[d]
        if len(s_row) < top_n:      # warmup — stay in cash
            holdings = []
            continue
        ranked = s_row.sort_values(ascending=False)
        band_set = set(ranked.index[:band])

        def _ok(sym):
            if not abs_filter:
                return True
            v = m_row.get(sym, np.nan)
            return pd.notna(v) and v > 0

        # keep incumbents still inside the band (and passing abs momentum)
        kept = [s for s in holdings
                if s in band_set and s in s_row.index and _ok(s)]
        # fill vacant slots with the best-ranked new names
        for s in ranked.index:
            if len(kept) >= top_n:
                break
            if s not in kept and _ok(s):
                kept.append(s)
        holdings = kept

        rf = float(risk_frac.at[d])
        offense_total = rf * len(kept) / top_n
        def_total = 1.0 - offense_total

        if kept and offense_total > 0:
            if weighting == "inv_vol":
                iv = 1.0 / vol.loc[d].reindex(kept)
                iv = iv.replace([np.inf, -np.inf], np.nan).dropna()
                if len(iv):
                    ww = iv / iv.sum() * offense_total
                    for s, x in ww.items():
                        w.at[d, s] = float(x)
                else:
                    for s in kept:
                        w.at[d, s] = offense_total / len(kept)
            else:                    # equal weight
                for s in kept:
                    w.at[d, s] = offense_total / len(kept)

        # --- defensive sleeve: best trending safe ETF(s), else cash ---
        if def_total > 1e-9 and dmom is not None:
            dv = dmom.loc[d].dropna().sort_values(ascending=False)
            dpicks = [s for s in dv.index[:def_k] if dv[s] > 0]
            for s in dpicks:
                w.at[d, s] = w.at[d, s] + def_total / def_k
            # any unfilled defensive share stays in cash
    return w
