"""Portfolio backtester for Kalshi perps on daily bars.

What it books, per day, in this order:
  1. execute the rebalance decided at YESTERDAY's close at TODAY's open
     (fees = |Δnotional| × cost.per_side; never the signal bar's close)
  2. mark contracts from yesterday's close to today's close
  3. funding on today's notional (sum of the day's intervals; longs pay when
     positive), from the chosen scenario
  4. interest on unencumbered collateral (equity − initial margin in use)
  5. liquidation check on today's intraday extremes: every position marked
     at its worst point at once; if equity ≤ maintenance the book is closed
     at that point minus a penalty. Conservative on purpose.

Positions are held as CONTRACT counts between rebalances, so weights drift
with price and turnover only happens when the target moves more than the
band on a rebalance day. Targets are capped by the venue's maintenance rates
(liquidation distance) and by the risk policy before they are traded.

Walk-forward here FITS parameters: on each fold the grid point with the best
in-sample Sharpe (data strictly before the fold, minus an embargo) is chosen
and scored on the fold only. A run without a grid is a fixed-parameter fold
report and is labelled as such — the firm has been burned by calling those
'out of sample' before (CHANGELOG 0.1.1).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from ..metrics import cagr, deflated_sharpe, max_drawdown, sharpe
from .data import HOLDOUT_START, align, daily_funding, load_funding_proxy, load_kalshi_funding
from .specs import APPROVAL_COST, COLLATERAL_APY, SPECS, CostModel
from .strategies import cap_weights

DAYS = 365


@dataclass(frozen=True)
class BacktestConfig:
    cost: CostModel = APPROVAL_COST
    funding: str = "kalshi"          # none | kalshi | proxy | proxy_raw
    interest_apy: float = COLLATERAL_APY
    rebalance_band: float = 0.03     # trade when |target − held| > band; below the 0.05 weight step so one step trades
    rebalance_every: int = 7         # check the band every N days (weekly, a priori)
    max_gross: float = 1.5
    max_asset: float = 0.75
    min_liq_distance: float = 0.35
    liq_penalty: float = 0.02        # of notional closed by force
    ladder_soft: float | None = None # drawdown from peak that halves sizing (None = off)
    ladder_kill: float | None = None # drawdown that flattens for good (None = off)
    bankroll_usd: float | None = None  # when set, trade WHOLE contracts for this bankroll (granularity)


def funding_table(panel: dict[str, pd.DataFrame], index: pd.DatetimeIndex, mode: str) -> pd.DataFrame:
    """Daily funding fraction of notional per asset (positive → longs pay)."""
    cols = {}
    for a in panel:
        if mode == "none":
            s = None
        elif mode == "kalshi":
            s = load_kalshi_funding(a)
        elif mode in ("proxy", "proxy_raw"):
            s = load_funding_proxy(a)
        else:
            raise ValueError(mode)
        cols[a] = daily_funding(s, index, apply_kalshi_rule=(mode != "proxy_raw"),
                                asset_class=SPECS[a].asset_class if a in SPECS else "crypto")
    return pd.DataFrame(cols, index=index).fillna(0.0)


def run(panel: dict[str, pd.DataFrame], targets: pd.DataFrame, cfg: BacktestConfig = BacktestConfig(),
        start: str | None = None, end: str | None = None) -> dict:
    """Simulate ``targets`` (signed notional weights decided at each close)."""
    closes = align(panel)
    assets = [a for a in targets.columns if a in closes.columns]
    # start where every asset in the book has a price (leading NaNs = not yet listed)
    idx = closes.index[closes[assets].notna().all(axis=1).to_numpy()]
    if start:
        idx = idx[idx >= pd.Timestamp(start, tz="UTC")]
    if end:
        idx = idx[idx < pd.Timestamp(end, tz="UTC")]
    if len(idx) < 3:
        raise ValueError("not enough bars")
    C = closes.loc[idx, assets].to_numpy()
    O = pd.concat({a: panel[a]["open"] for a in assets}, axis=1).reindex(closes.index).ffill().loc[idx].to_numpy()
    H = pd.concat({a: panel[a]["high"] for a in assets}, axis=1).reindex(closes.index).ffill().loc[idx].to_numpy()
    L = pd.concat({a: panel[a]["low"] for a in assets}, axis=1).reindex(closes.index).ffill().loc[idx].to_numpy()
    # a metals holiday: the ffilled bar has open=high=low=close of the last session — no false liquidation
    W = cap_weights(targets.reindex(closes.index).ffill().fillna(0.0).loc[idx, assets],
                    cfg.max_gross, cfg.max_asset, cfg.min_liq_distance).to_numpy()
    F = funding_table({a: panel[a] for a in assets}, idx, cfg.funding).loc[idx, assets].to_numpy()
    maint = np.array([SPECS[a].maint_rate for a in assets])
    im = maint * 1.3
    csize = np.array([float(SPECS[a].contract_size) if a in SPECS else 0.0 for a in assets])
    n, k = C.shape

    equity = np.ones(n)
    units = np.zeros(k)             # contracts in "1 unit = $1 of price" terms: notional = units × price
    held_w = np.zeros((n, k))
    fees = np.zeros(n)
    fund = np.zeros(n)
    intr = np.zeros(n)
    turnover = np.zeros(n)
    liq = np.zeros(n, dtype=bool)
    pnl_asset = np.zeros((n, k))
    pending = None                  # target weights decided at yesterday's close
    peak = 1.0
    killed = False
    killed_pending = False          # a flatten order is never deferred to the weekly check
    fee_frac = np.zeros(n)
    fund_frac = np.zeros(n)
    intr_frac = np.zeros(n)
    E = 1.0
    pending = W[0]                  # the decision at the first close executes at the next open
    for t in range(1, n):
        E_prev = E
        # 1. execute yesterday's decision at today's open
        if pending is not None and (killed_pending or (not killed and (t - 1) % cfg.rebalance_every == 0)):
            scale = 1.0
            if cfg.ladder_soft is not None and E / peak - 1 <= -cfg.ladder_soft:
                scale = 0.5
            tgt = pending * scale
            cur_w = units * O[t] / E
            trade = np.abs(tgt - cur_w) > cfg.rebalance_band
            if trade.any():
                new_units = np.where(trade, tgt * E / O[t], units)
                if cfg.bankroll_usd:
                    # whole contracts: notional per contract = contract_size × price (proxy price is
                    # the asset's USD price, so a BTC contract is 0.0001 × price). units are in
                    # equity-normalised "$1 of price" terms: units × price = notional / equity₀.
                    per_contract = csize * O[t]                      # $ per contract
                    n_c = np.floor(np.abs(tgt) * E * cfg.bankroll_usd / np.where(per_contract > 0, per_contract, np.inf))
                    quant = np.sign(tgt) * n_c * per_contract / (cfg.bankroll_usd * O[t])
                    new_units = np.where(trade, quant, units)
                d_notional = np.abs(new_units - units) * O[t]
                turnover[t] = d_notional.sum() / E
                fees[t] = d_notional.sum() * cfg.cost.per_side
                fee_frac[t] = fees[t] / E
                E -= fees[t]
                units = new_units
            pending = None
            killed_pending = False
        # 2. mark to today's close
        pa = units * (C[t] - C[t - 1])
        # 5. liquidation check on intraday extremes (before booking the close)
        adverse = np.where(units > 0, L[t], np.where(units < 0, H[t], C[t]))
        eq_worst = E + (units * (adverse - C[t - 1])).sum()
        mreq_worst = (np.abs(units) * adverse * maint).sum()
        if (units != 0).any() and eq_worst <= mreq_worst:
            liq[t] = True
            notional = (np.abs(units) * adverse).sum()
            E = max(eq_worst - notional * cfg.liq_penalty, 0.0)
            pnl_asset[t] = units * (adverse - C[t - 1])
            units = np.zeros(k)
            pa = np.zeros(k)
        else:
            E += pa.sum()
            pnl_asset[t] = pa
            # 3. funding on today's notional; 4. interest on free collateral
            notional = units * C[t]
            fund[t] = -(notional * F[t]).sum()
            im_used = (np.abs(notional) * im).sum()
            intr[t] = max(E - im_used, 0.0) * cfg.interest_apy / DAYS
            fund_frac[t] = fund[t] / E
            intr_frac[t] = intr[t] / E
            E += fund[t] + intr[t]
        if E <= 0:
            E = 0.0
            equity[t:] = 0.0
            held_w[t:] = 0.0
            break
        equity[t] = E
        held_w[t] = units * C[t] / E
        peak = max(peak, E)
        # drawdown kill: flatten at tomorrow's open, never re-enter
        if cfg.ladder_kill is not None and E / peak - 1 <= -cfg.ladder_kill and not killed:
            killed = True
            pending = np.zeros(k)
            killed_pending = True
        elif not killed:
            pending = W[t]
        elif killed and (units != 0).any():
            pending = np.zeros(k)
            killed_pending = True
    ret = pd.Series(equity, index=idx).pct_change().fillna(0.0)
    eq = pd.Series(equity, index=idx)
    years = max(len(idx) / DAYS, 1e-9)
    gross = pd.DataFrame(held_w, index=idx, columns=assets).abs().sum(axis=1)
    # Sharpe on EXCESS return over the collateral yield: a book that never
    # trades earns the 3.25% and must score zero, not infinity.
    excess = ret - cfg.interest_apy / DAYS
    excess.iloc[0] = 0.0
    sr = sharpe(excess, DAYS) if float(ret.std(ddof=1)) > 1e-5 else None
    out = {
        "net_sharpe": None if sr is None else round(sr, 3),
        "sharpe_total": None if sr is None else round(sharpe(ret, DAYS), 3),
        "cagr": round(cagr(eq / eq.iloc[0], DAYS), 4),
        "max_drawdown": round(max_drawdown(eq), 4),
        "total_return": round(float(eq.iloc[-1] / eq.iloc[0] - 1), 4),
        "ann_turnover": round(float(turnover.sum() / years), 2),
        "fees_annual": round(float(fee_frac.sum() / years), 4),
        "funding_annual": round(float(fund_frac.sum() / years), 4),
        "interest_annual": round(float(intr_frac.sum() / years), 4),
        "avg_gross_leverage": round(float(gross.mean()), 3),
        "max_gross_leverage": round(float(gross.max()), 3),
        "n_liquidations": int(liq.sum()),
        "n_days": int(len(idx)),
        "years": round(years, 2),
        "start": str(idx[0].date()), "end": str(idx[-1].date()),
        "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "killed": bool(killed),
        "worst_day": round(float(ret.min()), 4),
        "pct_positive_months": _pct_positive(ret, "M"),
        "pct_positive_quarters": _pct_positive(ret, "Q"),
    }
    out["_series"] = {"returns": ret, "excess": excess, "equity": eq,
                      "weights": pd.DataFrame(held_w, index=idx, columns=assets),
                      "pnl_asset": pd.DataFrame(pnl_asset, index=idx, columns=assets),
                      "fees": pd.Series(fees, index=idx), "funding": pd.Series(fund, index=idx),
                      "interest": pd.Series(intr, index=idx)}
    return out


def _pct_positive(ret: pd.Series, freq: str) -> float:
    rule = {"M": "ME", "Q": "QE"}[freq]
    g = (1 + ret).resample(rule).prod() - 1
    g = g[g != 0]
    return round(float((g > 0).mean()), 3) if len(g) else 0.0


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


# -------------------------------------------------------------- evaluation
def run_strategy(panel, strategy, params: dict, cfg: BacktestConfig, start=None, end=None) -> dict:
    targets = strategy(panel, **params)
    return run(panel, targets, cfg, start, end)


def _grid_points(grid: dict) -> list[dict]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])]


def walk_forward(panel, strategy, params: dict, cfg: BacktestConfig, grid: dict | None = None,
                 n_folds: int = 6, warmup_days: int = 730, embargo_days: int = 7,
                 dev_end: str = HOLDOUT_START, dev_start: str | None = None) -> dict:
    """Fold-by-fold evaluation on the DEV window.

    With ``grid``: for each fold pick the grid point maximising IS Sharpe on
    [dev_start, fold_start − embargo), then score the fold. Without: fixed
    params, labelled fixed_params=True (NOT out of sample).
    """
    closes = align(panel)
    idx = closes.index
    idx = idx[idx < pd.Timestamp(dev_end, tz="UTC")]
    if dev_start:
        idx = idx[idx >= pd.Timestamp(dev_start, tz="UTC")]
    if len(idx) <= warmup_days + n_folds * 30:
        raise ValueError("dev window too short for the requested folds")
    edges = np.linspace(warmup_days, len(idx), n_folds + 1, dtype=int)
    points = _grid_points(grid or {})
    # precompute full-history targets per grid point ONCE (signals are causal, so
    # a target on day t is the same whatever the run window)
    target_cache = {}
    for i, gp in enumerate(points):
        target_cache[i] = strategy(panel, **{**params, **gp})
    folds = []
    oos = []
    oos_x = []
    is_sr, oos_sr = [], []
    for f in range(n_folds):
        lo, hi = edges[f], edges[f + 1]
        f_start, f_end = idx[lo], idx[hi - 1] + pd.Timedelta(days=1)
        pick, pick_sr = 0, -np.inf
        if grid:
            is_end = f_start - pd.Timedelta(days=embargo_days)
            for i in range(len(points)):
                r = run(panel, target_cache[i], cfg, start=str(idx[0].date()), end=str(is_end.date()))
                sr = r["net_sharpe"] if r["net_sharpe"] is not None else -np.inf
                # ties → fewer trades
                if sr > pick_sr + 1e-9 or (abs(sr - pick_sr) <= 1e-9 and
                                           r["ann_turnover"] < folds_turn(folds, pick, target_cache, panel, cfg, idx, is_end)):
                    pick, pick_sr = i, sr
        r = run(panel, target_cache[pick], cfg, start=str(f_start.date()), end=str(f_end.date()))
        is_sr.append(pick_sr if grid else float("nan"))
        oos_sr.append(r["net_sharpe"] if r["net_sharpe"] is not None else 0.0)
        oos.append(r["_series"]["returns"])
        oos_x.append(r["_series"]["excess"])
        folds.append({"fold": f, "start": str(f_start.date()), "end": str(idx[hi - 1].date()),
                      "params": {**params, **points[pick]}, "is_sharpe": None if not grid else round(pick_sr, 3),
                      "oos_sharpe": r["net_sharpe"], "oos_return": r["total_return"],
                      "max_drawdown": r["max_drawdown"], "turnover": r["ann_turnover"],
                      "n_liquidations": r["n_liquidations"]})
    all_oos = pd.concat(oos)
    all_x = pd.concat(oos_x)
    eq = (1 + all_oos).cumprod()
    med_is = float(np.nanmedian(is_sr)) if grid else float("nan")
    med_oos = float(np.median(oos_sr))
    return {
        "strategy": getattr(strategy, "strategy_name", str(strategy)),
        "fixed_params": not bool(grid),
        "n_folds": len(folds),
        "oos_sharpe_median": round(med_oos, 3),
        "oos_sharpe_concat": round(sharpe(all_x, DAYS), 3) if float(all_x.std(ddof=1)) > 1e-5 else 0.0,
        "oos_sharpe_total": round(sharpe(all_oos, DAYS), 3) if float(all_oos.std(ddof=1)) > 1e-5 else 0.0,
        "oos_cagr": round(cagr(eq, DAYS), 4),
        "oos_max_drawdown": round(max_drawdown(eq), 4),
        "folds_positive": int(sum(1 for f in folds if f["oos_return"] > 0)),
        "wfe": round(med_oos / med_is, 3) if grid and med_is > 0 else None,
        "n_trials_this_call": len(points) * (len(folds) if grid else 1),
        "folds": folds,
        "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "_oos_returns": all_oos,
        "_oos_excess": all_x,
    }


def folds_turn(folds, pick, cache, panel, cfg, idx, is_end) -> float:
    """Turnover of the current pick on the IS window (tie-break helper)."""
    try:
        return run(panel, cache[pick], cfg, start=str(idx[0].date()), end=str(is_end.date()))["ann_turnover"]
    except Exception:  # noqa: BLE001
        return float("inf")


def cscv_pbo(returns: pd.DataFrame, n_blocks: int = 8) -> dict:
    """Probability of Backtest Overfitting via combinatorially symmetric
    cross-validation (Bailey, Borwein, Lopez de Prado, Zhu 2017).

    ``returns``: T × N daily returns of every registered trial. Split T into
    ``n_blocks`` blocks; for every half/half combination pick the best trial
    in-sample by Sharpe and record the relative rank of its out-of-sample
    Sharpe. PBO = share of combinations where that rank is below median.
    """
    R = returns.fillna(0.0).to_numpy()
    T, N = R.shape
    if N < 2 or T < n_blocks * 10:
        return {"pbo": None, "n_trials": N, "reason": "too few trials or bars"}
    blocks = np.array_split(np.arange(T), n_blocks)
    logits = []
    is_best, oos_best = [], []
    half = n_blocks // 2
    for combo in itertools.combinations(range(n_blocks), half):
        is_idx = np.concatenate([blocks[i] for i in combo])
        oos_idx = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        def sr(block):
            m = block.mean(axis=0)
            s = block.std(axis=0, ddof=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                out = np.where(s > 0, m / s, 0.0)
            return out
        sr_is = sr(R[is_idx])
        sr_oos = sr(R[oos_idx])
        b = int(np.argmax(sr_is))
        rank = (sr_oos < sr_oos[b]).sum() / (N - 1) if N > 1 else 0.5
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))
        is_best.append(sr_is[b])
        oos_best.append(sr_oos[b])
    logits = np.array(logits)
    slope = float(np.polyfit(is_best, oos_best, 1)[0]) if len(is_best) > 2 else float("nan")
    return {"pbo": round(float((logits < 0).mean()), 3), "n_trials": N, "n_combos": len(logits),
            "degradation_slope": round(slope, 3),
            "mean_oos_sr_of_is_best_daily": round(float(np.mean(oos_best)), 4)}


def dsr(returns: pd.Series, n_trials: int, trial_sr_std: float | None = None) -> dict:
    """Deflated Sharpe for a daily return stream against ``n_trials`` tries."""
    r = returns.dropna()
    if len(r) < 30 or r.std(ddof=1) == 0:
        return {"dsr": 0.0, "sr_daily": 0.0}
    sr_d = float(r.mean() / r.std(ddof=1))
    sk = float(r.skew())
    ku = float(r.kurt() + 3.0)
    p = deflated_sharpe(sr_d, n_trials=max(n_trials, 1), n_obs=len(r), skew=sk, kurt=ku,
                        trial_sr_std=trial_sr_std)
    return {"dsr": round(p, 4), "sr_daily": round(sr_d, 4), "sr_annual": round(sr_d * math.sqrt(DAYS), 3),
            "skew": round(sk, 3), "kurtosis": round(ku, 3), "n_obs": len(r), "n_trials": n_trials}


def stress(panel, strategy, params: dict, cfg: BacktestConfig, start=None, end=None) -> dict:
    """Same strategy under the three cost scenarios and two funding regimes."""
    from .specs import SCENARIOS
    out = {}
    targets = strategy(panel, **params)
    for c in SCENARIOS:
        for fm in ("kalshi", "proxy"):
            r = run(panel, targets, replace(cfg, cost=c, funding=fm), start, end)
            out[f"{c.name}/{fm}"] = {k: r[k] for k in ("net_sharpe", "cagr", "max_drawdown", "fees_annual",
                                                        "funding_annual", "n_liquidations")}
    return out
