# Risky / diverse book — can $250 2× in a week?

Owner ask (2026-09-12): try risky, diverse strategies; see if the
book can double every week. Paper only. `KALSHI_LIVE` stays unset.

**Doubling every week means +$250 / 7 days, every week.** That is
~5,200% annualized if it compounded. No registered 15-minute taker
does that as a *rate*. A leveraged favorite *can* print a 2× calendar
week in this sample. It also prints −70% to −90% drawdowns and already
lost in train.

## What we registered

| name | what | stake |
|---|---|---|
| `sprint` | last 90s 88–97¢ lock | 15% |
| `yolo_lock` | 88–94¢ FLB, `kelly_mult=1` | 18% cap |
| `nuke_lock` | same, `kelly_mult=3` | 35% cap |
| `longshot` | 8–22¢ underdogs | 10% |
| `yolo_follow` | follow ≥15 bp open impulse | 15% |
| `yolo_book` | sprint + 88–94¢ fav + follow (no longshot spam) | 15% |

A first draft of `yolo_book` bought every 8–22¢ dog. Lag hit ~7% and
the mix went to −$247 / 99% DD. That sleeve is registered as `longshot`
and is **not** in the paper mix.

## Lag-fill, $250, 7 series

| spec | train | TEST | last 7d | best week | weeks with ≥+$250 |
|---|---|---|---|---|---|
| `rich_fav` (4%) | 167 / −$3 / t=−0.07 / dd 22% | 483 / +$123 / t=1.14 / dd 24% | +$27 | +$65 | **0** |
| `sprint` | 4 / −$9 / hit 0% | 6 / −$21 / hit 0% | −$6 | −$3 | **0** |
| `sprint` TEST **touch** | — | 553 / **−$227** / hit 91% / **dd 91%** | — | −$26 | **0** |
| `longshot` | 581 / −$200 / hit 7% / dd 85% | 1098 / −$247 / hit 8% / dd 99% | −$216 | +$17 | **0** |
| `yolo_follow` | 0 fills | 1 / −$2 | −$2 | — | **0** |
| `yolo_lock` 18% | 167 / −$74 / dd **72%** | 499 / +$701 / t=0.49 / dd **76%** | +$73 | **+$505** | **2** (W35, W37) |
| `nuke_lock` 35% | 148 / −$200 / dd **93%** | 490 / +$661 / t=0.13 / dd **92%** | −$39 | **+$1,326** | **2** (W35, W37) |
| `yolo_book` | 172 / −$56 / dd 65% | 509 / +$444 / t=0.46 / dd 71% | +$37 | **+$386** | **1** (W35) |

`nuke_lock` W36 was **−$962**. Same strategy, next week. t-stat 0.13.

### Week tape for `yolo_lock` (the only book that actually 2×’d)

| week | pnl | n |
|---|---|---|
| 2026-W33 (train) | **−$128** | 22 |
| 2026-W34 | +$24 | 92 |
| 2026-W35 | **+$505** | 74 |
| 2026-W36 | −$183 | 220 |
| 2026-W37 (this week, partial) | +$127 last-7d slice | 205 |

Two doubles, one train wipe, one test give-back. **Not every week.**

## Why 2× every week is not a plan

90¢ locks pay ~10¢ when they win and lose the whole stake when they
don't. To make +$250 you need either ~20 all-wins at 15–18% of the
book, or a handful of longshot jackpots. Last-minute lag fills do not
exist (raced out). Touch last-minute at 15% stake **lost $227** on test
at 91% hit — 91% is not enough when a miss is 6–8× a win.

Longshots hit ~7–8% after lag. They cannot 2×; they go to zero.

The 2× weeks are **leverage on the same 88–94¢ favorite** that `rich_fav`
already trades at 4%. Size it 4–5× and a good copper/natgas week looks
like a miracle; gold's test drag looks like ruin. Train already saw the
ruin (W33).

## Paper switch (~2026-09-12 02:20Z)

Live shadow book: **`yolo_book`**, universe
**gold,silver,copper,wti,natgas,btc,eth**, 15% cap, 40% daily stop,
maker off, no `--live`.

This is a volatility experiment, not a promotion. `nuke_lock` stays
off the paper engine (train already −80%).

```bash
python3 scripts/kalshi_score_yolo.py
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy yolo_lock --fill-mode lag --split test --bankroll 250
```
