# reversal_seasonality — short-horizon reversal and calendar effects (long-only)

Designer run 2026-09-15, dev window only. Code: `quantfirm/perps/families/reversal_seasonality.py`. Four pre-registered configurations; nothing tuned after seeing results.

## 1. Hypothesis, mechanism, evidence

Equity seasonalities and short-horizon reversal — weekly reversal (Lehmann 1990; Jegadeesh 1990; Lo–MacKinlay 1990), turn-of-month (Ariel 1987; Lakonishok–Smidt 1988; Ogden 1990; McConnell–Xu 2008) — plus the claimed crypto weekend effect (Caporale–Plastun 2019; Baur, Cahill, Godfrey & Liu 2019: lower weekend *volume*, no robust return effect; Kinateder–Papavassiliou 2021) would tilt the vol-targeted long book toward the days that pay. Bollinger dips inside a 200-day uptrend are treated as buyable over-reactions (Bollinger 2001; Lento et al. 2007 and Hudson–Urquhart 2021: marginal after costs). The prior was failure: each effect is worth basis points per day against a 24–29 bps tier-0 round trip (evidence_review.md §5), and for BTC Liu–Tsyvinski (2021, RFS) find one-to-four-week momentum, the opposite sign of (a).

## 2. Data and causality

Coinbase spot daily BTC/ETH, Yahoo GC=F/SI=F, union calendar via `align`; no aux series. Rolling windows and the Bollinger state machine run on native bars with closes ≤ t, then are reindexed and forward-filled. Weekend and turn-of-month flags are calendar arithmetic (weekday counts, no holiday file) for day t+1, the session the weight decided at close t is exposed to. `python -m unittest tests.test_perps -q`: 38 tests OK, causality test included.

## 3. Registered grid (verbatim)

```python
TRIALS = {
    "rs_weekly_reversal": {"params": {"target_vol": 0.12, "lookback": 5, "tilt": 0.5}, "grid": {}},
    "rs_weekend_half": {"params": {"target_vol": 0.12, "weekend_weight": 0.5}, "grid": {}},
    "rs_turn_of_month": {"params": {"target_vol": 0.12, "off_weight": 0.5, "last_days": 2, "first_days": 3}, "grid": {}},
    "rs_bollinger_mr": {"params": {"target_vol": 0.12, "bb_window": 20, "bb_k": 2.0, "trend_window": 200}, "grid": {}},
}
```

Cadence: (a) `--every 7`; (b), (c), (d) `--every 1` — a 2–5 day event cannot be traded on a weekly band check; (b) means two fee-paying trades per crypto asset per week. The benchmark was also scored at `--every 1` (existing registry key, no new trial). Selection rule, fixed before running: highest `oos_sharpe_concat` gets the fixed run and `robust`.

## 4. Walk-forward (dev 2016-06-01 →, 6 folds, warmup 550; params fixed, so IS SR and WFE are `—`)

|config|every|oos_sharpe_concat|oos_cagr|oos_max_drawdown|folds +|
|---|--:|--:|--:|--:|--:|
|vol_target_hold (benchmark)|7|1.131|0.182|−0.184|6/6|
|vol_target_hold (benchmark)|1|1.065|0.1733|−0.1984|4/6|
|(c) rs_turn_of_month, selected|1|0.946|0.1382|−0.1944|4/6|
|(b) rs_weekend_half|1|0.913|0.1485|−0.2293|4/6|
|(a) rs_weekly_reversal|7|0.823|0.1453|−0.243|4/6|
|(d) rs_bollinger_mr|1|0.698|0.059|−0.0492|6/6|

Per fold — OOS SR, OOS return, max DD, turnover (zero liquidations everywhere):

|fold|window|(c) turn_of_month|(b) weekend_half|(a) weekly_reversal|(d) bollinger|bench @1 SR|
|--:|---|---|---|---|---|--:|
|0|2017-12-03→2019-03-08|−0.511,−0.0405,−0.1944,10.67|−0.705,−0.0744,−0.2293,10.8|−0.263,−0.0189,−0.243,22.91|−0.609,0.02,−0.0317,1.13|−0.237|
|1|2019-03-09→2020-06-11|1.114,0.2207,−0.1289,8.6|1.288,0.3079,−0.1759,8.21|1.118,0.2796,−0.1682,19.86|0.409,0.0674,−0.0492,4.59|1.269|
|2|2020-06-12→2021-09-15|2.42,0.447,−0.0721,5.86|1.735,0.3486,−0.0888,9.36|2.025,0.3806,−0.0902,12.58|1.141,0.1024,−0.0221,3.75|2.037|
|3|2021-09-16→2022-12-20|−0.677,−0.0478,−0.1437,6.55|−0.397,−0.023,−0.1542,4.71|−0.674,−0.0899,−0.2189,14.91|−0.149,0.0372,−0.0177,0.79|−0.461|
|4|2022-12-21→2024-03-25|2.221,0.4063,−0.0734,9.0|2.017,0.4045,−0.0914,12.74|1.458,0.2987,−0.0954,16.43|1.419,0.1203,−0.0273,4.7|2.229|
|5|2024-03-26→2025-06-30|1.013,0.1757,−0.0691,7.14|1.401,0.2752,−0.0832,7.05|1.633,0.3656,−0.0788,14.75|1.505,0.1074,−0.0182,3.08|1.439|

(d)'s 6/6 positive folds are collateral interest: its excess Sharpe is negative in folds 0 and 3.

## 5. Fixed dev run, selected (c), `--every 1`, 2018-01-01 → 2025-06-30

net_sharpe 0.948, cagr 0.1376, max_drawdown −0.1738, ann_turnover 7.78, fees_annual 0.0113, avg_gross_leverage 0.415, n_liquidations 0. By year: 2018 −0.0878, 2019 0.204, 2020 0.3264, 2021 0.1693, 2022 −0.0626, 2023 0.2402, 2024 0.2472, 2025 0.065.

|stress cell|net_sharpe|cagr|max_drawdown|fees/funding|
|---|--:|--:|--:|---|
|taker_t0/kalshi|0.948|0.1376|−0.1738|0.0113/0.0|
|taker_t0/proxy|0.821|0.1224|−0.1738|0.0113/−0.0137|
|maker_t0/kalshi|1.016|0.1453|−0.1681|0.0039/0.0|
|maker_t0/proxy|0.882|0.1292|−0.1681|0.0039/−0.0136|
|stress_1p5x/kalshi|0.887|0.1305|−0.1804|0.0179/0.0|
|stress_1p5x/proxy|0.76|0.115|−0.1804|0.0179/−0.0137|

**Fees vs benchmark** (same window; printed `fees_annual`, `cagr`, `avg_gross_leverage`). Benchmark `--every 7`: SR 0.94, cagr 0.1545, fees 0.0024, gross 0.592; `--every 1`: SR 1.027, cagr 0.1671, fees 0.0042, gross 0.593 — daily checking alone costs 18 bps/yr and 0.066 of OOS Sharpe (1.131 → 1.065).

- (a) `--every 7`: SR 0.683, cagr 0.1211, fees 0.0234, gross 0.581. Fees are 2.10 of the 3.34 pp CAGR gap (63%); with fees added back (14.45% vs 15.69%) the tilt still loses 1.24 pp/yr at equal exposure — the reversal sign is wrong, as Liu–Tsyvinski predict.
- (b) `--every 1`: SR 0.834, cagr 0.1374, fees 0.0123, gross 0.578. Fees are 0.81 of the 2.97 pp gap (27%); the other 2.16 pp is weekend return given up — crypto weekends were not lower-return in 2018–25.
- (c) `--every 1`: fees are 0.71 of the 2.95 pp gap (24%); the rest is 30% less exposure (0.415 vs 0.593). Exposure-neutral, Sharpe is 0.079 lower, not higher: turn-of-month days were not better days for metals.
- (d) `--every 1`: SR 0.704, cagr 0.0594, fees 0.0043 on gross 0.061 — 7% of deployed notional per year against 0.7% for the benchmark.

## 6. `robust` (selected (c), `--every 1`, `--n-boot 500 --n-null 60`; `research/kalshi_perps/robust_rs_turn_of_month.json`)

Bootstrap Sharpe p5/p50/p95 0.2313 / 0.9286 / 1.6083 (p_sharpe_le_0 0.014); CAGR 0.0537 / 0.1347 / 0.2171; MDD −0.2563 / −0.1572 / −0.0992. Perturbation (8 runs): min 0.794 (target_vol 0.15), median 0.953, max 0.976 (last_days 1), collapse_ratio 0.838. Timing null: real 0.948, null mean 0.809, null p95 1.009, percentile_of_real 0.85. Regime: btc_up_years 1.608, btc_down_years −1.066; vol calm/mid/turbulent 1.893 / 0.317 / 0.794. Sharpe difference vs vol_target_hold: 0.948 vs 1.027, diff −0.079, 90% band [−0.223, 0.077], **p_a_gt_b 0.192**, corr 0.966.

## 7. Verdict

**FAIL.** All four fail `beats_benchmark_oos` (0.946 / 0.913 / 0.823 / 0.698 against 1.065 daily, 1.131 weekly); (a) also sits 0.7 pp inside the 25% OOS drawdown gate. The other gates pass (≥4/6 folds, MDD ≤ 25%, zero liquidations, positive stress return): a clean negative — the benchmark's beta with extra fees.

## 8. Next, and why not run

A weekly *momentum* tilt (Liu–Tsyvinski's sign) belongs to the trend family and would pay (a)'s 2.3%/yr of fees; a weekend *volatility* rule (Baur et al.'s actual finding) is a sizing question for the vol-target engine, not a return signal; cost-aware variants of (b)/(c) that trade only above the fee break-even would be tuning after seeing results. Each is a fifth trial that raises the bar for every family; none has a mechanism strong enough to justify it. Referee note: the tournament's `--every 7` degenerates (b), (c), (d); their registered cadence is `--every 1` (see registry notes).
