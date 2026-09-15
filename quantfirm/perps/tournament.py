"""Pre-registered tournament for the perps desk.

The trial set below is frozen BEFORE the run and every grid point counts
toward N for the deflated Sharpe. Protocol (docs/FIRM.md §2, adapted to
daily bars):

  * DEV window only (before 2025-07-01). The holdout is opened once, by the
    judge, through ``cli holdout``; this module never reads it.
  * Walk-forward with parameter selection: per fold, the grid point with the
    best in-sample Sharpe (strictly before the fold, 7-day embargo) is scored
    on the fold. The concatenated OOS stream is what a strategy is judged on.
  * CSCV probability of backtest overfitting across every registered
    configuration plus the benchmark (vol-scaled long-only) as trial N+1.
  * Deflated Sharpe of the best candidate against N registered trials with
    the empirical cross-trial dispersion.
  * Hard constraints: OOS Sharpe must beat the benchmark's; ≥ 4 of 6 folds
    positive; OOS max drawdown ≤ 25%; zero liquidations; survives the stress
    cost scenario (1.5× fees + proxy funding) with positive OOS return.

Approval cost: taker tier 0 (12 bps + 2.5 bps half-spread). Base funding:
Kalshi's own history (≈0). Stress: Binance funding through Kalshi's rule.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import replace

import numpy as np
import pandas as pd

from .backtest import BacktestConfig, cscv_pbo, dsr, public, run, run_strategy, walk_forward
from .data import HOLDOUT_START, load_panel
from .specs import RESEARCH_UNIVERSE, STRESS, TAKER_T0
from .strategies import REGISTRY

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "research", "kalshi_perps")

DEV_START = "2016-06-01"
WARMUP_DAYS = 550          # folds begin ~2018-01
N_FOLDS = 6

# ---- frozen trial registry (edit = new tournament, bump the version) ----
TOURNAMENT_VERSION = "2026-09-15.2-campaign"
TRIALS: dict[str, dict] = {
    # family: {"params": fixed, "grid": {param: [values]}}
    "tsmom": {"params": {"target_vol": 0.12},
              "grid": {"lookbacks": [(21, 63, 126, 252), (63, 126, 252), (126, 252), (21, 63)]}},
    "ma_trend": {"params": {"target_vol": 0.12},
                 "grid": {"pairs": [((10, 50), (20, 100), (50, 200)), ((20, 100), (50, 200)), ((50, 200),)]}},
    "breakout": {"params": {"target_vol": 0.12},
                 "grid": {"entry": [55, 100, 20], "exit_": [20]}},
    "trend_ensemble": {"params": {"target_vol": 0.12}, "grid": {}},
    "trend_long_only": {"params": {"target_vol": 0.12}, "grid": {}},
    "gold_silver_ratio": {"params": {"target_vol": 0.08}, "grid": {}},
}
# breakout (20, 20) would be a degenerate pair; the grid generator makes exit_=20 for all three.
CONTROLS = ("vol_target_hold", "buy_hold", "flat", "coin_flip")
BENCHMARK = "vol_target_hold"


def collect_trials() -> dict:
    """Core trials plus every family module's TRIALS (agents register there)."""
    from .strategies import family_trials, load_all
    load_all()
    merged = dict(TRIALS)
    for k, v in family_trials().items():
        merged[k] = {"params": dict(v.get("params") or {}), "grid": dict(v.get("grid") or {})}
    return merged


def _grid_points(grid: dict) -> list[dict]:
    import itertools
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, v)) for v in itertools.product(*[grid[k] for k in keys])]


def n_registered_trials(trials: dict | None = None) -> int:
    """Configurations declared in the trial set. The registry may be larger:
    every ad-hoc backtest an agent ran also counts (see registry.py)."""
    trials = trials if trials is not None else collect_trials()
    return sum(len(_grid_points(t["grid"])) for t in trials.values())


def run_tournament(universe=RESEARCH_UNIVERSE, cfg: BacktestConfig = BacktestConfig(),
                   out_dir: str = OUT_DIR, log=print) -> dict:
    from .registry import count_unique as registry_count, record as registry_record
    panel = load_panel(universe)
    trials = collect_trials()
    n_declared = n_registered_trials(trials)
    # N for the deflated Sharpe = everything ever tried, not just this run's grid
    n_trials = max(n_declared, registry_count() + n_declared)
    log(f"tournament {TOURNAMENT_VERSION}: universe={list(universe)} declared={n_declared} "
        f"registry_total={n_trials} cost={cfg.cost.name} funding={cfg.funding}")
    results: dict[str, dict] = {}
    oos_streams: dict[str, pd.Series] = {}
    matrix: dict[str, pd.Series] = {}

    # 1. controls on the dev window (fixed, no selection)
    for name in CONTROLS:
        r = run_strategy(panel, REGISTRY[name], {}, cfg, start=None, end=HOLDOUT_START)
        results[name] = {"kind": "control", "dev": public(r)}
        matrix[name] = r["_series"]["excess"]
        log(f"  control {name:<18} SR {r['net_sharpe']} CAGR {r['cagr']} MDD {r['max_drawdown']}")
    # benchmark OOS stream = its fixed-param fold report (nothing to select)
    bench_wf = walk_forward(panel, REGISTRY[BENCHMARK], {}, cfg, grid=None, n_folds=N_FOLDS,
                            warmup_days=WARMUP_DAYS, dev_start=DEV_START)
    results[BENCHMARK]["walk_forward"] = {k: v for k, v in bench_wf.items() if not k.startswith("_")}
    oos_streams[BENCHMARK] = bench_wf["_oos_excess"]

    # 2. candidates: walk-forward with selection + every grid point on dev for CSCV
    for fam, spec in trials.items():
        if fam not in REGISTRY:
            log(f"  {fam}: not in registry, skipped")
            continue
        fn = REGISTRY[fam]
        wf = walk_forward(panel, fn, spec["params"], cfg, grid=spec["grid"] or None, n_folds=N_FOLDS,
                          warmup_days=WARMUP_DAYS, dev_start=DEV_START)
        oos_streams[fam] = wf["_oos_excess"]
        st = {}
        for gp in _grid_points(spec["grid"]):
            params = {**spec["params"], **gp}
            key = fam + ("" if not gp else ":" + ",".join(f"{k}={v}" for k, v in gp.items()))
            r = run_strategy(panel, fn, params, cfg, start=None, end=HOLDOUT_START)
            matrix[key] = r["_series"]["excess"]
            st[key] = public(r)
            registry_record(fam, params, "dev", public(r), source="tournament")
        # stress: the selected (last fold) params under 1.5× cost + proxy funding
        sel = wf["folds"][-1]["params"]
        stress_cfg = replace(cfg, cost=STRESS, funding="proxy")
        rs = run_strategy(panel, fn, sel, stress_cfg, start=None, end=HOLDOUT_START)
        results[fam] = {"kind": "candidate",
                        "walk_forward": {k: v for k, v in wf.items() if not k.startswith("_")},
                        "dev_fixed": st,
                        "stress_dev": public(rs),
                        "oos_vs_benchmark": round(wf["oos_sharpe_concat"] - bench_wf["oos_sharpe_concat"], 3)}
        log(f"  {fam:<18} OOS SR {wf['oos_sharpe_concat']:>6}  folds+ {wf['folds_positive']}/{wf['n_folds']}  "
            f"OOS MDD {wf['oos_max_drawdown']:>7}  CAGR {wf['oos_cagr']:>7}  stress SR {rs['net_sharpe']}")

    # 3. CSCV across every registered configuration + the benchmark
    M = pd.DataFrame(matrix).dropna(how="all")
    M = M.loc[M.index >= pd.Timestamp("2018-01-01", tz="UTC")]
    cand_cols = [c for c in M.columns if c.split(":")[0] in trials] + [BENCHMARK]
    pbo = cscv_pbo(M[cand_cols], n_blocks=8)
    trial_sr_std = float((M[cand_cols].mean() / M[cand_cols].std(ddof=1)).std(ddof=1))

    # 4. rank candidates on OOS Sharpe; DSR of the best against N
    bench_sr = bench_wf["oos_sharpe_concat"]
    ranked = sorted(((fam, results[fam]["walk_forward"]["oos_sharpe_concat"]) for fam in trials
                     if fam in results), key=lambda kv: -kv[1])
    verdicts = {}
    for fam, sr in ranked:
        wf = results[fam]["walk_forward"]
        d = dsr(oos_streams[fam], n_trials=n_trials, trial_sr_std=trial_sr_std)
        gates = {
            "beats_benchmark_oos": sr > bench_sr,
            "folds_positive_ge_4": wf["folds_positive"] >= 4,
            "oos_mdd_le_25pct": wf["oos_max_drawdown"] >= -0.25,
            "no_liquidations": all(f["n_liquidations"] == 0 for f in wf["folds"]),
            "stress_positive": results[fam]["stress_dev"]["total_return"] > 0,
            "dsr_ge_0.95": d["dsr"] >= 0.95,
            "pbo_le_0.10": (pbo.get("pbo") is not None and pbo["pbo"] <= 0.10),
        }
        verdicts[fam] = {"oos_sharpe": sr, "dsr": d, "gates": gates,
                         "score": sr if all(gates.values()) else 0.0}
    out = {
        "version": TOURNAMENT_VERSION,
        "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "universe": list(universe),
        "dev_window": [DEV_START, HOLDOUT_START], "warmup_days": WARMUP_DAYS, "n_folds": N_FOLDS,
        "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "rebalance": {"every_days": cfg.rebalance_every, "band": cfg.rebalance_band},
        "n_registered_trials": n_trials,
        "n_declared_this_run": n_declared,
        "trials": {k: {"params": v["params"], "grid": {kk: [str(x) for x in vv] for kk, vv in v["grid"].items()}}
                   for k, v in trials.items()},
        "benchmark": BENCHMARK, "benchmark_oos_sharpe": bench_sr,
        "pbo": pbo, "trial_sr_std_daily": round(trial_sr_std, 5),
        "ranked": ranked, "verdicts": verdicts,
        "results": results,
        "holdout": "SEALED — not read by this module",
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "tournament.json"), "w") as f:
        json.dump(out, f, indent=1, default=_json_default)
    with open(os.path.join(out_dir, "tournament.md"), "w") as f:
        f.write(render_md(out))
    log(f"wrote {out_dir}/tournament.json and tournament.md")
    return out


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Timestamp, dt.datetime)):
        return o.isoformat()
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def render_md(out: dict) -> str:
    L = []
    L.append(f"# Kalshi perps tournament — {out['version']}\n")
    L.append(f"Ran {out['ran_at']}. Universe {out['universe']}. Dev window {out['dev_window'][0]} → "
             f"{out['dev_window'][1]} (folds start after {out['warmup_days']} warmup days, "
             f"{out['n_folds']} folds). Cost `{out['cost_model']}`, funding `{out['funding_mode']}`, "
             f"rebalance every {out['rebalance']['every_days']}d with a {out['rebalance']['band']:.0%} band. "
             f"**{out['n_registered_trials']} registered trials.** Holdout: {out['holdout']}.\n")
    L.append("## Walk-forward (parameters selected in-sample per fold, scored out of sample)\n")
    L.append("| family | OOS Sharpe | OOS CAGR | OOS max DD | folds + | WFE | vs bench | stress SR | DSR | gates |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    bench = out["results"][out["benchmark"]]["walk_forward"]
    L.append(f"| **{out['benchmark']}** (benchmark) | {bench['oos_sharpe_concat']} | {bench['oos_cagr']:.1%} | "
             f"{bench['oos_max_drawdown']:.1%} | {bench['folds_positive']}/{bench['n_folds']} | — | 0 | — | — | — |")
    for fam, sr in out["ranked"]:
        r = out["results"][fam]
        wf = r["walk_forward"]
        v = out["verdicts"][fam]
        failed = [g for g, ok in v["gates"].items() if not ok]
        L.append(f"| {fam} | {wf['oos_sharpe_concat']} | {wf['oos_cagr']:.1%} | {wf['oos_max_drawdown']:.1%} | "
                 f"{wf['folds_positive']}/{wf['n_folds']} | {wf['wfe'] if wf['wfe'] is not None else '—'} | "
                 f"{r['oos_vs_benchmark']:+} | {r['stress_dev']['net_sharpe']} | {v['dsr']['dsr']} | "
                 f"{'PASS' if not failed else 'FAIL: ' + ', '.join(failed)} |")
    L.append("")
    L.append(f"CSCV probability of backtest overfitting across {out['pbo'].get('n_trials')} configurations "
             f"(+ benchmark): **PBO = {out['pbo'].get('pbo')}**, degradation slope {out['pbo'].get('degradation_slope')}.\n")
    L.append("## Controls (fixed, dev window)\n")
    L.append("| control | Sharpe | CAGR | max DD | turnover/yr | fees/yr | interest/yr |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for c in CONTROLS:
        d = out["results"][c]["dev"]
        L.append(f"| {c} | {d['net_sharpe']} | {d['cagr']:.1%} | {d['max_drawdown']:.1%} | {d['ann_turnover']} | "
                 f"{d['fees_annual']:.2%} | {d['interest_annual']:.2%} |")
    L.append("")
    L.append("## Per-fold detail\n")
    for fam, _ in out["ranked"]:
        L.append(f"### {fam}\n")
        L.append("| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |")
        L.append("|---:|---|---|---:|---:|---:|---:|---:|")
        for f in out["results"][fam]["walk_forward"]["folds"]:
            L.append(f"| {f['fold']} | {f['start']} → {f['end']} | `{_short(f['params'])}` | "
                     f"{f['is_sharpe'] if f['is_sharpe'] is not None else '—'} | {f['oos_sharpe']} | "
                     f"{f['oos_return']:+.1%} | {f['max_drawdown']:.1%} | {f['turnover']} |")
        L.append("")
    L.append("## Reading this\n")
    L.append("* Sharpe ratios are on EXCESS return over the 3.25% collateral yield, so an idle book scores 0.")
    L.append("* A family passes only if every gate holds; the score is otherwise exactly 0 (docs/FIRM.md §2).")
    L.append("* Numbers are on PROXY histories (Coinbase spot, Yahoo futures) with Kalshi's fee tier 0 and "
             "its near-zero funding; Kalshi perps themselves have three months of history.")
    L.append("* The holdout (2025-07-01 →) has not been read. `python -m quantfirm.perps.cli holdout` opens it "
             "once, for one family, and records that it did.")
    return "\n".join(L) + "\n"


def _short(p: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in p.items() if k != "target_vol")
