"""Cross-sectional (portfolio) backtester for the equity desk.

Strategy contract: a function (closes, **params) -> DataFrame of target
WEIGHTS (index: dates, columns: symbols, rows sum to <= 1.0, long-only),
CAUSAL: the weight row at date t may use closes up to and including t, and is
traded at t+1's close (next-bar execution — conservative for daily signals).
Weights persist (ffill) between rebalance rows; emit rows only when they
change to keep turnover visible.

Costs: charged on turnover = 0.5 * sum(|w_new - w_drifted|) * 2 sides, i.e.
cost_bps per side on traded notional. Weight drift between rebalances is
modeled (winners grow their weight before the next rebalance).

Splits: dev before HOLDOUT_START, holdout after — same discipline as the
crypto desk; tournament designers may only run dev.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..metrics import summary as _summary, sharpe as _sharpe

TRADING_DAYS = 252
HOLDOUT_START = "2024-08-01"
DEV_START = "2016-06-01"


def run(closes: pd.DataFrame, weights: pd.DataFrame,
        cost_bps_per_side: float = 5.0) -> dict:
    """Simulate a long-only weight schedule over a close-price panel."""
    rets = closes.pct_change(fill_method=None)
    w_target = weights.reindex(closes.index).ffill().fillna(0.0).clip(lower=0.0)
    # cap accidental gross > 1
    gross = w_target.sum(axis=1)
    w_target = w_target.div(gross.where(gross > 1.0, 1.0), axis=0)

    cost_rate = cost_bps_per_side / 1e4
    n = len(closes)
    port_ret = np.zeros(n)
    turnover = np.zeros(n)
    w_held = pd.Series(0.0, index=closes.columns)

    ret_np = rets.fillna(0.0).to_numpy()
    tgt_np = w_target.to_numpy()
    cols = closes.columns
    for i in range(1, n):
        # 1. holdings drift with returns of bar i
        r = ret_np[i]
        w = w_held.to_numpy()
        growth = w * (1 + r)
        port_r = growth.sum() - w.sum()  # cash earns 0
        total = 1 + port_r
        w_drift = growth / total if total > 0 else growth * 0
        # 2. rebalance to target decided at close i-1... (weights row i-1),
        #    traded at close i
        tgt = tgt_np[i - 1]
        traded = np.abs(tgt - w_drift).sum()
        cost = traded * cost_rate
        port_ret[i] = port_r - cost
        turnover[i] = traded
        w_held = pd.Series(tgt, index=cols)

    net = pd.Series(port_ret, index=closes.index)
    equity = (1 + net).cumprod()
    exposure = w_target.sum(axis=1)
    out = _summary(net, exposure, equity, TRADING_DAYS)
    out["annual_turnover"] = round(float(turnover.sum() / max(len(net) / TRADING_DAYS, 1e-9)), 2)
    out["cost_bps_per_side"] = cost_bps_per_side
    return out


def run_strategy(closes: pd.DataFrame, strategy, params: dict,
                 cost_bps_per_side: float = 5.0) -> dict:
    w = strategy(closes, **params)
    return run(closes, w, cost_bps_per_side)


def walk_forward(closes: pd.DataFrame, strategy, params: dict,
                 cost_bps_per_side: float = 5.0, n_folds: int = 4,
                 warmup_days: int = 300) -> dict:
    """Out-of-sample scoring in contiguous folds (same shape as the crypto
    desk's). Monthly-rebalance strategies have ~12 decisions/yr, so folds are
    longer and fewer than on hourly crypto."""
    idx = closes.index
    edges = np.linspace(warmup_days, len(idx), n_folds + 1, dtype=int)
    fold_sharpes, oos = [], []
    for k in range(n_folds):
        lo, hi = edges[k], edges[k + 1]
        if hi - lo < 60:
            continue
        window = closes.iloc[:hi]
        w = strategy(window, **params)
        res_window = window.iloc[:]
        rets_slice = _slice_returns(res_window, w, cost_bps_per_side, lo, hi)
        oos.append(rets_slice)
        fold_sharpes.append(round(_sharpe(rets_slice, TRADING_DAYS), 3))
    all_oos = pd.concat(oos) if oos else pd.Series(dtype=float)
    equity = (1 + all_oos).cumprod()
    w_full = strategy(closes, **params).reindex(closes.index).ffill().fillna(0.0)
    exposure = w_full.sum(axis=1).reindex(all_oos.index).fillna(0.0)
    out = _summary(all_oos, exposure, equity if len(equity) else pd.Series([1.0]),
                   TRADING_DAYS)
    out["fold_sharpes"] = fold_sharpes
    out["oos_sharpe"] = out.pop("net_sharpe")
    out["cost_bps_per_side"] = cost_bps_per_side
    return out


def _slice_returns(closes: pd.DataFrame, weights: pd.DataFrame,
                   cost_bps: float, lo: int, hi: int) -> pd.Series:
    """Net portfolio returns for bars [lo, hi) given the full causal sim."""
    rets = closes.pct_change(fill_method=None)
    w_target = weights.reindex(closes.index).ffill().fillna(0.0).clip(lower=0.0)
    gross = w_target.sum(axis=1)
    w_target = w_target.div(gross.where(gross > 1.0, 1.0), axis=0)
    cost_rate = cost_bps / 1e4
    ret_np = rets.fillna(0.0).to_numpy()
    tgt_np = w_target.to_numpy()
    port = np.zeros(len(closes))
    w = np.zeros(closes.shape[1])
    for i in range(1, len(closes)):
        growth = w * (1 + ret_np[i])
        port_r = growth.sum() - w.sum()
        total = 1 + port_r
        w_drift = growth / total if total > 0 else growth * 0
        tgt = tgt_np[i - 1]
        port[i] = port_r - np.abs(tgt - w_drift).sum() * cost_rate
        w = tgt
    return pd.Series(port, index=closes.index).iloc[lo:hi]


def split(closes: pd.DataFrame, which: str) -> pd.DataFrame:
    cutoff = pd.Timestamp(HOLDOUT_START)
    if which == "dev":
        sub = closes.loc[DEV_START:]
        return sub[sub.index < cutoff]
    if which == "holdout":
        return closes[closes.index >= cutoff]
    if which == "all":
        return closes
    raise ValueError("split must be dev|holdout|all")
