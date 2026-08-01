"""Refined stock cross-sectional momentum (STOCK track) — xsec-refined desk.

Improvements over the xsec_momentum baseline (dev OOS 0.91):
  1. Vol-scaled ranking: rank by momentum / realized vol (Sharpe-momentum)
     instead of raw return, damping the junk-vol names that dominate raw
     rankings and crash hardest in regime turns.
  2. Intermediate lookback: ~8-month formation with 1-month skip (189-21)
     rather than 12-1 — the more robust part of the momentum term structure.
  3. Rank-band holding (turnover control): a held name is only replaced when
     it falls out of the top band_mult * top_n ranks, so marginal rank noise
     does not churn the book (annual turnover ~9.6x vs baseline 9.4x with
     far higher gross alpha; Sharpe degrades only 1.35 -> 1.33 at 10bps).
  4. Risk-off to ETFs, not cash: any name failing its own absolute-momentum
     filter forfeits its slot to the best trending defensive ETF
     (IEF/TLT/GLD/SHY, bias-free) — cash only if none trend. An explicit
     SPY-SMA book-level gate is available (gate_mode) but tested WORSE on
     dev (whipsaw), so the tuned default is per-name gating only.
  5. Inverse-vol position weighting.

Tuned champion (dev 4-fold walk-forward, 39 total trials, net 5bps/side):
formation=189, skip=21, top_n=6, band_mult=3.0, inv_vol, gate_mode=none ->
OOS Sharpe 1.349 (folds 0.625/2.051/0.514/1.992), max DD -28%, turnover
9.6x; 10bps stress 1.330. Baseline xsec_momentum: 0.908.

Account fit: <= top_n + def_k positions (default 6 + 1 <= 15), monthly
rebalance (every=21), long-only, fractional-dollar friendly ($250 / 7
positions ~ $36 each, above the $2 minimum).

Causality: every signal at row date t is built from closes <= t only
(pct_change / rolling / shift look strictly backward); the backtester trades
row t at close t+1. Weight rows are emitted at rebalance dates only.

SURVIVORSHIP NOTE: uses the 200-stock universe (selected today), so dev
results carry survivorship bias; the judge applies a 30% haircut. The design
leans on the bias-free ETF defensive sleeve for the risk-off leg.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# ETFs and any other non-stock panel columns — excluded from the stock
# ranking universe, used only for the regime gate and defensive sleeve.
# Tournament #3 lesson: research agents add data files (TIP/BIL) that
# load_panel() globs in, so a hardcoded list silently rots. The stock
# universe is therefore defined POSITIVELY from universe.json; the
# hardcoded set survives only as a fallback if the file is unreadable.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD", "TIP", "BIL", "VEU",
}


def _stock_universe(columns) -> list:
    try:
        from ..data import universe
        allowed = {s["ticker"] for s in universe()["stocks"]}
        return [c for c in columns if c in allowed]
    except Exception:
        return [c for c in columns if c not in ETFS]

DEFAULT_DEF_MENU = ("IEF", "TLT", "GLD", "SHY")


@register("xsec_refined")
def xsec_refined(closes: pd.DataFrame,
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
                 def_menu: tuple = DEFAULT_DEF_MENU,
                 def_lookback: int = 63,
                 def_k: int = 1) -> pd.DataFrame:
    """Vol-scaled cross-sectional momentum with rank-band holding and an
    ETF-defense regime gate.

    gate_mode: "binary" (risk 1.0 if SPY > SMA else 0.0), "half" (1.0 if
    trend on and realized vol <= vol_cap, 0.5 if trend on but vol high,
    0.0 if trend off), or "none".
    """
    stocks = _stock_universe(closes.columns)
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    rets = closes[stocks].pct_change(fill_method=None)
    vol = rets.rolling(vol_days).std()
    if vol_scale:
        score = mom / vol.replace(0.0, np.nan)
    else:
        score = mom

    # --- regime gate (risk fraction per date) ---
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
