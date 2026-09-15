# xsec_momentum — cross-sectional momentum across six perps

## 1. Hypothesis, mechanism, evidence

Among btc, eth, gold, silver, sol, xrp, the names with the strongest trailing 3–12-month return should keep outperforming the rest over the next month, so a monthly book long the top two (documented variant: also short the bottom two) should beat holding all six per unit of risk. Mechanism: relative momentum from under-reaction and winner-chasing flows (Jegadeesh–Titman 1993; Asness–Moskowitz–Pedersen 2013). On this universe the sort is mostly a crypto-vs-metals rotation. For: Borri–Liu–Tsyvinski–Wu (2025) two-week cross-sectional crypto premium gross of costs; Liu–Tsyvinski–Wu (2022). Against: Han–Kang–Ryu (SSRN 4675565) — it does not survive costs and intra-period moves. Weak prior; long-only primary, long/short registered to document the short side.

## 2. Data and causality

Daily proxy closes only (Coinbase spot, Yahoo GC=F/SI=F), no aux series. Signal on day t uses `close.shift(skip)/close.shift(skip+lookback)−1`; ranks are per row; sizing is the shared `vol_target` (rolling windows). A freshness mask (native bar within 5 days, none stale inside the return window) removes xrp's 905-day Coinbase hole (2021-01-19 → 2023-07-13, close 0.30 → 0.82) from every rank, so its relisting jump is never traded; metals holidays (≤4 days) pass. `vol_target` sizes off a fully-long 6-name reference book, so the call passes `target_vol × n/k` (a design constant: 3, 1.5, 12/7 for top/ls/rank) to give the selected names the benchmark's risk budget; realised gross averaged 0.55 vs the benchmark's 0.49. Every run used `--every 30` (monthly band check; cadence is part of the hypothesis; nothing else in `BacktestConfig` changed). Causality: `tests.test_perps` 38/38 green plus a real-panel truncation check (diff 0.0).

## 3. Registered grid (verbatim from `TRIALS`)

`params = {"target_vol": 0.12, "top_k": 2}`; `grid = {"spec": [("top",63,0), ("top",252,21), ("ls",63,0), ("ls",252,21), ("rank",126,0)]}` (spec = mode, lookback, skip). Config 6: `("top",63,0)` on btc,eth,gold,silver over the standard window (fixed params; same registry key). Pre-registered selection rule: the config picked in the most folds, tie → last fold. Registry: 3 unique keys added (`("top",252,21)` and `("ls",63,0)` were evaluated in-sample, never picked); `n_trials_this_call` 20.

## 4. Walk-forward

`--universe btc,eth,gold,silver,sol,xrp --start 2021-07-01 --folds 4 --warmup 200 --every 30`. Four years, fold-0 in-sample window ≈ 6 months: short.

| fold | window | params | IS SR | OOS SR | OOS ret | DD | turnover |
|---:|---|---|---:|---:|---:|---:|---:|
| 0 | 2022-01-17 → 2022-11-27 | ls,252,21 | 1.419 | 0.025 | +2.36% | −8.82% | 4.42 |
| 1 | 2022-11-28 → 2023-10-08 | ls,252,21 | 0.676 | −0.279 | +0.18% | −10.14% | 4.65 |
| 2 | 2023-10-09 → 2024-08-18 | ls,252,21 | 0.287 | −0.774 | −5.45% | −10.5% | 3.66 |
| 3 | 2024-08-19 → 2025-06-30 | rank,126,0 | 0.817 | 1.341 | +19.94% | −11.38% | 2.23 |

oos_sharpe_concat **0.154**, oos_cagr 4.47%, oos_max_drawdown −11.93%, folds positive 3/4, WFE −0.17 (median OOS −0.127). Selected by rule: `("ls",252,21)`.

Benchmark control `vol_target_hold` {target_vol 0.12}, same window/universe/cadence (existing key): oos_sharpe_concat **1.054**, CAGR 17.67%, DD −14.1%, 3/4 folds (−0.991, 0.863, 2.13, 2.09).

Config 6, 4-asset standard window, fixed params (not a selection): oos_sharpe_concat **1.112**, CAGR 23.31%, DD −22.35%, 6/6 folds; fold OOS SR 0.114 / 1.004 / 2.471 / 0.023 / 1.57 / 1.304, turnover 3.3–6.4. Below the CAMPAIGN benchmark (1.13 / 18.2% / −18.4%, weekly cadence) with a deeper drawdown.

## 5. Fixed dev run 2021-07-01 → 2025-06-30, six assets, `--yearly --stress`

Selected `("ls",252,21)`: net_sharpe −0.358, CAGR −1.63%, max DD −27.59%, turnover 4.22, fees 0.61%/yr, 0 liquidations. By year: 2021 +11.13%, 2022 +9.75%, 2023 −8.34%, 2024 −17.63%, 2025 +1.67%.

| cell | SR | CAGR | DD |
|---|---:|---:|---:|
| taker_t0/kalshi | −0.358 | −1.63% | −27.59% |
| taker_t0/proxy | −0.426 | −2.44% | −28.74% |
| maker_t0/kalshi | −0.322 | −1.21% | −27.32% |
| maker_t0/proxy | −0.397 | −2.09% | −28.16% |
| stress_1p5x/kalshi | −0.384 | −1.94% | −28.1% |
| stress_1p5x/proxy | −0.459 | −2.81% | −29.25% |

Long-only primary `("top",63,0)`, same window (registered config 1, extra fixed run, same key): net_sharpe 0.578, CAGR 12.64%, max DD −31.48%, turnover 6.3, fees 0.91%/yr, 0 liquidations; by year +13.81% / −9.31% / +25.24% / +13.55% / +9.71%; stress cells SR 0.463–0.612, all CAGR positive (10.37%–13.31%), DD −30.99% to −31.82%.

## 6. `robust` (--n-boot 500 --n-null 60), six assets, 2021-07-01 → 2025-07-01

Selected `("ls",252,21)`: bootstrap Sharpe p5/p50/p95 −1.2102 / −0.362 / 0.4698 (p_sharpe_le_0 0.766); perturbation min/median −0.824 / −0.3 (top_k=3 worst, top_k=1 best −0.056); timing-null percentile 0.367 (null mean −0.106); regime: BTC up-years −0.679, down-years 0.557, vol calm/mid/turbulent −0.913 / 0.147 / −0.579; vs benchmark sharpe_a −0.358 vs sharpe_b 1.026, diff −1.384, p_a_gt_b 0.046, corr −0.027.

Primary `("top",63,0)` (second robust run; the json on disk holds the selected config): bootstrap −0.0776 / 0.5472 / 1.3635 (p_sharpe_le_0 0.098); perturbation 0.385 / 0.534; timing-null percentile 0.25 (null mean 0.788 — random timing of the same exposures beat the ranking); regime up 1.043 / down −0.526, calm 0.921 / mid −0.242 / turbulent 1.231; vs benchmark 0.578 vs 1.026, diff −0.448, p_a_gt_b 0.134, corr 0.745.

## 7. Verdict

**FAIL** — beats_benchmark_oos (0.154 vs 1.054), stress total return negative (all six cells, selected config), negative WFE; primary long-only also fails beats_benchmark (0.578 vs 1.026, p 0.134), max DD (−31.48%) and shows no timing skill (percentile 0.25). Passed: 0 liquidations, OOS DD −11.93%. DSR/PBO are the referee's.

## 8. Next, and why not run

(i) Rank on return/σ so the sort is not a crypto-vs-metals switch; (ii) crypto-only (btc, eth, sol, xrp), where the literature's premium lives — only ~2 clean years for four names; (iii) gate the top-2 by its own 12-month trend sign. Each is a new trial against a 49-configuration registry, and the timing null already says the ranking adds nothing to the exposures it picks.
