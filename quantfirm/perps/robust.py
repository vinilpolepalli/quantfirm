"""Adversarial robustness checks for one strategy configuration.

A walk-forward Sharpe is one number from one path. These tests ask how much
of it is luck, exposure, or a fragile parameter:

  * block bootstrap of the daily return stream → confidence intervals on
    Sharpe, CAGR and max drawdown (stationary/circular blocks keep the
    autocorrelation that a plain bootstrap destroys)
  * parameter perturbation (±25% on every numeric parameter, one at a time)
    → does the result survive being slightly wrong?
  * regime split → performance in years where BTC rose vs fell, and in calm
    vs turbulent vol terciles
  * timing null → block-shuffle the strategy's own target weights in time
    (same exposure distribution, no timing) and place the real Sharpe in
    that distribution: the percentile is the evidence for timing skill as
    opposed to beta
  * Sharpe difference vs the benchmark → paired block bootstrap of the two
    daily excess-return streams

Everything runs on the DEV window only.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd

from ..metrics import cagr, max_drawdown, sharpe
from .backtest import BacktestConfig, DAYS, public, run, run_strategy
from .data import align
from .strategies import REGISTRY


def _ann_sharpe(x: np.ndarray) -> float:
    s = x.std(ddof=1)
    return float(x.mean() / s * math.sqrt(DAYS)) if s > 0 else 0.0


def block_bootstrap(returns: pd.Series, n_boot: int = 2000, block: int = 20, seed: int = 0,
                    rf_daily: float = 0.0) -> dict:
    """Circular block bootstrap of a daily return series."""
    r = returns.dropna().to_numpy()
    n = len(r)
    if n < block * 5:
        return {"error": "too short"}
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    srs, cagrs, mdds = np.empty(n_boot), np.empty(n_boot), np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        x = r[idx]
        srs[b] = _ann_sharpe(x - rf_daily)
        eq = np.cumprod(1 + x)
        years = n / DAYS
        cagrs[b] = eq[-1] ** (1 / years) - 1 if eq[-1] > 0 else -1.0
        peak = np.maximum.accumulate(eq)
        mdds[b] = float((eq / peak - 1).min())
    pct = lambda a: [round(float(np.percentile(a, q)), 4) for q in (5, 25, 50, 75, 95)]
    return {"n_boot": n_boot, "block": block, "n_obs": n,
            "sharpe_p5_25_50_75_95": pct(srs), "cagr_p5_25_50_75_95": pct(cagrs),
            "mdd_p5_25_50_75_95": pct(mdds),
            "p_sharpe_le_0": round(float((srs <= 0).mean()), 4),
            "p_cagr_le_0": round(float((cagrs <= 0).mean()), 4)}


def _perturb_value(v, frac: float, direction: int):
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        nv = int(round(v * (1 + direction * frac)))
        return max(1, nv) if nv != v else v + direction
    if isinstance(v, float):
        return v * (1 + direction * frac)
    if isinstance(v, tuple):
        return tuple(_perturb_value(x, frac, direction) for x in v)
    return v


def perturbation(panel, strategy, params: dict, cfg: BacktestConfig, start, end,
                 frac: float = 0.25) -> dict:
    """±frac on each numeric parameter, one at a time. Reports the spread of
    Sharpe across all perturbations relative to the base."""
    import inspect
    sig = inspect.signature(strategy)
    base_params = {k: v.default for k, v in sig.parameters.items()
                   if v.default is not inspect.Parameter.empty and k not in ("panel", "kw")}
    base_params.update(params)
    base = public(run_strategy(panel, strategy, params, cfg, start, end))
    rows = []
    for k, v in base_params.items():
        if k in ("long_only", "seed", "funding") or isinstance(v, (bool, str, dict)) or v is None:
            continue
        for d in (-1, +1):
            nv = _perturb_value(v, frac, d)
            if nv == v:
                continue
            try:
                r = public(run_strategy(panel, strategy, {**params, k: nv}, cfg, start, end))
            except Exception as e:  # noqa: BLE001
                rows.append({"param": k, "value": str(nv), "error": str(e)[:80]})
                continue
            rows.append({"param": k, "value": str(nv), "net_sharpe": r["net_sharpe"], "cagr": r["cagr"],
                         "max_drawdown": r["max_drawdown"]})
    srs = [x["net_sharpe"] for x in rows if x.get("net_sharpe") is not None]
    return {"base_sharpe": base["net_sharpe"], "n_perturbations": len(rows),
            "min_sharpe": round(min(srs), 3) if srs else None,
            "median_sharpe": round(float(np.median(srs)), 3) if srs else None,
            "max_sharpe": round(max(srs), 3) if srs else None,
            "collapse_ratio": round(min(srs) / base["net_sharpe"], 3) if srs and base["net_sharpe"] else None,
            "rows": rows}


def regime_split(returns: pd.Series, panel, cfg: BacktestConfig, ref: str = "btc") -> dict:
    """Sharpe/return by BTC up-years vs down-years and by BTC vol tercile."""
    rf = cfg.interest_apy / DAYS
    x = returns - rf
    ref_close = panel[ref]["close"].reindex(returns.index).ffill()
    yearly_ref = ref_close.groupby(ref_close.index.year).agg(["first", "last"])
    up_years = set(yearly_ref.index[yearly_ref["last"] > yearly_ref["first"]])
    is_up = pd.Series([y in up_years for y in returns.index.year], index=returns.index)
    vol = ref_close.pct_change().rolling(30).std()
    terc = pd.qcut(vol.rank(method="first"), 3, labels=["calm", "mid", "turbulent"])
    out = {}
    for name, mask in (("btc_up_years", is_up), ("btc_down_years", ~is_up)):
        seg = returns[mask.to_numpy()]
        out[name] = {"n_days": int(len(seg)), "sharpe": round(_ann_sharpe((seg - rf).to_numpy()), 3) if len(seg) > 30 else None,
                     "ann_return": round(float((1 + seg).prod() ** (DAYS / max(len(seg), 1)) - 1), 4) if len(seg) else None}
    for lab in ("calm", "mid", "turbulent"):
        seg = returns[(terc == lab).to_numpy()]
        out[f"vol_{lab}"] = {"n_days": int(len(seg)), "sharpe": round(_ann_sharpe((seg - rf).to_numpy()), 3) if len(seg) > 30 else None}
    return out


def timing_null(panel, strategy, params: dict, cfg: BacktestConfig, start, end,
                n_null: int = 200, block: int = 30, seed: int = 0) -> dict:
    """Shuffle the strategy's own target weights in time (block-wise) and
    re-run the simulator. Same exposure distribution, no timing. The real
    Sharpe's percentile in the null distribution is the timing-skill evidence."""
    targets = strategy(panel, **params)
    real = run(panel, targets, cfg, start, end)
    real_sr = real["net_sharpe"] if real["net_sharpe"] is not None else 0.0
    rng = np.random.default_rng(seed)
    closes = align(panel)
    T = targets.reindex(closes.index).ffill().fillna(0.0)
    mask = (T.index >= pd.Timestamp(start, tz="UTC")) & (T.index < pd.Timestamp(end, tz="UTC"))
    W = T[mask].to_numpy()
    n = len(W)
    srs = []
    for _ in range(n_null):
        n_blocks = int(math.ceil(n / block))
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        shuffled = T.copy()
        shuffled.loc[mask] = W[idx]
        r = run(panel, shuffled, cfg, start, end)
        srs.append(r["net_sharpe"] if r["net_sharpe"] is not None else 0.0)
    srs = np.array(srs)
    return {"real_sharpe": round(real_sr, 3), "n_null": n_null, "block_days": block,
            "null_sharpe_mean": round(float(srs.mean()), 3), "null_sharpe_p95": round(float(np.percentile(srs, 95)), 3),
            "percentile_of_real": round(float((srs < real_sr).mean()), 3),
            "excess_over_null_mean": round(real_sr - float(srs.mean()), 3)}


def sharpe_difference(a: pd.Series, b: pd.Series, n_boot: int = 2000, block: int = 20,
                      rf_daily: float = 0.0, seed: int = 1) -> dict:
    """Paired circular block bootstrap of Sharpe(a) − Sharpe(b)."""
    df = pd.concat({"a": a, "b": b}, axis=1).dropna()
    x, y = df["a"].to_numpy() - rf_daily, df["b"].to_numpy() - rf_daily
    n = len(x)
    if n < block * 5:
        return {"error": "too short"}
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        diffs[i] = _ann_sharpe(x[idx]) - _ann_sharpe(y[idx])
    point = _ann_sharpe(x) - _ann_sharpe(y)
    return {"sharpe_a": round(_ann_sharpe(x), 3), "sharpe_b": round(_ann_sharpe(y), 3),
            "diff": round(point, 3), "diff_p5": round(float(np.percentile(diffs, 5)), 3),
            "diff_p95": round(float(np.percentile(diffs, 95)), 3),
            "p_a_gt_b": round(float((diffs > 0).mean()), 4), "corr": round(float(np.corrcoef(x, y)[0, 1]), 3)}


def full_report(panel, strategy, params: dict, cfg: BacktestConfig, start: str, end: str,
                benchmark: str = "vol_target_hold", n_boot: int = 2000, n_null: int = 200) -> dict:
    base = run_strategy(panel, strategy, params, cfg, start, end)
    bench_params = {"target_vol": params.get("target_vol", 0.12)} if "target_vol" in params else {}
    bench = run_strategy(panel, REGISTRY[benchmark], bench_params, cfg, start, end)
    rf = cfg.interest_apy / DAYS
    ret, bret = base["_series"]["returns"], bench["_series"]["returns"]
    return {
        "strategy": getattr(strategy, "strategy_name", str(strategy)), "params": params,
        "window": [start, end], "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "base": public(base), "benchmark": benchmark, "benchmark_metrics": public(bench),
        "bootstrap": block_bootstrap(ret, n_boot=n_boot, rf_daily=rf),
        "perturbation": perturbation(panel, strategy, params, cfg, start, end),
        "regime": regime_split(ret, panel, cfg),
        "timing_null": timing_null(panel, strategy, params, cfg, start, end, n_null=n_null),
        "vs_benchmark": sharpe_difference(ret, bret, n_boot=n_boot, rf_daily=rf),
    }
