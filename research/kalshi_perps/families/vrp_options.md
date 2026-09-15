# vrp_options — Deribit DVOL (options-market) information as a perps signal

Code `quantfirm/perps/families/vrp_options.py`. Selected config `{"target_vol": 0.12, "mode": "vrp_tilt"}` (last fold's pick; chosen in 3 of 4 folds). Registry rows added: 4 walkforward + 1 backtest (key `bcbddc0b7532`); nothing added or changed after the first run.

## 1. Hypothesis, mechanism, evidence

VRP = implied − realised vol is what option buyers pay to bear variance risk; in equities a high VRP predicts high subsequent returns (Bollerslev–Tauchen–Zhou 2009, RFS 22(11), https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787; Bollerslev–Marrone–Xu–Zhou 2014, JFQA). Alexander & Imeraj (2021, J. Alternative Investments 23(4), https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734) build the VIX construction for bitcoin from Deribit options and document a large, time-varying bitcoin VRP with an unsettled predictive sign, so both signs were registered. DVOL is Deribit's 30-day variance-swap-style implied vol (https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/). Six mechanisms on the desk's long-only vol-targeted book, BTC/ETH legs only: z-score gate above +k (`vrp_high`, BTZ sign); mirror below −k (`vrp_low`); parameter-free gate DVOL > realised (`vrp_raw`); stay-invested tilt, full when z > 0 else half (`vrp_tilt`); "sell fear, buy the dip", full when DVOL is in its top trailing-year quintile and price > 200-day mean, else half (`fear_dip`); sizing on max(implied, realised) vol (`iv_size`). Gold and silver have no DVOL and stay at the plain vol-targeted long weight in every mode (the VIX is an equity gauge; a VIX-gated gold book is a different, safe-haven family); their weights are numerically identical to `vol_target_hold`'s, so every difference from the benchmark is the crypto options signal.

## 2. Data and causality

`D.load_aux("dvol_btc"/"dvol_eth")` daily close (2021-03-24→); Coinbase spot for realised vol (30-day std × √365 × 100, vol points); panel closes for the 200-day mean. DVOL is reindexed to the panel calendar, forward-filled and shifted one day; the VRP, its 252-day z-score (63-day minimum history) and the DVOL quantile are built on same-stamped series and the finished feature is shifted one day, so the weight decided at close t uses the t−1 print. Where the input is undefined, every mode holds the benchmark book. Because DVOL starts 2021-03, the walk-forward uses `--start 2021-04-01 --warmup 250 --folds 4` (folds from 2021-12-07; fold 0's in-sample window has about six months of live signal) and the fixed and `robust` runs use `--start 2021-04-01`; CAMPAIGN's 1.13 benchmark is over 2018→2025, so the like-for-like comparison is `robust`'s same-window `vs_benchmark`. Truncating the real panel at 2024-01-01 changes no earlier weight in any mode (max |diff| 0.0); `python -m unittest tests.test_perps -q`: 38 tests OK.

## 3. Registered grid (verbatim)

```
TRIALS = {"vrp_options": {"params": {"target_vol": 0.12},
          "grid": {"mode": ["vrp_high", "vrp_low", "vrp_tilt", "vrp_raw", "fear_dip", "iv_size"]}}}
```
Fixed a priori: k = 0.5, rv_window = 30, lookback = 252, quantile = 0.8, trend_window = 200, base = 0.5.

## 4. Walk-forward (`--start 2021-04-01 --warmup 250 --folds 4`, taker_t0, kalshi funding)

| fold | window | params | IS SR | OOS SR | OOS return | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2021-12-07 → 2022-10-27 | mode=vrp_tilt | 0.997 | -1.144 | -0.0759 | -0.1473 | 1.53 |
| 1 | 2022-10-28 → 2023-09-18 | mode=vrp_high | -0.107 | 1.119 | 0.1113 | -0.0404 | 2.73 |
| 2 | 2023-09-19 → 2024-08-08 | mode=vrp_tilt | 0.227 | 2.304 | 0.343 | -0.0586 | 3.87 |
| 3 | 2024-08-09 → 2025-06-30 | mode=vrp_tilt | 0.944 | 1.596 | 0.1928 | -0.0559 | 2.24 |

oos_sharpe_concat **1.053**, oos_sharpe_median 1.357, oos_cagr 0.1498, oos_max_drawdown -0.1473, folds_positive **3/4**, wfe 2.319, n_trials_this_call 24, no liquidations. Fold 1's best in-sample config was negative (-0.107): `vrp_high`, flat 70% of the time, was least bad through the 2022 bear.

## 5. Fixed dev run, `mode=vrp_tilt`, `--start 2021-04-01 --yearly --stress`

net_sharpe 1.077, cagr 0.1573, max_drawdown -0.1487, total_return 0.861, ann_turnover 1.9, fees_annual 0.0028, avg_gross_leverage 0.547, n_liquidations 0, pct_positive_months 0.588.
By year: 2021 (from April) 0.0919 · 2022 -0.0492 · 2023 0.252 · 2024 0.2839 · 2025 (to June) 0.1151.

| stress cell | net_sharpe | cagr | max_drawdown | fees_annual | funding_annual |
|---|---:|---:|---:|---:|---:|
| taker_t0/kalshi | 1.077 | 0.1573 | -0.1487 | 0.0028 | 0.0 |
| taker_t0/proxy | 0.983 | 0.1453 | -0.1492 | 0.0028 | -0.0104 |
| maker_t0/kalshi | 1.093 | 0.1594 | -0.148 | 0.001 | 0.0 |
| maker_t0/proxy | 0.999 | 0.1473 | -0.1485 | 0.001 | -0.0104 |
| stress_1p5x/kalshi | 1.063 | 0.1554 | -0.1493 | 0.0044 | 0.0 |
| stress_1p5x/proxy | 0.968 | 0.1435 | -0.1498 | 0.0044 | -0.0104 |

## 6. `robust` (window 2021-04-01 → 2025-07-01, `--n-boot 500 --n-null 60`)

Benchmark `vol_target_hold`, same window: net_sharpe 1.074, cagr 0.1643, max_drawdown -0.1343, ann_turnover 1.61.
Bootstrap Sharpe p5/p50/p95 **0.1985 / 1.0857 / 1.8876**, p_sharpe_le_0 0.014.
Perturbation (14 runs): min **0.936** (target_vol 0.15), median **1.077**, max 1.119 (base 0.625), collapse_ratio 0.869; k, quantile and trend_window do not enter `vrp_tilt`, so those rows equal the base.
Timing null: real 1.077, null mean 0.779, null p95 0.972, percentile_of_real **1.0** — but the null shuffles the strategy's own weights, which also destroys the vol-targeting's timing, and this book is 0.979-correlated with the benchmark, so the percentile measures the sizer, not the options signal.
Regime: btc_up_years SR 1.823 (912 days), btc_down_years -0.051 (640 days); vol calm 1.604, mid 0.436, turbulent 1.191.
Sharpe difference vs benchmark: sharpe_a 1.077, sharpe_b 1.074, diff **0.003** (p5 -0.152, p95 0.159), **p_a_gt_b 0.532**, corr 0.979.

## 7. Verdict

**FAIL — beats_benchmark_oos**: OOS 1.053 vs 1.13, and same-window +0.003 Sharpe with p_a_gt_b 0.532; the DVOL tilt is the benchmark with 0.29/yr more turnover, lower CAGR (0.1573 vs 0.1643) and a deeper drawdown (-0.1487 vs -0.1343). Passes oos_mdd_le_25pct (-0.1473), no_liquidations, stress_positive (stress_1p5x/proxy cagr 0.1435); folds 3/4 positive; DSR and PBO are the referee's.

## 8. Next, and why not run (each is a new trial)

(i) The sign test proper — fixed dev runs of `vrp_high`, `vrp_low`, `vrp_raw` side by side; the walk-forward only exposes their in-sample ranking, and the referee's tournament records every grid point's dev run anyway. (ii) The exact BTZ construction, VRP in variance units (DVOL² − RV²) with a 21-day hold. (iii) DVOL term structure or skew, which needs option chains the desk does not store. (iv) GVZ (CBOE gold vol) for the metals legs, not in the data set. The a-priori grid spent the six-configuration budget; each of these would now be tuning after seeing that the tilt is benchmark-like.
