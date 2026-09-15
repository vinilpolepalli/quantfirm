# crash_filter_beta — vol-targeted long book with a crash filter

## 1. Hypothesis, mechanism, evidence

The benchmark's (`vol_target_hold`) losses sit in a few deep legs (2018, 2022). The incumbent's MA/TSMOM/breakout gate removes them but trades 3.8x/yr, and whipsaw plus 24–29 bps round trips eat the saving. A depth trigger — flat when close is more than `exit_depth` below its trailing `high_window`-day high — fires only in genuine crashes, so it should trade far less yet still sidestep 2018/2022-style legs. Mechanism: daily, per-asset, long-only port of `quantfirm/strategies/drawdown_filter.py`; hysteretic re-entry (>= 10 days flat, drawdown healed to within `reenter_depth` of the trailing high, 30-day return >= 0); optional vol-spike leg (7-day return <= mom_exit and 7-day vol > vol_mult x 90-day median); per-asset states sized by `vol_target` (0.12). Evidence: Kaminski & Lo (2014) "When Do Stop-Loss Rules Stop Losses?", J. Financial Markets (stops pay under positive autocorrelation); Han, Zhou & Zhu (2016) "Taming Momentum Crashes: A Simple Stop-Loss Strategy", SSRN 2407199; Daniel & Moskowitz (2016) "Momentum Crashes", JFE; Faber (2007), SSRN 962461; the in-house hourly reference above (overlapping years, so supportive, not independent).

## 2. Data and causality

Daily closes only, `D.load_panel(("btc","eth","gold","silver"))` (Coinbase spot, Yahoo front-month futures); no aux series. Each asset's state machine runs on its own bars (metals skip weekends) using rolling windows and positive-lag `pct_change`; the state at t uses rows <= t. States are reindexed to the union calendar, forward-filled over metals holidays, clipped at 0, then sized; the backtester executes the close-t decision at t+1's open. Dev window only. `tests.test_perps`: 38 tests OK.

Disclosed checks (no returns, no registry rows): pre-registration breach counts per depth — gold never breaches 0.20/0.30 below a 60/120-day high, silver rarely — motivated the metals variant; post-registration I verified preset == explicit-numeric weights and counted exits since 2018 (d30_w60: BTC 7, ETH 12, gold 0, silver 1; d20_w60: 16/17/0/3).

## 3. Registered grid (verbatim)

```python
TRIALS = {
    "crash_filter_beta": {
        "params": {"target_vol": 0.12},
        "grid": {"variant": ["d20_w60", "d20_w120", "d30_w60", "d30_w120", "d30_w60_spike", "d30_w60_m12"]},
    }
}
```

variant = (exit_depth, high_window): d20_w60 (0.20, 60), d20_w120 (0.20, 120), d30_w60 (0.30, 60), d30_w120 (0.30, 120); d30_w60_spike adds the vol-spike leg (mom_exit -0.15, vol_mult 1.6); d30_w60_m12 uses depth 0.12 for gold/silver. Fixed: reenter_depth 0.05 (scaled with the asset's depth), min_flat 10, reenter_mom_lb 30. A-priori selection rule: the last fold's IS pick goes to backtest/robust. Nothing changed after seeing results.

## 4. Walk-forward (dev 2016-06-01 ->, 6 folds, warmup 550, taker_t0, Kalshi funding)

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 -> 2019-03-08 | d30_w60_m12 | 2.796 | 0.019 | 0.0386 | -0.1561 | 3.06 |
| 1 | 2019-03-09 -> 2020-06-11 | d30_w120 | 1.841 | 0.611 | 0.1422 | -0.1961 | 2.68 |
| 2 | 2020-06-12 -> 2021-09-15 | d30_w60_m12 | 1.59 | 2.033 | 0.3897 | -0.0625 | 2.54 |
| 3 | 2021-09-16 -> 2022-12-20 | d30_w60_m12 | 1.631 | -1.08 | -0.0575 | -0.1277 | 2.16 |
| 4 | 2022-12-21 -> 2024-03-25 | d20_w60 | 1.324 | 2.036 | 0.4249 | -0.0947 | 2.79 |
| 5 | 2024-03-26 -> 2025-06-30 | d20_w60 | 1.457 | 1.58 | 0.2753 | -0.0665 | 2.5 |

oos_sharpe_concat **1.011** (benchmark 1.131), oos_sharpe_median 1.095, oos_sharpe_total 1.308, oos_cagr 0.1467, oos_max_drawdown -0.1961, folds_positive 5/6, wfe 0.68, 0 liquidations, n_trials_this_call 36. The IS pick changed three times; modal pick d30_w60_m12, last-fold pick d20_w60.

## 5. Fixed dev run, d20_w60 (2018-01-01 -> 2025-06-30, `--yearly --stress`)

net_sharpe 1.169, cagr 0.1643, max_drawdown -0.139, total_return 2.1294, ann_turnover 2.07, fees_annual 0.003, n_liquidations 0, worst_day -0.04 (benchmark, same window: 0.94 / 0.1545 / -0.2115 / turnover 1.68).

by_year: 2018 -0.0133, 2019 0.271, 2020 0.2571, 2021 0.1032, 2022 -0.0032, 2023 0.2463, 2024 0.3045, 2025 0.1102.

Stress (net_sharpe / cagr / max_drawdown): taker_t0/kalshi 1.169 / 0.1643 / -0.139; taker_t0/proxy 1.052 / 0.1499 / -0.1407; maker_t0/kalshi 1.187 / 0.1665 / -0.1385; maker_t0/proxy 1.071 / 0.1521 / -0.1402; stress_1p5x/kalshi 1.152 / 0.1622 / -0.1395; stress_1p5x/proxy 1.036 / 0.1479 / -0.1412; 0 liquidations in all six.

Caveat: chosen with hindsight (folds 4–5), so not out of sample — section 4 is.

## 6. `robust` (d20_w60 as `exit_depth 0.2, high_window 60`; `--n-boot 500 --n-null 60`)

Bootstrap Sharpe p5/p50/p95 0.4613 / 1.1592 / 1.7711; cagr 0.0783 / 0.1632 / 0.2414; mdd -0.2211 / -0.1326 / -0.0909; p_sharpe_le_0 0.0. Perturbation (12 rows): min 1.031 (exit_depth 0.15), median 1.131, max 1.191, collapse_ratio 0.882. Timing null: real 1.169, null mean 0.742, null p95 1.01, **percentile_of_real 1.0**, excess 0.427. Regime: btc_up_years 1.605 (ann 0.2342), btc_down_years -0.458 (ann -0.0083), vol_calm 2.035, vol_mid 0.724, vol_turbulent 0.719. Vs benchmark: sharpe_a 1.169, sharpe_b 0.94, diff 0.228, diff_p5 -0.075, diff_p95 0.537, **p_a_gt_b 0.908**, corr 0.898. CLI output: `research/kalshi_perps/robust_crash_filter_beta.json`.

## 7. Verdict

**FAIL — beats_benchmark_oos: walk-forward 1.011 < 1.131.** Passed: folds 5/6, oos_mdd -0.1961, no liquidations, stress positive; DSR/PBO are the referee's. The fixed d20_w60 run (timing-null percentile 1.0, p_a_gt_b 0.908, 2018 -0.0133, 2022 -0.0032) shows the mechanism works at depth 0.20, but early folds selected the 0.30/metals variants and fold 3 (-1.08) shows 0.30 still rides the 2022 legs.

## 8. Next — not run, each is a new trial

(a) d20_w60 alone: the walk-forward never chose it before 2022, so its edge showed only after the fact. (b) A two-point grid {d20_w60, d30_w60}: dropping m12/w120 after seeing they drove the selection instability is the tuning the protocol forbids. (c) Vol-scaled depth (k x sigma_i) instead of the metals constant. (d) The trigger fires after fast crashes (Mar 2020) then waits for the weekly check; a cadence variant needs `rebalance_every` and its own registration.
