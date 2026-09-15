# Kalshi perps research campaign — referee results (2026-09-15)

Tournament version `2026-09-15.2-campaign` (`tournament.md`, `tournament.json`).
Protocol: `CAMPAIGN.md`. Designer reports: `families/*.md`. Referee: the parent
session, which ran the joint tournament, the deflated Sharpe against the whole
registry, the CSCV probability of overfitting across every walk-forward
configuration, and its own robustness checks on the families whose designers
were cut off. Nobody promoted their own work.

## Verdict

**No family passes. The holdout stays sealed.** Twenty-two walk-forward
trials (sixteen from the campaign, six from the first pass) all fail
`beats_benchmark_oos`, `dsr_ge_0.95` and `pbo_le_0.10`. The best campaign
family, `basis_crowding`, scores OOS Sharpe 1.100 against the benchmark's
1.131 and is the benchmark on 97% of days. The paper incumbent
(`trend_long_only`, 12% vol target, balanced rung) is unchanged.

| item | value |
|---|---|
| benchmark `vol_target_hold` (12% vol) OOS Sharpe / CAGR / max DD | 1.131 / 18.2% / −18.4%, 6/6 folds |
| best campaign trial | `basis_crowding` 1.100 (−0.031 vs benchmark) |
| best deflated Sharpe (bar 0.95) | 0.824 (`basis_crowding`), N = 113 |
| CSCV PBO across 62 walk-forward configurations (bar 0.10) | 0.586, degradation slope −0.953 |
| registry at run start | 52 distinct configurations + 61 declared grid points = N 113 |
| registry now | 79 distinct configurations in 225 rows |
| holdout openings | 1 (the incumbent, first pass); 0 in the campaign |

N for the deflated Sharpe is `registry_count() + n_declared` at the start of
the run: the 52 distinct configurations already in `trial_registry.jsonl`
plus the 61 grid points declared in the family modules' `TRIALS`. The
tournament itself appended rows, so a re-run today would use N = 140 and
every DSR below would fall further. On this history (2,767 OOS days, the
trial Sharpe dispersion the tournament measured) a candidate needs an OOS
Sharpe of roughly 1.4 to clear DSR 0.95 at N = 113; the expected best of 113
null trials is about 0.76 a year.

## What ran

Ten designer agents, one family each, under `CAMPAIGN.md`: hypothesis,
mechanism, external evidence and a grid of at most six configurations
written into the module before the first backtest; DEV window only
(2016-06-01 → 2025-06-30); every CLI run appended to the registry; report
the numbers the tools printed. Eight reports were delivered
(`families/basis_crowding.md`, `crash_filter_beta.md`, `dual_momentum.md`,
`kalshi_micro.md`, `macro_gold.md`, `reversal_seasonality.md`,
`vrp_options.md`, `xsec_momentum.md`). Seven of the ten agents were
terminated by the account's monthly spend limit (HTTP 429, "You've hit your
monthly spend limit") before they finished: `trend_v2` and `allocator_blend`
have modules and registry rows but no designer report, and the planned
adversarial round (attacker agents on the top candidates) was not spawned.
The referee ran the robustness checks for the four unreported
configurations itself (below). The truncation cut the campaign's breadth,
not its verdict: the tournament, DSR and PBO ran on every registered
configuration.

## Joint tournament

Walk-forward, six folds 2018 → 2025-06, the grid point with the best
in-sample Sharpe strictly before each fold scored on that fold only. Cost
taker tier 0 (12 bps + 2.5 bps half-spread per side), weekly rebalance check
with a 3% band, execution at the next open, Kalshi funding (≈0), 3.25% on
idle collateral, Sharpe on excess return over the collateral yield. Per-fold
detail in `tournament.md`.

| rank | trial | idea | OOS Sharpe | OOS CAGR | OOS max DD | folds + | stress SR | DSR | failed gates |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| — | `vol_target_hold` (benchmark) | passive equal-risk vol-targeted long book | 1.131 | 18.2% | −18.4% | 6/6 | — | — | control |
| 1 | `basis_crowding` | cut BTC/ETH when Binance basis or funding says longs are crowded; add on capitulation inside an uptrend | 1.100 | 17.6% | −18.4% | 5/6 | 1.224 | 0.824 | benchmark, DSR, PBO |
| 2 | `vrp_options` | scale crypto by the Deribit DVOL variance-risk premium | 1.099 | 17.0% | −18.4% | 6/6 | 1.246 | 0.823 | benchmark, DSR, PBO |
| 3 | `dual_momentum_skip` | 12-1 month absolute momentum per bloc, relative tilt | 1.047 | 12.0% | −8.6% | 6/6 | 1.008 | 0.784 | benchmark, DSR, PBO |
| 4 | `trend_v2_tsmom` | 12-month TSMOM sign, monthly cadence | 1.031 | 14.3% | −18.4% | 6/6 | 0.972 | 0.769 | benchmark, DSR, PBO |
| 5 | `rs_turn_of_month` | half weight over month-end, full weight in the first days | 1.026 | 14.5% | −16.2% | 4/6 | 1.219 | 0.768 | benchmark, DSR, PBO |
| 6 | `trend_v2_tsmom_live` | 12-month TSMOM, live-book vol targeting | 1.016 | 15.6% | −17.0% | 5/6 | 0.947 | 0.759 | benchmark, DSR, PBO |
| 7 | `crash_filter_beta` | benchmark, cut on drawdown-from-high and vol spikes | 1.011 | 14.7% | −19.6% | 5/6 | 1.355 | 0.751 | benchmark, DSR, PBO |
| 8 | `dual_momentum_6` | dual momentum on six assets (sol, xrp added) | 0.975 | 12.1% | −12.7% | 6/6 | 0.988 | 0.720 | benchmark, DSR, PBO |
| 9 | `rs_weekend_half` | half weight over weekends | 0.958 | 14.9% | −18.4% | 6/6 | 1.212 | 0.708 | benchmark, DSR, PBO |
| 10 | `allocator_blend` | blend of benchmark and incumbent by fixed weight, trend breadth or risk parity | 0.911 | 12.1% | −15.5% | 5/6 | 1.254 | 0.661 | benchmark, DSR, PBO |
| 11 | `trend_v2_baz` | continuous EWMA trend strength (Baz et al. 2015) | 0.907 | 9.5% | −11.8% | 6/6 | 0.850 | 0.655 | benchmark, DSR, PBO |
| 12 | `macro_gold` | metals sleeve gated on DXY and real-yield trends, VIX overlay | 0.881 | 12.5% | −16.3% | 4/6 | 1.062 | 0.631 | benchmark, DSR, PBO |
| 13 | `xsec_momentum` | cross-sectional momentum, long/short and long-only | 0.876 | 17.7% | −30.7% | 5/6 | 1.222 | 0.628 | benchmark, max DD, DSR, PBO |
| 14 | `rs_weekly_reversal` | fade last week's move | 0.823 | 14.5% | −24.3% | 4/6 | 0.676 | 0.571 | benchmark, DSR, PBO |
| 15 | `trend_long_only` (incumbent) | ensemble trend gate on the long book | 0.798 | 9.8% | −12.5% | 6/6 | 1.249 | 0.544 | benchmark, DSR, PBO |
| 16 | `dual_momentum` | 6- or 12-month absolute momentum per bloc | 0.706 | 9.0% | −8.5% | 5/6 | 1.172 | 0.444 | benchmark, DSR, PBO |
| 17 | `breakout` | Donchian channels, long/short | 0.464 | 7.2% | −13.3% | 5/6 | 0.562 | 0.212 | benchmark, DSR, PBO |
| 18 | `tsmom` | multi-lookback TSMOM, long/short | 0.453 | 7.2% | −13.3% | 5/6 | 0.797 | 0.203 | benchmark, DSR, PBO |
| 19 | `ma_trend` | MA crossovers, long/short | 0.422 | 7.4% | −21.1% | 3/6 | 0.891 | 0.181 | benchmark, folds, DSR, PBO |
| 20 | `trend_ensemble` | average of the three, long/short | 0.381 | 6.5% | −15.5% | 5/6 | 0.793 | 0.152 | benchmark, DSR, PBO |
| 21 | `rs_bollinger_mr` | Bollinger-band mean reversion | 0.358 | 4.6% | −5.2% | 6/6 | 0.530 | 0.140 | benchmark, DSR, PBO |
| 22 | `gold_silver_ratio` | long/short the gold–silver ratio | −0.803 | 1.9% | −2.6% | 6/6 | −0.772 | 0.000 | benchmark, DSR, PBO |

Passed by nearly everyone: ≥4/6 folds positive, OOS max DD ≤ 25%, zero
liquidations, positive total return under 1.5× fees plus Binance funding
through Kalshi's deadband. Those gates are inherited from the long book: four
assets that all rose 2018–25 pass them on their own.

## Edge, or the benchmark wearing a hat?

Paired block-bootstrap Sharpe differences against `vol_target_hold` on the
fixed dev run. Designer runs: n_boot 500, n_null 60, on the window stated in
each report. Referee runs: n_boot 300, n_null 40, 2018-01 → 2025-07.

| trial | Sharpe diff | 90% band | p(a > b) | return corr | timing-null percentile | run by |
|---|---:|---|---:|---:|---:|---|
| `basis_crowding` (capitulation) | +0.001 | [−0.061, +0.062] | 0.57 | 0.996 | 0.90 | designer, 2020-06 → |
| `vrp_options` | +0.003 | — | 0.53 | — | — | designer, 2021 → |
| `dual_momentum_skip` | −0.084 | [−0.509, +0.326] | 0.33 | 0.68 | 0.925 | referee |
| `trend_v2_tsmom` | −0.137 | [−0.407, +0.149] | 0.25 | 0.875 | 0.575 | referee |
| `rs_turn_of_month` | −0.079 | [−0.223, +0.077] | 0.19 | 0.966 | 0.85 | designer |
| `trend_v2_tsmom_live` | −0.200 | [−0.489, +0.056] | 0.13 | 0.869 | 0.425 | referee |
| `crash_filter_beta` (fixed d20_w60) | see report | — | 0.91 | — | 1.00 | designer; the walk-forward picked the 0.30 / metals variants in the early folds, so this is the hindsight configuration |
| `allocator_blend` | −0.048 | [−0.228, +0.151] | 0.36 | 0.959 | 0.60 | referee |
| `macro_gold` | −0.183 | [−0.562, +0.130] | 0.18 | 0.821 | 0.58 | designer |
| `dual_momentum` | −0.289 | [−0.797, +0.201] | 0.15 | 0.683 | 0.62 | designer |
| `xsec_momentum` (long-only) | — | — | 0.13 | — | 0.25 | designer |

Reading. The two families nearest the bar are the benchmark plus noise:
`basis_crowding` is byte-identical to it before 2020 and 0.996-correlated
after; `vrp_options` is the benchmark with 0.29 a year more turnover, a lower
CAGR and a deeper drawdown on its own window. Every gate-style overlay
(trend, dual momentum, macro, crash filter) has p(a > b) between 0.13 and
0.36: it gives back more in missed rallies than it saves in the 2018 and
2022 bear legs. `dual_momentum_skip` is the one overlay with real timing
content (null percentile 0.925, OOS drawdown −8.6%) but it trails the
benchmark on Sharpe, its perturbation collapse ratio is 0.47 (Sharpe 0.40 at
a 274-day lookback), and it is a fixed-parameter configuration reported
after the 6-month variant failed. It is a candidate for a future
pre-registered trial, not a promotion.

## Referee checks on the unreported configurations (`robust_*.json`)

| | `trend_v2_tsmom` | `trend_v2_tsmom_live` | `allocator_blend` | `dual_momentum_skip` |
|---|---:|---:|---:|---:|
| fixed dev Sharpe (excess) / CAGR / max DD | 0.803 / 11.8% / −18.5% | 0.741 / 12.0% / −19.3% | 0.892 / 12.3% / −15.8% | 0.856 / 10.2% / −8.6% |
| turnover / fees per year | 3.28 / 0.47% | 4.92 / 0.71% | 1.92 / 0.28% | 2.55 / 0.37% |
| bootstrap Sharpe p5 / p50 / p95 | 0.12 / 0.76 / 1.45 | 0.05 / 0.73 / 1.34 | 0.14 / 0.87 / 1.49 | 0.20 / 0.86 / 1.45 |
| p(Sharpe ≤ 0) | 0.027 | 0.037 | 0.023 | 0.020 |
| perturbation min / median / collapse ratio | 0.72 / 0.80 / 0.89 | 0.55 / 0.73 / 0.75 | 0.86 / 0.95 / 0.96 | 0.40 / 0.78 / 0.47 |
| timing null: real / null mean / null p95 / percentile | 0.80 / 0.74 / 1.02 / 0.575 | 0.74 / 0.74 / 0.96 / 0.425 | 0.89 / 0.85 / 1.10 / 0.60 | 0.86 / 0.56 / 0.93 / 0.925 |
| BTC up-years / down-years Sharpe | 1.28 / −1.32 | 1.31 / −1.42 | 1.37 / −0.85 | 1.27 / −0.80 |
| vol calm / mid / turbulent Sharpe | 1.76 / 0.36 / 0.44 | 1.43 / 0.22 / 0.68 | 1.76 / 0.41 / 0.72 | 1.95 / 0.05 / 0.76 |
| vs benchmark: diff / p(a > b) / corr | −0.137 / 0.25 / 0.875 | −0.200 / 0.13 / 0.869 | −0.048 / 0.36 / 0.959 | −0.084 / 0.33 / 0.68 |

These runs replaced the partial `robust_trend_v2_tsmom.json` and
`robust_allocator_blend.json` written before their designer agents were cut
off; all four files are now the referee's.

## What the campaign settles

1. **The long book is the strategy.** Every gate the campaign built spends
   more in missed rallies than it saves in bear legs on this sample. The
   incumbent's value is the drawdown shape (−12.5% vs −18.4% OOS; +23.7% at
   −4.9% vs +27.1% at −11.6% on the one holdout opening), not Sharpe.
2. **Overlays that read a new series add no information at a daily
   horizon.** Options-implied vol (DVOL), perp basis and funding, DXY and
   real yields, VIX: each tilt is either 0.96–0.996 correlated with the
   benchmark or worse than it.
3. **Fee-paying ideas die at 24–29 bps a round trip.** Weekly reversal
   (fees are 24–63% of the gap to the benchmark), cross-sectional long/short
   (0.15), and every Kalshi-native intraday idea (`families/kalshi_micro.md`:
   nothing above 2× round-trip cost across about 30 cells; the one t ≈ 2.9
   is the expected false positive).
4. **Multiple testing is now the binding constraint.** The registry is
   append-only, so each new idea raises the bar for the next. A family that
   wants to be promoted has to be right by a wide margin, not by a fold.

## Still open (each is a new pre-registered trial)

* `dual_momentum_skip` with hysteresis around the 3.25% hurdle, registered
  before running, same grid discipline.
* Diversifiers: copper, US500 and WTI perps once listed (four assets at 0.9
  BTC–ETH correlation are two bets).
* Kalshi's own funding once the metals history is months long; the
  September BTC premium (+14.8%/yr) if it persists above the deadband.
* A fee tier below 12 bps, which changes the arithmetic of every fee-bound
  idea.

Files: `tournament.md`, `tournament.json`, `trial_registry.jsonl` (225
rows), `robust_*.json`, `families/*.md`, `families/kalshi_micro_analysis.py`.
