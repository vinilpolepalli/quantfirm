# Strategy tournament #1 — results and verdict (2026-07-31)

**Verdict: NO-GO. No strategy is approved for live capital.**

The eval worked. That is the headline: five designer agents produced
strategies that all beat every baseline on six years of development data, and
the verification gauntlet — one-shot holdout year, deflated Sharpe, and
adversarial refutation — correctly identified all of it as regime beta rather
than deployable alpha. A firm without these gates would have shipped it.

## Format

- 5 designer agents, one strategy family each, optimizing the shared eval:
  out-of-sample walk-forward net Sharpe (5 folds) on dev data
  (2019-01 → 2025-06), under full market costs (0.93%/side), holdout
  untouched, every trial counted (203 total across the tournament).
- 1 judge agent: ran the holdout year (2025-07 → 2026-06) once per candidate,
  cost scenarios, ±25% parameter perturbations, line-by-line causality audit.
- 2 adversarial agents attacking the surviving pick (lookahead, regime
  dependence, whipsaw, parameter cliffs, cross-asset, capacity).

## Dev-period leaderboard (all beat the 1.11–1.12 baseline bar)

| strategy | dev OOS Sharpe | dev maxDD | turnover/yr | ETH Sharpe |
|---|---|---|---|---|
| composite_ensemble | **1.651** | −34% | 3.8 | 0.97 |
| breakout_hold | 1.584 | −49% | 7.7 | 1.16 |
| slow_trend | 1.462 | −43% | 8.5 | 0.95 |
| vol_regime | 1.385 | −48% | 2.0 | 1.04 |
| drawdown_filter | 1.316 | −57% | — | — |

Causality audit: clean, all five (trailing windows, positive shifts only).
Fragility: none — parameter surfaces are plateaus (66–94% Sharpe retention
under ±25% perturbation).

## The holdout year killed everything

2025-07 → 2026-06 was a **−45% BTC bear** (107,377 → 58,625):

| strategy | dev OOS | holdout | holdout maxDD |
|---|---|---|---|
| composite_ensemble | +1.65 | **−1.23** | −22% |
| slow_trend | +1.46 | −1.23 | −23% |
| breakout_hold | +1.58 | −2.29 | −31% |
| vol_regime | +1.39 | −2.34 | −50% |
| drawdown_filter | +1.32 | −2.09 | −57% |
| *baseline: trend_vol_composite* | +1.11 | −1.34 | −32% |
| *baseline: buy_and_hold* | +1.12 | −1.63 | −54% |

- Retention rule (holdout ≥ 50% of dev): **0/5 pass.**
- Not a cost artifact: the best candidate loses in the holdout **even at
  zero cost** (gross Sharpe −1.08).
- Deflated Sharpe: best dev Sharpe (1.651) after 203 trials → **0.09
  probability** of being real; holdout DSR ≈ 6×10⁻⁵.
- Silver lining the risk desk noted: composite_ensemble and slow_trend lost
  *far* less than buy-and-hold (−22% vs −54% maxDD) — the vol gates and
  trend filters genuinely cut bear damage. They are risk reducers, not alpha.

## Adversarial findings (on the would-be fallback)

1. **Regime dependence (fatal):** 2019–2021 supplies ~111% of total
  log-return; from 2022-01 onward, cumulative net return is −18% with ~0.0
  Sharpe. The dev "edge" is one bull market, counted once.
2. **Risk-policy incompatibility:** dev-path maxDD −58% vs a −40% kill
  switch — replayed historically, the kill switch fires in Sep-2022 and the
  strategy spends 19% of the dev period below the trip level.
3. **No alpha vs B&H:** net dev Sharpe 1.13 vs 1.12 for holding — diluted
  beta plus 17%/yr cost drag at 18.6 turnover.
4. Whipsaw: 11% of position changes reverse within 24h.
5. Ops: repo candle history ends 2026-06-30 and Kraken tops up only ~30
  days — the nightly refresh is load-bearing; a gap check belongs in the
  engine (added to backlog).

## Standing decision

- `config/live.json` stays `enabled: false`, lifecycle `NO_GO`.
- `composite_ensemble` sits in the WATCH seat: nightly revalidation tracks
  it as new data arrives; it may be promoted only by a future tournament
  round passing the full gauntlet (see FIRM.md §2 for the gates).
- The $250 stays uninvested. The firm's own verification standard — the one
  thing that separates a quant process from gambling with extra steps — says
  a long-only BTC book had no deployable edge as of this data.

## What a next round could try (research desk backlog)

- Regime-conditional exposure with a *bear-regime* target of ~0 (the current
  candidates keep buying bear rallies).
- Multi-asset long-flat allocation (BTC/ETH/SOL) with cross-sectional gates.
- Limit-order execution model (cuts the cost hurdle roughly 3×, widening the
  viable strategy space).
- Longer holdout + CSCV/PBO once the trial registry accumulates history.
