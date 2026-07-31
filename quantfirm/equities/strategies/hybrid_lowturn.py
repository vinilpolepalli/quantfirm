"""Hybrid low-turnover (STOCK track) — hybrid-lowturn desk.

Two sleeves, quarterly rebalance, deliberately few knobs:

  1. Quality-momentum stock sleeve (~50% of book): 12-1 cross-sectional
     momentum, but ranked by the AVERAGE momentum percentile over the last
     n_snaps monthly snapshots (rank stability — names that just spiked into
     the top decile are discounted), restricted to the calmer half of the
     universe by realized vol of returns (low vol-of-returns filter — junk
     momentum is concentrated in the high-vol tail). Top-N equal weight,
     each name must also have positive absolute momentum.
  2. Defensive ETF sleeve (~50% of book, survivorship-free): an equal split
     across a small defensive menu (IEF / GLD by default), each slice trend
     gated by its own long SMA — a slice whose asset is below trend sits in
     cash.

A book-level trend gate (SPY vs its long SMA) moves the stock sleeve's
allocation into the defensive sleeve when the market is below trend, so in a
2022-style regime the whole book is defensive-or-cash.

Robustness stance per the family brief: quarterly rebalance (every=63),
equal weights, one shared SMA length for all gates, no per-name weighting
model. Optimized for holdout transfer, not dev Sharpe.

Causality: all signals at row date t use closes <= t only (pct_change /
rolling / shift look strictly backward); the backtester trades row t at
close t+1. Weight rows are emitted at rebalance dates only.

Account fit: <= top_n + len(def_menu) positions (6 + 2 = 8 <= 15), quarterly
rebalance, long-only, $250 / 8 positions ~ $31 each >> $2 minimum.

SURVIVORSHIP NOTE: the stock sleeve uses the 200-stock universe selected
today, so dev results carry survivorship bias (judge applies a 30% haircut).
Half the book (the defensive sleeve) is bias-free ETFs by design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# The 25 bias-free ETFs in the panel (from universe.json) — excluded from the
# stock ranking universe.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD",
}


@register("hybrid_lowturn")
def hybrid_lowturn(closes: pd.DataFrame,
                   formation: int = 252,
                   skip: int = 21,
                   top_n: int = 6,
                   vol_window: int = 126,
                   vol_max: float = 0.5,
                   n_snaps: int = 3,
                   snap_step: int = 21,
                   gate_every: int = 63,
                   pick_every: int = 1,
                   gate_sma: int = 200,
                   stock_frac: float = 0.5,
                   def_menu: tuple = ("IEF", "TLT", "GLD", "DBC")) -> pd.DataFrame:
    """Quality-momentum stock sleeve + trend-gated defensive ETF sleeve.

    vol_max: keep only stocks whose realized-vol percentile is <= vol_max
    (0.5 = calmer half of the universe).
    n_snaps/snap_step: momentum rank averaged over n_snaps snapshots spaced
    snap_step days apart (rank stability).
    gate_every/pick_every: trend gates are re-checked every gate_every days
    (monthly), but the stock roster is only refreshed every pick_every-th
    gate date (quarterly) — gates need to be responsive, momentum picks
    don't, and slow picks keep turnover and settlement churn down.
    """
    idx = closes.index
    stocks = [c for c in closes.columns if c not in ETFS]

    px = closes[stocks]
    mom = px.pct_change(formation - skip, fill_method=None).shift(skip)
    rank_pct = mom.rank(axis=1, pct=True)
    stab = sum(rank_pct.shift(i * snap_step) for i in range(n_snaps)) / n_snaps
    vol = px.pct_change(fill_method=None).rolling(vol_window).std()
    vol_rank = vol.rank(axis=1, pct=True)

    # book-level trend gate (no gate before the SMA exists)
    spy = closes["SPY"]
    spy_sma = spy.rolling(gate_sma).mean()
    risk_on = (spy > spy_sma) | spy_sma.isna()

    # defensive per-asset trend gates
    dmenu = [a for a in def_menu if a in closes.columns]
    dgate = {}
    for a in dmenu:
        s = closes[a].rolling(gate_sma).mean()
        dgate[a] = (closes[a] > s) | s.isna()

    dates = idx[::gate_every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)

    roster: list = []
    for j, d in enumerate(dates):
        # --- stock roster refresh (quarterly) ---
        if j % pick_every == 0:
            m_row = mom.loc[d]
            elig = (vol_rank.loc[d] <= vol_max) & (m_row > 0)
            scores = stab.loc[d].where(elig).dropna()
            roster = list(scores.sort_values(ascending=False).index[:top_n])
        # --- stock sleeve (book gate checked monthly) ---
        placed = 0.0
        if bool(risk_on.at[d]) and roster:
            for s in roster:
                w.at[d, s] = stock_frac / top_n
            placed = stock_frac / top_n * len(roster)

        # --- defensive sleeve (absorbs whatever the stock sleeve left) ---
        def_total = 1.0 - placed
        if dmenu and def_total > 1e-9:
            slice_w = def_total / len(dmenu)
            for a in dmenu:
                if bool(dgate[a].at[d]):
                    w.at[d, a] = w.at[d, a] + slice_w
                # gated-off slice stays in cash
    return w
