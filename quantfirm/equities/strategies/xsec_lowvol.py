"""XSEC-LOWVOL-SLEEVE (IDEA_BACKLOG 1.2) — low-volatility sleeve as the
incumbent's risk-off destination.

Thesis (Blitz & van Vliet 2007, SSRN 980865): long-only low-vol is the rare
anomaly whose published effect is substantially a long-leg phenomenon. This
module wires the lowest-vol names of the incumbent's OWN 200-stock universe
in as the defensive destination of `xsec_refined`'s rotation, replacing the
cash/bond-ETF default. Every other module of the incumbent is copied verbatim
and left untouched (the incumbent file is never edited).

Two registered strategies:

  * ``xsec_lowvol``        — the incumbent chassis (formation 189-21,
    vol-scaled ranking, top-6, rank-band 3x, inv-vol weights, per-name abs
    filter, monthly) whose risk-off slots go to an equal-weight sleeve of the
    ``sleeve_n`` lowest trailing-252d-vol stocks instead of IEF/TLT/GLD/SHY.
  * ``xsec_lowvol_sleeve`` — the sleeve STANDALONE, run once purely to
    document that it does not beat the incumbent (pre-registered expectation
    per the brief: it will not).

Sleeve construction (per brief): rank the non-ETF universe by trailing 252d
realized vol (ascending), hold the bottom ``sleeve_n`` names equal-weight,
with rank-band hysteresis: a held name is kept while its vol rank stays
inside ``sleeve_band * sleeve_n``; vacancies are filled with the lowest-vol
non-held names. Sleeve state advances at every rebalance date so hysteresis
is well-defined across risk-on stretches.

Declared parameter surface (registered up front): sleeve_n in {10, 20}
(decile-vs-quintile split of the brief), sleeve_band in {1.5, 2.5};
sleeve_vol_days fixed at 252 per brief. All chassis params pinned to the
incumbent champion.

Account fit note: sleeve_n=10 keeps worst-case position count at
(top_n - 1) offense + 10 sleeve = 15, exactly the account cap; sleeve_n=20
can breach the 15-position cap when fully risk-off and is registered only
because the brief pre-declares the 10-vs-20 sweep.

Causality: identical to the incumbent — every signal at row t uses closes
<= t only (pct_change / rolling / shift look strictly backward); the
backtester trades row t at close t+1. Weight rows are emitted at rebalance
dates only.

SURVIVORSHIP NOTE (flagged for adversarial review per brief): the sleeve
draws from the 200-stock universe selected today, so unlike the incumbent's
bias-free ETF defense it inherits the stock track's survivorship haircut —
low-vol "safe" names that later blew up are absent by construction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# The 25 bias-free ETFs in the panel — excluded from the stock ranking
# universe and from the low-vol sleeve (copied from the incumbent).
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD",
}


def _sleeve_step(vol_row: pd.Series, prev: list, sleeve_n: int,
                 sleeve_band: float) -> list:
    """One hysteresis step of the low-vol sleeve.

    Rank by trailing vol ascending (lowest vol = best). Keep previous
    holdings still inside the band of ``sleeve_band * sleeve_n`` ranks; fill
    vacancies with the lowest-vol new names. Empty until ``sleeve_n`` names
    have a valid vol estimate.
    """
    v = vol_row.dropna()
    v = v[v > 0]
    if len(v) < sleeve_n:
        return []
    ranked = v.sort_values()          # ascending: lowest vol first
    band = max(sleeve_n, int(round(sleeve_band * sleeve_n)))
    band_set = set(ranked.index[:band])
    kept = [s for s in prev if s in band_set]
    for s in ranked.index:
        if len(kept) >= sleeve_n:
            break
        if s not in kept:
            kept.append(s)
    return kept[:sleeve_n]


@register("xsec_lowvol_sleeve")
def xsec_lowvol_sleeve(closes: pd.DataFrame,
                       sleeve_n: int = 20,
                       sleeve_vol_days: int = 252,
                       sleeve_band: float = 1.5,
                       every: int = 21) -> pd.DataFrame:
    """Standalone low-vol sleeve: equal-weight bottom ``sleeve_n`` stocks by
    trailing 252d vol, monthly, rank-band hysteresis. Documentation run only
    (pre-registered expectation: does NOT beat the incumbent)."""
    stocks = [c for c in closes.columns if c not in ETFS]
    vol = closes[stocks].pct_change(fill_method=None).rolling(sleeve_vol_days).std()
    dates = closes.index[::every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    hold: list = []
    for d in dates:
        hold = _sleeve_step(vol.loc[d], hold, sleeve_n, sleeve_band)
        for s in hold:
            w.at[d, s] = 1.0 / sleeve_n
    return w


@register("xsec_lowvol")
def xsec_lowvol(closes: pd.DataFrame,
                formation: int = 189,
                skip: int = 21,
                vol_days: int = 63,
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
                sleeve_n: int = 10,
                sleeve_vol_days: int = 252,
                sleeve_band: float = 1.5) -> pd.DataFrame:
    """`xsec_refined` chassis with the defensive destination replaced by the
    low-vol stock sleeve. Offense modules (ranking, rank-band holding, abs
    filter, inv-vol weighting, gate) are copied verbatim from the incumbent.
    """
    stocks = [c for c in closes.columns if c not in ETFS]
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    rets = closes[stocks].pct_change(fill_method=None)
    vol = rets.rolling(vol_days).std()
    if vol_scale:
        score = mom / vol.replace(0.0, np.nan)
    else:
        score = mom

    # --- regime gate (risk fraction per date) — verbatim from incumbent ---
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

    # --- low-vol sleeve inputs (replaces the def_menu ETF momentum) ---
    sleeve_vol = rets.rolling(sleeve_vol_days).std()

    dates = idx[::every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    band = max(top_n, int(round(band_mult * top_n)))
    holdings: list = []
    sleeve_hold: list = []

    for d in dates:
        # sleeve hysteresis state advances every rebalance date, deployed
        # or not, so risk-off entries start from a well-defined book
        sleeve_hold = _sleeve_step(sleeve_vol.loc[d], sleeve_hold,
                                   sleeve_n, sleeve_band)

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

        # --- defensive destination: equal-weight low-vol sleeve, else cash ---
        if def_total > 1e-9 and sleeve_hold:
            share = def_total / len(sleeve_hold)
            for s in sleeve_hold:
                w.at[d, s] = w.at[d, s] + share
        # if the sleeve is still in warmup, the defensive share stays in cash
    return w
