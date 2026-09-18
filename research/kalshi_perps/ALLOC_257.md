# $257 on Kalshi perps — 2026-09-18, owner override

The morning memo said leave the $257 on the incentive book. The owner killed
that desk the same afternoon and will move the $257 to perps margin
themselves. **This file is the override.** Nothing here was traded.

```bash
python3 scripts/perps_alloc_257.py --live
```

## Verdict

| action | call |
|---|---|
| Incentive / LIP desk | **DEAD.** Collector, quoter, runbook, paper state removed. Do not rebuild. |
| Transfer $257 predictions → perps margin | **Owner does this.** Agents do not move money. |
| Lift `KILL_SWITCH_PERPS` / set `live: true` | **NO, not this commit.** Transfer ≠ go-live. Gate is still §7. |
| Dump internet / Jupiter / Hyperliquid catalogs into the registry | **NO.** Already tested; more trials raise the DSR bar. |
| Register a BTC funding-cost overlay today | **NO.** Watch it. `basis_crowding` already used funding as a signal and lost. |

## What $257 is, on this desk

Predictions and Kalshi Prime margin are still separate accounts. The owner
transfers; an agent does not. After the transfer the number that matters is
the $250-row whole-contract sim in `granularity.json`, scaled to $257:

| book | $/year | $/day | typical hole |
|---|---:|---:|---:|
| `trend_long_only` 12% vol (incumbent) | $26.11 | $0.07 | −$24.08 |
| `vol_target_hold` 12% vol (control) | $38.34 | $0.11 | −$56.51 |
| idle on margin at 3.25% | $8.35 | $0.02 | $0 |

That is gated beta, not alpha. The campaign's best overlay still lost to the
control. The residual-momentum sleeve improved the book and still failed
deflated Sharpe. Paper books on 2026-09-16, when the owner halted them, were
$249.75 / $249.92 / $249.83 after two days. That is not a result.

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

1. Owner transfers $257 to the perps margin account.
2. Then we work the perps desk: paper first, §7 still binds, kill switch
   stays until they say otherwise.
