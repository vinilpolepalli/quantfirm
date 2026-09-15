# Kalshi perps tournament — 2026-09-15.1

Ran 2026-09-15T00:28:30+00:00. Universe ['btc', 'eth', 'gold', 'silver']. Dev window 2016-06-01 → 2025-07-01 (folds start after 550 warmup days, 6 folds). Cost `taker_t0`, funding `kalshi`, rebalance every 7d with a 3% band. **13 registered trials.** Holdout: SEALED — not read by this module.

## Walk-forward (parameters selected in-sample per fold, scored out of sample)

| family | OOS Sharpe | OOS CAGR | OOS max DD | folds + | WFE | vs bench | stress SR | DSR | gates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **vol_target_hold** (benchmark) | 1.131 | 18.2% | -18.4% | 6/6 | — | 0 | — | — | — |
| trend_long_only | 0.798 | 9.8% | -12.5% | 6/6 | — | -0.333 | 1.249 | 0.6577 | FAIL: beats_benchmark_oos, dsr_ge_0.95, pbo_le_0.10 |
| breakout | 0.464 | 7.2% | -13.3% | 5/6 | 0.416 | -0.667 | 0.562 | 0.3084 | FAIL: beats_benchmark_oos, dsr_ge_0.95, pbo_le_0.10 |
| tsmom | 0.453 | 7.2% | -13.3% | 5/6 | 0.129 | -0.678 | 0.797 | 0.2976 | FAIL: beats_benchmark_oos, dsr_ge_0.95, pbo_le_0.10 |
| ma_trend | 0.422 | 7.4% | -21.1% | 3/6 | 0.095 | -0.709 | 0.891 | 0.2704 | FAIL: beats_benchmark_oos, folds_positive_ge_4, dsr_ge_0.95, pbo_le_0.10 |
| trend_ensemble | 0.381 | 6.5% | -15.5% | 5/6 | — | -0.75 | 0.793 | 0.2329 | FAIL: beats_benchmark_oos, dsr_ge_0.95, pbo_le_0.10 |
| gold_silver_ratio | -0.803 | 1.9% | -2.6% | 6/6 | — | -1.934 | -0.772 | 0.0 | FAIL: beats_benchmark_oos, dsr_ge_0.95, pbo_le_0.10 |

CSCV probability of backtest overfitting across 14 configurations (+ benchmark): **PBO = 0.3**, degradation slope -0.532.

## Controls (fixed, dev window)

| control | Sharpe | CAGR | max DD | turnover/yr | fees/yr | interest/yr |
|---|---:|---:|---:|---:|---:|---:|
| vol_target_hold | 1.311 | 21.5% | -18.9% | 1.82 | 0.26% | 2.97% |
| buy_hold | 1.296 | 60.7% | -61.6% | 1.35 | 0.20% | 2.65% |
| flat | None | 3.3% | 0.0% | 0.0 | 0.00% | 3.25% |
| coin_flip | -1.031 | -7.4% | -56.9% | 12.29 | 1.78% | 2.96% |

## Per-fold detail

### trend_long_only

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `` | — | 0.394 | +7.3% | -6.4% | 4.02 |
| 1 | 2019-03-09 → 2020-06-11 | `` | — | 0.462 | +9.5% | -12.5% | 4.07 |
| 2 | 2020-06-12 → 2021-09-15 | `` | — | 2.21 | +36.4% | -5.9% | 3.24 |
| 3 | 2021-09-16 → 2022-12-20 | `` | — | -0.471 | +1.0% | -5.0% | 2.73 |
| 4 | 2022-12-21 → 2024-03-25 | `` | — | 0.671 | +11.4% | -6.1% | 5.01 |
| 5 | 2024-03-26 → 2025-06-30 | `` | — | 0.807 | +12.7% | -5.0% | 4.78 |

### breakout

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `entry=100, exit_=20` | 2.192 | 0.616 | +10.7% | -6.2% | 5.5 |
| 1 | 2019-03-09 → 2020-06-11 | `entry=100, exit_=20` | 1.502 | -0.034 | +3.0% | -13.3% | 4.32 |
| 2 | 2020-06-12 → 2021-09-15 | `entry=100, exit_=20` | 1.027 | 1.861 | +30.2% | -5.7% | 2.59 |
| 3 | 2021-09-16 → 2022-12-20 | `entry=100, exit_=20` | 1.172 | -0.841 | -3.9% | -7.6% | 4.34 |
| 4 | 2022-12-21 → 2024-03-25 | `entry=100, exit_=20` | 0.835 | 0.522 | +10.2% | -6.5% | 5.03 |
| 5 | 2024-03-26 → 2025-06-30 | `entry=100, exit_=20` | 0.785 | 0.393 | +8.1% | -5.3% | 3.62 |

### tsmom

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `lookbacks=(21, 63, 126, 252)` | 3.07 | 0.521 | +9.7% | -6.9% | 12.73 |
| 1 | 2019-03-09 → 2020-06-11 | `lookbacks=(21, 63, 126, 252)` | 2.14 | 0.458 | +9.7% | -9.8% | 9.4 |
| 2 | 2020-06-12 → 2021-09-15 | `lookbacks=(21, 63, 126, 252)` | 1.547 | 1.991 | +32.8% | -4.8% | 6.9 |
| 3 | 2021-09-16 → 2022-12-20 | `lookbacks=(21, 63, 126, 252)` | 1.606 | -0.051 | +3.2% | -6.9% | 7.8 |
| 4 | 2022-12-21 → 2024-03-25 | `lookbacks=(21, 63, 126, 252)` | 1.27 | -0.367 | -0.5% | -13.3% | 11.91 |
| 5 | 2024-03-26 → 2025-06-30 | `lookbacks=(21, 63, 126, 252)` | 1.031 | -0.065 | +3.0% | -5.5% | 8.8 |

### ma_trend

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `pairs=((20, 100), (50, 200))` | 3.297 | 0.719 | +14.0% | -9.5% | 6.54 |
| 1 | 2019-03-09 → 2020-06-11 | `pairs=((20, 100), (50, 200))` | 2.042 | -0.318 | -1.8% | -18.8% | 5.33 |
| 2 | 2020-06-12 → 2021-09-15 | `pairs=((20, 100), (50, 200))` | 1.438 | 2.217 | +40.7% | -8.9% | 4.04 |
| 3 | 2021-09-16 → 2022-12-20 | `pairs=((10, 50), (20, 100), (50, 200))` | 1.552 | -0.367 | -0.2% | -7.3% | 6.42 |
| 4 | 2022-12-21 → 2024-03-25 | `pairs=((20, 100), (50, 200))` | 1.301 | -0.458 | -2.4% | -15.6% | 7.23 |
| 5 | 2024-03-26 → 2025-06-30 | `pairs=((20, 100), (50, 200))` | 1.047 | 0.603 | +11.7% | -6.8% | 4.41 |

### trend_ensemble

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `` | — | 0.684 | +11.9% | -6.8% | 8.89 |
| 1 | 2019-03-09 → 2020-06-11 | `` | — | -0.173 | +1.2% | -15.1% | 6.58 |
| 2 | 2020-06-12 → 2021-09-15 | `` | — | 1.992 | +33.2% | -7.2% | 4.96 |
| 3 | 2021-09-16 → 2022-12-20 | `` | — | -0.354 | +0.1% | -7.8% | 6.06 |
| 4 | 2022-12-21 → 2024-03-25 | `` | — | -0.315 | -0.1% | -12.6% | 8.72 |
| 5 | 2024-03-26 → 2025-06-30 | `` | — | 0.298 | +7.1% | -5.3% | 6.0 |

### gold_silver_ratio

| fold | window | params | IS SR | OOS SR | OOS ret | OOS DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2017-12-03 → 2019-03-08 | `` | — | -0.282 | +3.7% | -1.0% | 4.12 |
| 1 | 2019-03-09 → 2020-06-11 | `` | — | -1.348 | +0.6% | -2.6% | 2.31 |
| 2 | 2020-06-12 → 2021-09-15 | `` | — | -1.182 | +1.6% | -1.7% | 1.15 |
| 3 | 2021-09-16 → 2022-12-20 | `` | — | 0.216 | +4.6% | -0.7% | 2.63 |
| 4 | 2022-12-21 → 2024-03-25 | `` | — | -0.625 | +3.1% | -1.7% | 2.11 |
| 5 | 2024-03-26 → 2025-06-30 | `` | — | -1.208 | +1.1% | -1.9% | 3.22 |

## Reading this

* Sharpe ratios are on EXCESS return over the 3.25% collateral yield, so an idle book scores 0.
* A family passes only if every gate holds; the score is otherwise exactly 0 (docs/FIRM.md §2).
* Numbers are on PROXY histories (Coinbase spot, Yahoo futures) with Kalshi's fee tier 0 and its near-zero funding; Kalshi perps themselves have three months of history.
* The holdout (2025-07-01 →) has not been read. `python -m quantfirm.perps.cli holdout` opens it once, for one family, and records that it did.
