# dual_momentum — Antonacci dual momentum across a crypto bloc and a metals bloc

## 1. Hypothesis, mechanism, evidence
The benchmark is levered beta on four assets that all rose 2018–25; the incumbent `trend_long_only` lost to it (0.80 vs 1.13) because its fast per-asset components (10/50 MA, 21-day sign, 55-day breakout) whipsaw at a 29 bps round trip. Hypothesis: a slow (6- or 12-month) absolute-momentum gate judged per bloc (equal-weight of two correlated assets) changes state a few times a year, keeps the bull exposure, sits in 3.25% collateral through the 2018 and 2022 bear legs, and relative momentum tilts risk to the trending bloc. Mechanism: a bloc's trailing return over `lookback` calendar days (ending `skip` days ago) must exceed 3.25% × lookback/365; the bloc with the higher return gets risk share `top_share` (winner sleeve at the benchmark's size, loser at (1−top_share)/top_share of it, a gated-out bloc 0); long-only, equal risk per asset via `vol_target`. Evidence: Antonacci, "Risk Premia Harvesting Through Dual Momentum" (SSRN 2042750) and "Absolute Momentum" (SSRN 2244633); Moskowitz–Ooi–Pedersen 2012, "Time Series Momentum" (JFE); Hurst–Ooi–Pedersen 2017, "A Century of Evidence on Trend-Following Investing" (SSRN 2993026); Jegadeesh–Titman 1993 / Asness–Moskowitz–Pedersen 2013 for the skip month; Liu–Tsyvinski 2021 (RFS) for crypto TSMOM; `tournament.md` for the whipsaw diagnosis.

## 2. Data and causality
Daily closes from `D.load_panel` only (Coinbase spot, Yahoo GC=F/SI=F); no aux series. `align()` closes are resampled to a calendar-daily forward-filled frame so the horizon is identical for crypto (365 bars/yr) and metals (252). Row t uses close(t−skip) and close(t−skip−lookback); weights decided at close t execute at t+1's open. An asset joins its bloc and is tradable only if it printed a native bar within the last 7 days at every point of the window, which drops xrp for its 2021-01-19 → 2023-07-13 Coinbase delisting and until 2024-07-12 after it (else the relisting jump counts as momentum). `skip` is clipped at 0. Registry-wide causality test green (38 tests OK); truncating real data at 2022-07-01 changes no earlier weight (max |diff| 0.0). Nothing after 2025-07-01 was read.

## 3. Registered grid (verbatim)
```python
TRIALS = {
    "dual_momentum": {"params": {"target_vol": 0.12},
                      "grid": {"lookback": [182, 365], "top_share": [0.7, 1.0]}},
    "dual_momentum_skip": {"params": {"target_vol": 0.12, "lookback": 365, "skip": 30, "top_share": 1.0},
                           "grid": {}},
    "dual_momentum_6": {"params": {"target_vol": 0.12, "lookback": 365, "top_share": 0.7,
                                   "crypto": ("btc", "eth", "sol", "xrp")},
                        "grid": {}},
}
```
Six configurations; lookbacks in calendar days (182 ≈ 6 months, 365 = 12). `dual_momentum_6` ran with `--universe btc,eth,gold,silver,sol,xrp --start 2021-07-01` (shorter sample; on four assets it equals dual_momentum(365, 0.7)). Nothing was added after seeing results.

## 4. Walk-forward (dev 2016-06-01 →, 6 folds, warmup 550, taker_t0, Kalshi funding)
`dual_momentum`, grid point selected in-sample per fold (every fold picked lookback 182, top_share 1.0):

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | 182 / 1.0 | 3.47 | 0.568 | 0.0929 | -0.0584 | 2.07 |
| 1 | 2019-03-09 → 2020-06-11 | 182 / 1.0 | 2.172 | -0.519 | -0.0225 | -0.0848 | 3.11 |
| 2 | 2020-06-12 → 2021-09-15 | 182 / 1.0 | 1.648 | 2.843 | 0.4297 | -0.047 | 1.08 |
| 3 | 2021-09-16 → 2022-12-20 | 182 / 1.0 | 1.869 | -0.333 | 0.0135 | -0.0585 | 1.72 |
| 4 | 2022-12-21 → 2024-03-25 | 182 / 1.0 | 1.579 | 1.188 | 0.1845 | -0.0624 | 3.98 |
| 5 | 2024-03-26 → 2025-06-30 | 182 / 1.0 | 1.519 | 0.117 | 0.0502 | -0.0656 | 1.96 |

oos_sharpe_concat **0.706**, oos_cagr 0.0903, oos_max_drawdown -0.0848, folds positive 5/6, WFE 0.195, liquidations 0 (benchmark 1.131 / 0.182 / -0.184 / 6/6; incumbent 0.798).

`dual_momentum_skip` (fixed_params=true; OOS SR by fold 0.568, 0.393, 2.979, -0.288, 1.804, 0.18; turnover 0.74–6.46): oos_sharpe_concat 1.047, oos_cagr 0.1198, oos_max_drawdown -0.0865, folds positive 6/6, WFE null.

`dual_momentum_6` (fixed_params=true, six ~5-month folds from 2023-01-02; OOS SR -1.531, 1.753, 3.615, -0.431, 3.201, -0.334): oos_sharpe_concat 1.404, oos_cagr 0.1801, oos_max_drawdown -0.0957, folds positive 3/6, WFE null. A 2.5-year universe check only.

## 5. Dev fixed run, selected config (182 / 1.0), 2018-01-01 → 2025-06-30, `--yearly --stress`
net_sharpe 0.651, cagr 0.0845, max_drawdown -0.1246, total_return 0.8379, ann_turnover 2.4 (incumbent 3.76, benchmark 1.68), fees_annual 0.0035, avg_gross_leverage 0.188, n_liquidations 0, pct_positive_months 0.633. By year: 2018 0.0032, 2019 0.0484, 2020 0.0808, 2021 0.2041, 2022 0.0508, 2023 0.0873, 2024 0.1372, 2025 0.0333.

| scenario | net_sharpe | cagr | max_drawdown | fees_annual | funding_annual |
|---|---:|---:|---:|---:|---:|
| taker_t0/kalshi | 0.651 | 0.0845 | -0.1246 | 0.0035 | 0.0 |
| taker_t0/proxy | 0.499 | 0.0714 | -0.1272 | 0.0035 | -0.0123 |
| maker_t0/kalshi | 0.68 | 0.087 | -0.1232 | 0.0012 | 0.0 |
| maker_t0/proxy | 0.527 | 0.0739 | -0.1257 | 0.0012 | -0.0123 |
| stress_1p5x/kalshi | 0.625 | 0.0823 | -0.126 | 0.0055 | 0.0 |
| stress_1p5x/proxy | 0.473 | 0.0693 | -0.1287 | 0.0055 | -0.0123 |

n_liquidations 0 in all six cells.

## 6. `robust` (n_boot 500, n_null 60, 2018-01-01 → 2025-07-01, benchmark vol_target_hold 0.94)
Bootstrap Sharpe p5/p50/p95 -0.0418 / 0.6554 / 1.278 (p_sharpe_le_0 0.062); CAGR 0.0262 / 0.0847 / 0.1397; MDD -0.2211 / -0.126 / -0.0702. Perturbation (10): min 0.469 (lookback 136), median 0.641, max 0.788 (target_vol 0.09), collapse_ratio 0.72; top_share 0.75 → 0.758, lookback 228 → 0.554, skip 1 → 0.517, hurdle ±25% → 0.628 / 0.667. Timing null: real 0.651, null mean 0.575, null p95 0.98, percentile_of_real 0.617, excess_over_null_mean 0.076. Regime: btc_up_years Sharpe 0.835 (ann_return 0.1063), btc_down_years -0.082 (0.0267); vol calm 1.437, mid 0.376, turbulent 0.281. Sharpe difference vs benchmark: diff -0.289 (p5 -0.797, p95 0.201), **p_a_gt_b 0.148**, corr 0.683.

## 7. Verdict
**FAIL** — beats_benchmark_oos (0.706 vs 1.131; below the incumbent 0.798 too), hence dsr_ge_0.95. Passes folds ≥ 4 (5/6), OOS DD ≤ 25% (-0.0848), zero liquidations, stress positive (stress_1p5x/proxy cagr 0.0693). The skip variant (1.047, 6/6) also trails the benchmark and is a fixed-param report; the 6-asset variant (1.404) is 2.5 years at 3/6 folds. PBO and DSR are the referee's.

## 8. Next, and why not run
The whipsaw moved rather than vanished: the 6-month gate re-entered late after the 2019 and 2022–23 recoveries (folds 1 and 3 negative) and metals flicker around the 3.25% hurdle (9–15 signal changes per asset-year before the weekly band); timing-null percentile 0.617 says the gate barely beats its own exposure shuffled in time. Untested: (a) hysteresis around the hurdle (exit below 0, re-enter above it); (b) vol-adjusted relative momentum so metals can win; (c) blending 182 and 365 instead of selecting (WFE 0.195 says selection added little); (d) top_share 0.7 with the loser's budget handed to the winner when only one bloc passes. Each is a new configuration that raises the registry's N for everyone, so none was run.
