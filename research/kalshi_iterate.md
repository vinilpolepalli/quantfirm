# Strategy iteration — 2026-09-12 (not a go-live)

Goal: a taker that is green on **lag-fill backtest** *and* live paper.
Bankroll $250. Fill headline is always **lag**. Touch is a ceiling.

## What we already knew

`one_pct` last-90s 90–97¢ locks: 1-min lag is empty (`raced_out`). Touch
P&L is the race REST is not supposed to win. Write-up:
`research/kalshi_one_pct_week.md`.

Live paper nevertheless filled 7/7 one_pct trades on 12 Sep
(+~$7.3, cash **$258** after the 01:45Z window). Poll is 2s, not 60s, so
the candle lag model is too harsh for that book. 7 trades is not a
strategy. It is a speed experiment.

## Train-only scan (before 2026-08-27)

Last-minute (τ=60) 90–97¢: 99% contested, lag n≈5, EV negative.

Positive lag-EV cells with n_lag≥30 were **88–94¢ favorites with 3–10
minutes left** (τ=240 and τ=600). That finding is frozen into:

| name | rule |
|---|---|
| `mid_lock` | `one_pct` fn, τ 180–300, 88–94¢, spot-agree |
| `spot_lock` | `one_pct` fn, τ 180–660, 88–94¢, spot-agree |
| `rich_fav` | FLB 88–94¢, no spot gate |
| `model_fav` | GBM ≥88% **and** book already 80–94¢ (train late_lock lost on 22–70¢ “certain” fills) |

## Lag-fill scoreboard ($250)

| strategy | universe | train n / pnl / t | TEST n / pnl / t / hit / dd | last 7d n / pnl / t |
|---|---|---|---|---|
| `one_pct` | 7 series | 4 / −5 / −2.3 | 5 / −4 / −1.4 / 0% | 3 / −3 / −1.1 |
| `mid_lock` | 7 series | 48 / −10 / −0.4 | 142 / −42 / −0.9 / 77% / 28% | 61 / −18 / −0.6 |
| `spot_lock` | 7 series | 166 / −5 / −0.1 | 449 / **+117** / 1.12 / 85% / 23% | 212 / +24 / 0.43 |
| `spot_lock` | **5 commodities** | 166 / −5 / −0.1 | 337 / **+96** / 1.12 / 86% / 23% | **148 / +33 / 0.67** |
| `rich_fav` | 7 series | 167 / −3 / −0.1 | 483 / +123 / 1.14 / 85% / 24% | 225 / +27 / 0.45 |
| `model_fav` | 7 series | 9 / −18 / −1.0 | **43 / +70 / 2.69 / 93% / 4.4%** | 12 / +1 / 0.09 |
| `late_lock` | 7 series | 11 / −32 / −0.9 | 49 / +181 / 2.35 / 88% / 16% | 16 / +9 / 0.22 |
| `favorite_div` | 7 series | 441 / +40 / 0.63 | 1283 / +64 / 0.50 / 73% / 31% | 491 / +25 / 0.32 |

Tournament gate (test n≥30, pnl>0, t≥1.5, dd≤30): **`model_fav` and
`late_lock` now clear TEST** after energy/crypto were added. Train n is
still <30 and red. Last week is too thin to trust. Do not promote.

`spot_lock` on the five commodities is the only book with **n>100 on last
week**, positive lag P&L, and a flat (not disastrous) train. t=0.67 is
**not** super-effective. It is the next measurement.

Crypto 15m lag locks lost last week (BTC −$15 on `spot_lock`). They stay
out of the paper book.

## Paper switch (12 Sep ~01:50Z)

Previous live book `one_pct` + BTC/ETH: 7/7, +~$7, still paper.
New live book: **`spot_lock`**, metals **gold,silver,copper,wti,natgas**,
`--no-maker`, no `--live`.

This is not a claim of edge. It is the first lag-fill-compatible trial
with enough expected fills that a few days of paper can move the t-stat.

## Reproduce

```bash
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy spot_lock --fill-mode lag --split test --bankroll 250
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy spot_lock --fill-mode lag --since 2026-09-05T00:00:00Z
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy model_fav --fill-mode lag --split test --bankroll 250
```
