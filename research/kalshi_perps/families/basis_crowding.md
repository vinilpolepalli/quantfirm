# basis_crowding — perp basis / funding as a long-book crowding gauge

Designer run 2026-09-15. **Verdict: FAIL — the family is the benchmark plus noise; every crowding cut lost money on this sample.**

## 1. Hypothesis, mechanism, evidence
Binance's USDT-perp basis (premium index) and funding measure how crowded leveraged retail longs are. Hold the vol-targeted long book (`vol_target_hold`) but (a) cut BTC/ETH when the 30-day basis is high relative to its trailing year (crash risk), (b) add when the 7-day basis collapses inside an uptrend (positioning washout), (c) cut when 30-day funding is rising. Gold/silver have no basis series and keep the plain vol-targeted weight. Evidence: Schmeling, Schrimpf, Todorov, "Crypto carry", BIS Working Paper 1087 (high carry, driven by trend-chasing retail leverage, predicts crashes); CF Benchmarks note that basis correlates ~0.5 with momentum z-scores. Measured before any backtest: corr(30d premium, 90d momentum z) = 0.40 BTC / 0.55 ETH; P(close > SMA100 | crowded at q90) = 1.00 BTC / 0.99 ETH. The gate fires only inside uptrends (~21% of uptrend days, 6 episodes of ~40 days), so it is anti-trend at the margin and adds "beyond trend" only if those cuts are paid for.

## 2. Data and causality
`load_aux("premium_btc"/"premium_eth")` daily close (2020-01→) and `load_funding_proxy` raw Binance 8h funding summed per UTC day. Both moved to t+1 (`index + 1 day`) before use, reindexed to the price calendar, ffilled over 8 missing premium days. Trailing rolling means/quantiles (min_periods = half window) and SMA only; rows before the aux history or before a window fills carry signal 1.0 = benchmark weight. Basis data start 2020-01, so all runs use `--start 2020-06-01`; walk-forward `--warmup 300 --folds 5` (folds of 311 days from 2021-03-28). Brief deviation, decided from the data's shape before the first run: "7-day premium < 0" is the normal state on Binance (premium close negative on 69%/63% of BTC/ETH days, median −3.7 bps), so (b) is registered as 7-day mean premium < trailing-365d q10 (~3.5% of days jointly with the uptrend). Granularity: at 12% target the benchmark's median BTC weight is 0.05 of equity, so with the 0.05 step a "half" cut often rounds to 0 or to no change.

## 3. Registered grid (verbatim)
```
TRIALS = {"basis_crowding": {"params": {"target_vol": 0.12},
  "grid": {"variant": ["derisk_q90_flat", "derisk_q90_half", "derisk_q80_half",
                       "capitulation", "funding_mom_half", "derisk_q90_half+capitulation"]}}}
```
derisk_qXX_Y: 30d mean premium > trailing-365d qXX → BTC/ETH weight 0.0 (flat) / 0.5 (half); capitulation: 7d mean premium < q10 AND close > SMA100 → 1.5; funding_mom_half: 30d mean daily funding up over 14 days → 0.5; combo: both, de-risk wins ties. Fixed: gauge_window 30, pct_window 365, capit_window 7, trend_window 100, chg_window 14, capit_pct 0.10, capit_boost 1.5, fmom_to 0.5. No tuning after results. The five unselected variants were each run once as fixed dev backtests (§5); these are the same keys the tournament's `dev_fixed` records.

## 4. Walk-forward (`--start 2020-06-01 --warmup 300 --folds 5`, 30 trials this call)
| fold | window | selected | IS SR | OOS SR | OOS ret | DD | turn | bench OOS SR |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 2021-03-28→2022-02-01 | capitulation | 2.803 | 0.164 | +3.87% | −8.34% | 1.63 | 0.064 |
| 1 | 2022-02-02→2022-12-09 | capitulation | 1.607 | −0.879 | −6.53% | −17.53% | 1.68 | −0.854 |
| 2 | 2022-12-10→2023-10-16 | capitulation | 0.804 | 0.947 | +12.27% | −8.58% | 2.94 | 0.947 |
| 3 | 2023-10-17→2024-08-22 | capitulation | 0.749 | 2.46 | +38.45% | −8.23% | 3.18 | 2.448 |
| 4 | 2024-08-23→2025-06-30 | capitulation | 1.221 | 1.591 | +19.37% | −6.03% | 2.48 | 1.612 |

oos_sharpe_concat **0.922**, oos_cagr 0.148, oos_max_drawdown −0.1753, folds positive 4/5, WFE 0.776. `vol_target_hold` fixed fold report on the same window: 0.903 / 0.1444 / −0.173 / 4/5 (the CAMPAIGN's 1.13 is the 2018→ 6-fold window). The de-risk and funding variants were never the in-sample best in any fold.

## 5. Fixed dev run, `variant=capitulation`, 2020-06-01→2025-06-30, `--yearly --stress`
SR 1.315, CAGR 0.2054, MDD −0.16, turnover 1.69, fees 0.25%/yr, avg/max gross 0.545/0.867, 0 liquidations, worst day −3.01%. Benchmark, same window: 1.313 / 0.2053 / −0.1482.
By year: 2020 +25.56%, 2021 +17.57%, 2022 −7.41%, 2023 +27.31%, 2024 +33.75%, 2025 +11.08%.
Stress (SR / CAGR / MDD): taker_t0/kalshi 1.315 / 0.2054 / −0.16; taker_t0/proxy 1.16 / 0.1827 / −0.1605 (funding −1.84%/yr); maker_t0/kalshi 1.328 / 0.2073 / −0.1597; maker_t0/proxy 1.173 / 0.1846 / −0.1601; stress_1p5x/kalshi 1.303 / 0.2037 / −0.1603 (fees 0.39%); stress_1p5x/proxy 1.148 / 0.181 / −0.1608.
Unselected variants, fixed dev, same window (SR / CAGR / MDD / turnover): derisk_q90_flat 1.284 / 0.1901 / −0.1482 / 1.75; derisk_q90_half 1.284 / 0.1938 / −0.1482 / 1.55; derisk_q80_half 1.17 / 0.1764 / −0.1482 / 1.61; funding_mom_half 1.048 / 0.1524 / −0.146 / 1.89; derisk_q90_half+capitulation 1.279 / 0.1932 / −0.1601 / 1.74. Every crowding cut lowered the Sharpe below the benchmark's 1.313.

## 6. `robust` (n_boot 500, n_null 60, window 2020-06-01→2025-07-01)
Bootstrap Sharpe p5/p50/p95 0.5471 / 1.3069 / 2.1335; CAGR 0.0965 / 0.2041 / 0.3376; MDD −0.2166 / −0.1336 / −0.0888; p(SR≤0) 0.0. Perturbation (18): min 1.131 (target_vol 0.15), median 1.315, max 1.338, collapse ratio 0.86; the capitulation knobs move Sharpe by ≤0.03. Regime: BTC up-years 1.802 (1491 d), down-years −0.937 (365 d); vol calm 2.19 / mid 0.392 / turbulent 1.64. Timing null: real 1.315, null mean 1.134, null p95 1.372, percentile 0.9. vs benchmark: sharpe_a 1.314, sharpe_b 1.313, diff 0.001 [−0.061, 0.062], **p_a_gt_b 0.57**, corr 0.996.
Paired differences via `robust.sharpe_difference` (n_boot 500, same window; library call, not a CLI run): derisk_q90_flat vs benchmark −0.029 (p_a_gt_b 0.366); derisk_q90_half −0.029 (0.248); derisk_q80_half −0.143 [−0.253, −0.045] (0.006); funding_mom_half −0.265 [−0.442, −0.104] (0.008); combo −0.034 (0.298). "Beyond trend": capitulation vs trend_long_only +0.249 [−0.224, +0.731], p 0.794, corr 0.782 — but the benchmark itself scores 1.313 vs trend's 1.066 here, so that is the passive book beating trend, not the basis signal. Why the gate failed: on the 240 BTC crowded-q90 days the benchmark's BTC P&L was +7.29% of equity (+0.030%/day vs +0.023% on other days) and the mean forward-30-day BTC return after a crowded day was +9.16% vs +5.42% (ETH: +0.030%/day vs +0.016%; forward 5.51% vs 7.62%). The BIS crash-after-high-carry pattern does not reproduce at a 30-day/q90 horizon on 2020–25 daily data with 6 episodes.

## 7. Verdict
**FAIL.** The selected config is the benchmark on 97% of days (corr 0.996, Sharpe diff 0.001, p_a_gt_b 0.57): beats_benchmark fails in substance (0.922 vs 0.903 OOS is one fold's rounding), and with zero edge over the passive book it cannot clear DSR ≥ 0.95 or PBO ≤ 0.10 against the registry. Folds ≥ 4, MDD ≤ 25%, zero liquidations and stress-positive all pass, but are inherited from `vol_target_hold`. In the referee's 2016→ tournament the family is byte-identical to the benchmark before 2020-07 (premium) / 2020-02 (funding).

## 8. Next, and why not run (each is a new trial on a 6-episode sample)
(i) The paper's own horizon: a 7-day premium spike gate (q95) instead of a 30-day mean, closer to BIS 1087's carry spikes. (ii) Cross-venue crowding (Hyperliquid/OKX funding in the scratchpad) to test whether Binance basis is simply too compressed post-2022 (funding 4–13%/yr vs 18–38% in 2020–21). (iii) A deadband on the funding-change tilt, which flipped on 47% of days. None would change the structural finding: the gate only fires inside uptrends that, in this sample, kept going.
