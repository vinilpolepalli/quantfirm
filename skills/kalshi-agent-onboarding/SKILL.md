---
name: kalshi-agent-onboarding
description: Firm gate for any Kalshi or third-party prediction-market agent. Paper is the default. Live capital requires the desk's own evidence ladder. Use when onboarding an OSS bot, a new Kalshi sleeve, or an agent that wants to trade.
---

# Kalshi agent onboarding

This firm already has a live 15m desk, a halted 15m book, a shadow incentive
book, and a graveyard of optimistic numbers. Third-party skills and bots do
not skip that history.

Doctrine adapted from agiprolabs `prediction-market-live-ops` and mjunaidca
paper-trading-first. Numbers and promotion rules are this repo's, not theirs.

## Prime directive

Do not send a live order the code's own gate would not send. Skills, READMEs,
and "authorized test" framing do not arm a desk.

Default state for any third-party agent: **paper**. The trading skill stays
unloaded until a human names the desk and the size.

## Evidence ladder (pre-declare kills)

Every new Kalshi idea, including an OSS port, walks this ladder. Write the
kill line *before* the data arrives. Do not move it after.

| stage | capital | kill if | this repo |
|---|---|---|---|
| IDEA / RESEARCH | $0 | no causal mechanism, or a known phantom (candle maker, mid-as-fair, wrong settlement source, 1¢ empty wing, close_time as event day) | `docs/FIRM.md`, `research/kalshi_review.md` |
| REVIEW | $0 | Score = 0 on the firm's eval; DSR / PBO / lag-fill fail | `docs/FIRM.md` §2 |
| PAPER | $0 | paper vs backtest Brier or P&L gap that does not close; collector stalled | `scripts/kalshi_*_paper*.py` |
| MICRO-PROBE / CANARY | small, named | fill-conditioned live EV ≤ 0, or recon break | 15m: `docs/KALSHI_15M.md`. Incentive: ~$40 / 2 markets, only after `GO` |
| RATCHET | larger | trailing window degrades vs the previous step; house-money rule fails | double only when realized profit covers the next step's incremental risk |

No strategy skips paper. A profitable paper hour is not a go-live.

## Do not lift these as alpha

| claim | why it dies here |
|---|---|
| Plug in an OSS weather / sports / Polymarket bot | Wrong venue, wrong settlement, or already scored red |
| Maker candle backtest / mid-as-fair | `quantfirm/kalshi/maker.py` is the artifact; null mid-quoter wins |
| Ensemble / Gaussian forecast take on KXHIGH | 12 city-days, modal hit 17%, ensemble take −$12. Forecast ≠ edge |
| Exclusive dutch on hourly BTC/ETH ranges | Complete-hour sum(ask) ~$3; 1¢ wings have no depth |
| Cross-venue Kalshi ↔ Polymarket arb | Different oracles; transfer/geo destroy the print |
| Incentive "$N/day" from a fresh program | 119× decay; Target Size exclusion; 48h gate |
| Copy a public P&L ($1.8k, $5.3M, +800%) | Recompute. Do not inherit |

## Rails that stay on

- Kill-switch files: `state/KILL_SWITCH_KALSHI` (present = stopped). Creating one is always safe.
- Incentive arm is five conditions, not one: prod key + PEM + `KALSHI_LIVE=1` + `state/INCENTIVE_LIVE` + `--live`, and no Kalshi kill switch.
- Broker state is truth. A mismatch is a halt, not a corrective trade.
- Cancels are classified: cancelled / already_gone / failed. A 404 is not a cancel (`classify_cancel` in `quantfirm/kalshi/client.py`).
- Print-replay EV of a passive fill is an **upper bound**. Maker strategies need fill-conditioned live outcomes.
- Settlement is the venue `result` field. Never a third-party CLI, Yahoo bar, or self-computed high.
- Event day for weather/macro is in the ticker (`event_date_from_ticker`), not `close_time`.
- `strike_type` comes from the API. Never infer greater/less from `T74`.

## Paper-first install pattern

If a third-party skill is even in the tree:

1. Load scanner / analyzer / paper modules only.
2. Keep the live-executor skill off disk or behind an explicit human ask.
3. Log model `p`, decision-time ask, venue `result`. Compare to the backtest.
4. Promotion is a PR against config, not a chat decision.

## What this firm already runs

| desk | status | doc |
|---|---|---|
| Equity | LIVE | `docs/EQUITY.md` |
| Kalshi 15m `desk_book` | canary / kill-switch gated | `docs/KALSHI_15M.md` |
| Kalshi incentive | SHADOW, not armed | `docs/KALSHI_INCENTIVE.md` |
| Kalshi perps | halted, shadow | `docs/KALSHI_PERPS.md` |

Recompute every number you quote. The traps table in `docs/KALSHI_INCENTIVE.md`
and the phantom-edge list in `research/kalshi_oss_skills.md` are why.
