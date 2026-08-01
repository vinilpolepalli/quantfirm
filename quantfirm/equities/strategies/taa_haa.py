"""TAA-HAA (IDEA_BACKLOG 1.4) — Keller Hybrid Asset Allocation, ETF track.

Keller & Keuning, "Dual and Canary Momentum with Rising Yields/Inflation:
Hybrid Asset Allocation" (SSRN 4346906, 2023), adapted to the desk's panel:

  * Risky menu (8): SPY IWM EFA EEM VNQ DBC IEF TLT — the brief's
    SPY/IWM/VWO/VEA/VNQ/DBC/IEF/TLT with EEM/EFA substituted for VWO/VEA
    (same exposures, already in the bias-free 25-ETF panel).
  * Canary: TIP. 13612W momentum per the backlog's pre-declared definition
    (1.1): the average of 1/3/6/12-month returns, computed from daily closes
    resampled monthly. Keller's original weighted form
    (12*r1 + 4*r3 + 2*r6 + r12)/4 is a registered variant (mom_kind).
  * Monthly at the close: if TIP 13612W > 0, equal-weight the top-`top_n`
    risky assets by 13612W, with per-asset positivity — any picked asset
    whose own 13612W <= 0 forfeits its slot to the cash proxy; else (canary
    breached) 100% to the cash proxy. Cash proxy = better of IEF/BIL by
    13612W (HAA's defensive best-of).
  * chassis="gtaa" is the single permitted family ablation (Tier 2.1 Faber
    GTAA-5): 1/5 each of SPY/EFA/IEF/VNQ/DBC when the month-end close is
    above its 10-month SMA of month-end closes, else that slot to cash.

Rebalance dates are the last trading day of each calendar month (true
monthly cadence per the brief). Weight rows are emitted at those dates only.

Causality: the monthly series takes, for each calendar month, the close of
its last trading day; the signal row at month-end date t uses closes <= t
only (current month's own close is the freshest input, exactly Keller's
month-end decision). The backtester trades row t at close t+1. During
warmup (first 12 month-ends, no r12) the book stays in cash.

Data note: the panel is split-adjusted price-only (no dividends), so BIL's
price series is ~flat — holding BIL is economically the backtester's cash.
That understates the bond/bill legs by their yield (see backlog Tier 3.1);
all benchmarks in this tournament share the same basis.

Benchmarks per the brief (registered here, identical folds): 60/40
(taa_bench_6040, monthly rebalanced SPY/IEF). SPY buy-and-hold (spy_hold)
and GEM (dual_momentum) already exist in baselines.py.

NOT required to beat xsec_refined — this candidate competes for the
bias-free ETF-track book (the brief says so explicitly). Pre-declared
success bar: survives deflated Sharpe and beats 60/40 on Sharpe AND MaxDD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

RISKY8 = ("SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT")
DEFENSIVE = ("IEF", "BIL")
GTAA5 = ("SPY", "EFA", "IEF", "VNQ", "DBC")


def _month_end_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each calendar month present in idx."""
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("M")).max().values)


def _mom_13612(monthly: pd.DataFrame, mom_kind: str) -> pd.DataFrame:
    r1 = monthly.pct_change(1)
    r3 = monthly.pct_change(3)
    r6 = monthly.pct_change(6)
    r12 = monthly.pct_change(12)
    if mom_kind == "weighted":       # Keller's original 13612W weighting
        return (12.0 * r1 + 4.0 * r3 + 2.0 * r6 + r12) / 4.0
    return (r1 + r3 + r6 + r12) / 4.0   # backlog's pre-declared definition


@register("taa_haa")
def taa_haa(closes: pd.DataFrame,
            risky: tuple = RISKY8,
            canary: str = "TIP",
            defensive: tuple = DEFENSIVE,
            top_n: int = 4,
            mom_kind: str = "avg",
            chassis: str = "haa",
            sma_months: int = 10) -> pd.DataFrame:
    """Keller HAA: TIP-canary-gated top-N of 8 risky ETFs by 13612W with
    per-asset positivity, defensive best-of IEF/BIL. Long-only, monthly."""
    idx = closes.index
    me_dates = _month_end_dates(idx)
    syms = sorted({*risky, canary, *defensive} & set(closes.columns))
    monthly = closes.loc[me_dates, syms]
    w = pd.DataFrame(0.0, index=me_dates, columns=closes.columns)

    if chassis == "gtaa":            # Tier 2.1 ablation: Faber GTAA-5
        menu = [s for s in GTAA5 if s in closes.columns]
        sma = monthly[menu].rolling(sma_months).mean()
        for d in me_dates:
            px, sm = monthly.loc[d, menu], sma.loc[d, menu]
            for s in menu:
                if pd.notna(sm[s]) and px[s] > sm[s]:
                    w.at[d, s] = 1.0 / len(menu)
        return w

    mom = _mom_13612(monthly, mom_kind)
    risky_list = [s for s in risky if s in closes.columns]
    def_list = [s for s in defensive if s in closes.columns]

    for d in me_dates:
        row = mom.loc[d]
        cval = row.get(canary, np.nan)
        dvals = row.reindex(def_list).dropna()
        if pd.isna(cval) or dvals.empty:
            continue                 # warmup — cash
        proxy = dvals.idxmax()       # best of IEF/BIL by 13612W
        if cval <= 0.0:              # canary breached — full defense
            w.at[d, proxy] = 1.0
            continue
        rvals = row.reindex(risky_list).dropna().sort_values(ascending=False)
        if len(rvals) < top_n:
            continue                 # warmup — cash
        slot = 1.0 / top_n
        for s in rvals.index[:top_n]:
            if rvals[s] > 0.0:       # per-asset positivity
                w.at[d, s] += slot
            else:                    # slot forfeits to the cash proxy
                w.at[d, proxy] += slot
    return w


@register("taa_bench_6040")
def taa_bench_6040(closes: pd.DataFrame, w_spy: float = 0.6,
                   bond: str = "IEF") -> pd.DataFrame:
    """60/40 benchmark (brief-mandated): SPY/IEF, monthly rebalanced."""
    me_dates = _month_end_dates(closes.index)
    w = pd.DataFrame(0.0, index=me_dates, columns=closes.columns)
    if "SPY" in closes.columns:
        w.loc[:, "SPY"] = w_spy
    if bond in closes.columns:
        w.loc[:, bond] = 1.0 - w_spy
    return w
