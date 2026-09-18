# $257 on Kalshi perps — 2026-09-18, paper first

The morning memo said leave the $257 on the incentive book. The owner killed
that desk the same afternoon and will move the $257 to perps margin
themselves. They then asked to paper-trade a bunch of strats, or backtest
the one we found, **before** transferring. **This file is the override.**
Nothing here was traded live.

```bash
python3 scripts/perps_alloc_257.py --live
```

## Verdict

| action | call |
|---|---|
| Incentive / LIP desk | **DEAD.** Collector, quoter, runbook, paper state removed. Do not rebuild. |
| Paper the three already-measured books | **YES, now.** Incumbent / candidate / growth. Shadow adapter. |
| Paper a catalog of internet / Jupiter / HL systems | **NO.** Already tested; more trials raise the DSR bar. |
| Re-run CLI `backtest` / `holdout` for a demo | **NO.** `registry.record` and the sealed vault. The numbers already exist. |
| Transfer $257 predictions → perps margin | **Owner does this, after paper has a reading.** Agents do not move money. |
| Set `live: true` | **NO.** Transfer ≠ go-live. Gate is still §7. |
| Register a BTC funding-cost overlay today | **NO.** Watch it. `basis_crowding` already used funding as a signal and lost. |

## Why not paper a bunch of new strats

Paper-before-transfer is the right order. Papering *everything that looks
tradable on the internet* is the wrong one.

The desk already ran that catalog through the gauntlet: thirteen trend
dresses, then twelve campaign families, then a residual-momentum sleeve.
Twenty-two walk-forward trials. Nothing passed the alpha gate. The
control (`vol_target_hold`) beat almost every overlay. The sleeve that
helped still failed deflated Sharpe. Internet/Jupiter/Hyperliquid lists
are the same objects under other names.

The trial registry is append-only. Each new family raises the
deflated-Sharpe bar for every other idea. On this history a candidate
now needs an out-of-sample Sharpe near 1.4. Dumping twenty fresh
lookalikes into paper does not buy twenty independent readings; it
buys a higher hurdle and a story that something "is working" on two
days of $250.

So the paper books are the three that were already built and measured:

| book | rule | why it is in paper |
|---|---|---|
| incumbent | `trend_long_only` @ 12% vol, BTC/ETH/gold/silver | the deployable posture: gated beta, not alpha |
| candidate | `blend_core_sleeve` @ 12% vol, 30% residual sleeve | the one thing that beat the core OOS; still fails DSR |
| growth | same blend @ 18% vol, 40% sleeve | same evidence, dial up; owner said risk is acceptable |

`vol_target_hold` is the already-backtested control (OOS Sharpe 1.13,
holdout +27.1% / −11.6%). It does not need a fourth paper book to
"find" it, and adding one is not a new trial.

The backtests that matter are already on disk:
`research/kalshi_perps/tournament.md`, `CAMPAIGN_RESULTS.md`,
`families/xsmom_residual.md`, `holdout_trend_long_only.json`,
`granularity.json`. Re-running them through the CLI would append
registry rows and, if someone passed `--i-am-the-judge`, reopen a
sealed holdout. Do not.

## What $257 is, on this desk

Predictions and Kalshi Prime margin are still separate accounts. The owner
transfers; an agent does not. After the transfer the number that matters is
the $250-row whole-contract sim in `granularity.json`, scaled to $257:

| book | $/year | $/day | typical hole |
|---|---:|---:|---:|
| `trend_long_only` 12% vol (incumbent) | $26.11 | $0.07 | −$24.08 |
| `vol_target_hold` 12% vol (control) | $38.34 | $0.11 | −$56.51 |
| idle on margin at 3.25% | $8.35 | $0.02 | $0 |

That is gated beta, not alpha. Two days of paper at halt ($249.75 /
$249.92 / $249.83) is not a result either. A reading takes weeks, which
is why this restarts the daily shadow tick instead of waiting on a
transfer.

## What stays true from the morning pass

Live Kalshi `/margin` 2026-09-18, funding sorted by time (the API is
newest-first; an unsorted `tail(90)` reads June):

| market | last-90 holding cost | now |
|---|---:|---|
| BTC | **+15.13%/yr**, 20% zero | estimate 0; last two prints 0 |
| ETH | −1.51%/yr, 89% zero | last 12 prints 0 |
| gold / silver | 7 prints | too thin to quote a rate |

20 tradable crypto + gold + silver. No copper, no US500, no WTI. Sixteen
extra coins are still ~2 bets. Tier-0 taker is 12 bps of notional on open
and close; twenty round trips a month at 2x is a ~115%/yr hurdle.

Already killed, do not re-litigate: grid/DCA/martingale, funding farm,
basis/crowding, scalping/MM, EMA/MACD/RSI, weekend/TOM, crash/VIX filters,
dual momentum, raw alt rotation, LLM/copy-trading, Jupiter, Hyperliquid.

The one opening that is still an opening: a BTC funding-cost overlay if this
venue keeps billing longs ~15%. Three months, one name. Let
`scripts/perps_watch.py` measure it. Do not register it to start the next
session.

## Next

1. Shadow/paper is on: three books, daily cron, `live: false`.
2. Owner transfers the $257 after those books have a reading they want
   to fund — not so the books can start.
3. §7 still binds. A transfer is not a go-live.
