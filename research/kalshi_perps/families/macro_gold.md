# macro_gold — macro-conditioned gold/silver sleeve

Designer report 2026-09-15; code `quantfirm/perps/families/macro_gold.py`. Universe btc, eth, gold, silver; dev only; taker tier 0, Kalshi funding, weekly check, 3% band, defaults untouched.

## 1. Hypothesis, mechanism, evidence

Gold's drivers are US real yields and the dollar, and both trend at 1–3 month horizons, so a metals sleeve that is long only while the 60-day DXY trend is down AND the 60-day TIP trend is up (falling real yields) should keep gold's up-months, skip part of its drawdowns and beat an always-long sleeve at the same risk budget. Variants: the OR gate; a VIX-spike overlay on gold in both signs (haven bid vs dash-for-cash); a symmetric long/short score (short metals when dollar and real yields both rise). btc/eth stay at the plain vol-targeted long weight, so on four assets the family is the benchmark plus a gated metals sleeve and any difference is the sleeve. Evidence: Erb & Harvey 2013 "The Golden Dilemma" (FAJ; real gold price mean-reverts); O'Connor, Lucey, Batten & Baur 2015 survey (IRFA; gold vs real yields and vs the dollar, with Capie–Mills–Wood 2005 and Pukthuanthong–Roll 2011); Moskowitz–Ooi–Pedersen 2012 (JFE; gold/silver trend 1985–2009); Brooks 2017 "A Half Century of Macro Momentum" (AQR); Baur & Lucey 2010 and Baur & McDermott 2010 (gold's short-lived safe-haven effect).

## 2. Data and causality

`load_aux("macro")` columns dxy, tip, vix (us10y unused). Holiday NaNs forward-filled on the series' own trading-day index; 60-trading-day % changes and a rolling 504-day 0.90 VIX quantile (min 252 obs) computed there, reindexed to the price calendar, forward-filled over weekends and shifted one day: the weight decided at close t uses macro data through t−1 and fills at t+1's open. No full-sample statistics; nothing after 2025-07-01 is read by the strategy. Truncation test: weight difference 0.0 on all five variants; `tests.test_perps` green (38). Disclosure: one post-hoc diagnostic printed calendar-2025 gold/silver returns, which include H2-2025; the cell was discarded, no decision followed (all registered runs were already complete).

## 3. Registered grid (verbatim, written before the first run)

```python
TRIALS = {"macro_gold": {
    "params": {"target_vol": 0.12, "lookback": 60, "vix_window": 504, "vix_pct": 0.9},
    "grid": {"variant": ["and", "or", "and_vix_haven", "and_vix_cut", "score"]}}}
```

Sixth configuration: the selected variant on `--universe gold,silver` (universe-blind registry key, shares `c7d6ce71a435`). Control, not a trial: `vol_target_hold` 0.12 on gold,silver (existing key `a1e554fa54c5`). Pre-committed selection rule: last fold's variant → `and_vix_cut`. Nothing tuned after results. Registry: 9 rows, 4 new unique keys (`score` was never selected in a fold, so the CLI wrote no row for it; it stays in `TRIALS` and counts toward N).

## 4. Walk-forward (n_trials_this_call 30)

| fold | window | variant | IS SR | OOS SR | OOS ret | DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | or | 3.011 | -0.319 | -0.0121 | -0.1629 | 9.27 |
| 1 | 2019-03-09 → 2020-06-11 | and_vix_haven | 1.564 | 0.997 | 0.1932 | -0.1281 | 8.9 |
| 2 | 2020-06-12 → 2021-09-15 | or | 1.442 | 2.095 | 0.4229 | -0.0735 | 3.4 |
| 3 | 2021-09-16 → 2022-12-20 | and | 1.545 | -0.494 | -0.0014 | -0.0771 | 0.26 |
| 4 | 2022-12-21 → 2024-03-25 | and | 1.201 | 1.733 | 0.3056 | -0.0514 | 4.77 |
| 5 | 2024-03-26 → 2025-06-30 | and_vix_cut | 1.28 | 0.669 | 0.1176 | -0.0739 | 3.45 |

oos_sharpe_concat **0.881** (benchmark 1.13), oos_sharpe_median 0.833, oos_cagr 0.1251, oos_max_drawdown -0.1629, folds_positive 4/6, wfe 0.558, no liquidations. Four variants in six folds: not separable in-sample.

## 5. Fixed dev run, `and_vix_cut`, 2018-01-01 → 2025-06-30

net_sharpe 0.758, sharpe_total 1.087, cagr 0.1078, max_drawdown -0.154, total_return 1.1547, ann_turnover 3.81, fees_annual 0.0055, avg_gross_leverage 0.246, n_liquidations 0, worst_day -0.0577.

by_year: 2018 -0.0854, 2019 0.1493, 2020 0.2595, 2021 0.1435, 2022 -0.0397, 2023 0.1891, 2024 0.2141, 2025 0.0267.

Stress (net_sharpe/cagr/max_drawdown): taker_t0/kalshi 0.758/0.1078/-0.154; taker_t0/proxy 0.609/0.0917/-0.154; maker_t0/kalshi 0.794/0.1116/-0.1531; maker_t0/proxy 0.645/0.0955/-0.1531; stress_1p5x/kalshi 0.716/0.1032/-0.1548; stress_1p5x/proxy 0.576/0.0882/-0.1548. Proxy funding costs 0.0139/yr, stress fees 0.0088/yr.

**Metals-only contribution** (`--universe gold,silver`, same params, 2018-01-02 → 2025-06-30): net_sharpe **-0.088**, cagr 0.0259, max_drawdown -0.0685, ann_turnover 5.18, fees_annual 0.0075, avg_gross_leverage 0.142; every year between -0.0132 (2021) and 0.031 (2020); stress net_sharpe taker_t0 -0.088, maker_t0 -0.004, stress_1p5x -0.162 (kalshi = proxy: no metals funding proxy). The sleeve earned less than the 3.25% collateral yield: trading P&L net of fees about zero. Control, always-long metals: net_sharpe 0.779, cagr 0.1311, max_drawdown -0.1334. Why: the gold gate was on 33%/43%/43%/11% of days in 2019/2023/2024/2025H1 while gold rose 0.186/0.121/0.274/0.239, and on 28% of 2021 while gold fell 0.060 — the dollar/real-yield regime did not separate gold's good years from its bad ones in this sample.

## 6. `robust` (n_boot 500, n_null 60)

Bootstrap Sharpe p5/p50/p95 0.0377/0.752/1.4587 (p_sharpe_le_0 0.048); CAGR 0.0318/0.1075/0.1848; MDD -0.2633/-0.1556/-0.0971. Perturbation (8 runs): min 0.656, median 0.732, max 0.826, collapse_ratio 0.865 (worst target_vol 0.15; vix_pct 1.125 is clipped to 0.99 in code). Timing null: real 0.758, null mean 0.732, p95 0.977, percentile_of_real 0.583, excess_over_null_mean 0.026. Regime: btc_up_years 1.294, btc_down_years -1.224, vol_calm 1.906, vol_mid 0.241, vol_turbulent 0.279. vs benchmark: sharpe_a 0.757, sharpe_b 0.94, diff -0.183 (p5 -0.562, p95 0.13), **p_a_gt_b 0.18**, corr 0.821.

## 7. Verdict

**FAIL** — beats_benchmark_oos (0.881 < 1.13; p_a_gt_b 0.18), no timing skill (null percentile 0.583), metals sleeve alone negative excess Sharpe (-0.088) at a fifth of the always-long control's return (cagr 0.0259 vs 0.1311); passed folds 4/6, OOS DD -0.1629, 0 liquidations, stress return > 0 (all from the crypto sleeve); DSR and PBO are the referee's.

## 8. Next, and why not run

(i) Invert the premise: gold's 2019–2025 gains came against the dollar/real-yield gate, so "gold up while DXY and real yields up" (official-sector bid) may be the state to hold — a new hypothesis, not a variant. (ii) Continuous macro tilts in [0.5, 1] instead of a 0/1 gate, so the sleeve is never fully off and whipsaw (turnover 5.18, fees 0.0075/yr) shrinks. (iii) A VIX overlay faster than the weekly check (cadence hypothesis; `rebalance_every` would change). Each is a new registered trial raising everyone's deflated-Sharpe bar; the grid is spent and its answer is clear.
