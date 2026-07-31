"""Vectorized long-only backtester with venue costs and walk-forward splits.

Contract for strategies (see strategies/base.py): a strategy maps an OHLCV
frame to a target position series in [0, 1] (fraction of bankroll in the
asset). Positions are decided on bar close t and earn bar t+1's return —
no lookahead by construction. Costs are charged on |Δposition|.

Anti-overfitting rules enforced here:
  * DEV/HOLDOUT split: tournament agents may only run --split dev
    (data before HOLDOUT_START). The judge alone runs the holdout, once.
  * Walk-forward folds inside dev for out-of-sample scoring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .costs import CostModel, RH_MARKET
from .metrics import HOURS_PER_YEAR, summary, sharpe

# Tournament agents never see results after this date. Judge only.
HOLDOUT_START = "2025-07-01"
DEV_START = "2019-01-01"


def run(df: pd.DataFrame, position: pd.Series, cost: CostModel = RH_MARKET,
        bars_per_year: float = HOURS_PER_YEAR) -> dict:
    """Simulate. `position` must be indexed like df, values in [0, 1]."""
    pos = position.reindex(df.index).ffill().fillna(0.0).clip(0.0, 1.0)
    ret = df["close"].pct_change().fillna(0.0)
    # position chosen at close of t applies to return from t to t+1
    strat_ret = pos.shift(1).fillna(0.0) * ret
    trade_cost = pos.diff().abs().fillna(pos.iloc[0] if len(pos) else 0.0) * cost.per_side
    net_ret = strat_ret - trade_cost
    equity = (1 + net_ret).cumprod()
    out = summary(net_ret, pos, equity, bars_per_year)
    out["cost_model"] = cost.name
    out["gross_sharpe"] = round(sharpe(strat_ret, bars_per_year), 3)
    out["cost_drag_annual"] = round(float(trade_cost.sum() / max(len(df) / bars_per_year, 1e-9)), 4)
    return out


def run_strategy(df: pd.DataFrame, strategy, params: dict,
                 cost: CostModel = RH_MARKET) -> dict:
    pos = strategy(df, **params)
    return run(df, pos, cost)


def walk_forward(df: pd.DataFrame, strategy, params: dict,
                 cost: CostModel = RH_MARKET, n_folds: int = 5,
                 warmup_bars: int = 24 * 90) -> dict:
    """Score out-of-sample: split dev period into n_folds contiguous test
    windows; for each, compute signals with history available up to the end of
    that window but score only the window's bars. (Signal functions are
    causal by contract, so per-fold refit is a no-op unless the strategy
    optimises internally; the split still kills regime-lucky full-sample wins.)
    """
    idx = df.index
    fold_edges = np.linspace(warmup_bars, len(idx), n_folds + 1, dtype=int)
    fold_results = []
    oos_returns = []
    for i in range(n_folds):
        lo, hi = fold_edges[i], fold_edges[i + 1]
        if hi - lo < 50:
            continue
        window = df.iloc[:hi]  # causal history through fold end
        pos = strategy(window, **params).reindex(window.index).ffill().fillna(0.0).clip(0, 1)
        ret = window["close"].pct_change().fillna(0.0)
        strat_ret = pos.shift(1).fillna(0.0) * ret
        trade_cost = pos.diff().abs().fillna(0.0) * cost.per_side
        net = (strat_ret - trade_cost).iloc[lo:hi]
        oos_returns.append(net)
        fold_results.append(round(sharpe(net), 3))
    all_oos = pd.concat(oos_returns) if oos_returns else pd.Series(dtype=float)
    equity = (1 + all_oos).cumprod()
    pos_full = strategy(df, **params).reindex(df.index).ffill().fillna(0.0)
    out = summary(all_oos, pos_full, equity if len(equity) else pd.Series([1.0]))
    out["fold_sharpes"] = fold_results
    out["oos_sharpe"] = out.pop("net_sharpe")
    out["cost_model"] = cost.name
    return out


def split(df: pd.DataFrame, which: str) -> pd.DataFrame:
    if which == "dev":
        return df.loc[DEV_START:HOLDOUT_START].iloc[:-1]
    if which == "holdout":
        return df.loc[HOLDOUT_START:]
    if which == "all":
        return df
    raise ValueError("split must be dev|holdout|all")
