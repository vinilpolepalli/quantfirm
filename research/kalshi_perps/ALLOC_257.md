# $257 on Kalshi perps — or "just perps" — 2026-09-18

Owner asked whether we should look through the hundreds of perpetual-futures
strategies online, plus the math, and put the $257 on them. **Nothing here
was traded.** Numbers were recomputed this session from the incentive paper
log, `granularity.json`, and Kalshi's public `/margin` endpoints. The
command that reprints them:

```bash
python3 scripts/perps_alloc_257.py --live
```

## Verdict

| action | call | why |
|---|---|---|
| Move the $257 onto Kalshi perps | **NO** | predictions vs margin are separate accounts; the money is reserved for the LIP; last-24h paper accrual is **$3.12/day** against a perps expected **$0.07/day** |
| Dump internet / YouTube / "JS perps" catalogs into the registry | **NO** | the desk already ran those families; every extra trial raises the deflated-Sharpe bar |
| Restart the halted perps desk | **NO** | owner halt 2026-09-16; two paper days; §7 wants ≥6 weeks shadow |
| Register a BTC funding-cost overlay today | **NO** | carry is still live, and that is a watch item, not a trial. `basis_crowding` already used funding as a signal and lost to the control |
| Arm the incentive book | **not this memo** | still `INSUFFICIENT` (43.2h of 48h). A GO is a $40 canary, not $257 |

The $257 stays where it is.

## The $257 is not sitting on a perp

Kalshi predictions and Kalshi Prime margin are different accounts,
different regulators (DCM vs FCM), different balances. A liquidation on
perps cannot touch the predictions deposit; the reverse is also true. Using
the $257 on perps is not a config flip. It is: apply for margin, finish the
tutorial, transfer out of predictions, and abandon the LIP measurement the
shadow book is halfway through. Help center, 2026-08-17:
https://help.kalshi.com/en/articles/15357608-your-perpetuals-margin-account

`state/INCENTIVE_LIVE` is absent. `state/KILL_SWITCH_PERPS` is present.
`config/perps.json` is `HALTED`, `live: false`.

## Recomputed: incentive vs perps at $257

Incentive paper book (`state/kalshi_incentive_paper.json`), last tick
2026-09-18T11:27Z, 30 ticks, **$59.09 accrued, verdict INSUFFICIENT**.

| window | what it is | $/day |
|---|---|---|
| since inception (43.2h) | the over-read. Do not use. | **$32.84** |
| last 48h wall-clock | still polluted by the first hours | $29.54 |
| last 24h wall-clock | dollars the log actually booked yesterday | **$3.12** |
| last 12h wall-clock | more recent, still uncredited | **$1.83** |
| board identity (2026-09-16) | $106,033 paid / $17,067,304 resting × $257 | **$1.59** |
| paper-gate trailing 24h | capped `interval_h` span is 8h of 24h | **refuses (too gappy)** |

The later ticks are ~$0.30 each, but the scheduler is skipping and
`MAX_INTERVAL_H = 1.0`, so a 5-hour gap books one hour. That is conservative
on purpose. The wall-clock last day is the honest human number; the identity
is the bound. Nobody has seen a credited LIP reward.

Perps, same $257, from the $250 whole-contract rows in
`research/kalshi_perps/granularity.json` (2018-01 → 2025-06, tier-0 taker,
Kalshi funding). Ratios do not change at $257; dollars scale.

| book | $/year | $/day | typical DD | what it is |
|---|---:|---:|---:|---|
| `trend_long_only` 12% vol (incumbent) | **$26.11** | **$0.07** | **−$24.08** | gated beta. No losing calendar year in the sim. Not alpha. |
| `vol_target_hold` 12% vol (control) | $38.34 | $0.11 | −$56.51 | the thing the campaign could not beat. Lost 2018 and 2022. |
| idle on margin at 3.25% | $8.35 | $0.02 | $0 | only after a transfer, and only if the $250 average-balance rule is met |

A last-day LIP estimate of $3.12 is about **forty times** the gated perps
expectation. Even the board identity, $1.59/day, is about twenty times.
Moving the $257 onto perps is swapping a possible uncredited subsidy for a
beta bet that, at this size, is a couple of dinners a year and a $24 hole
when crypto or gold have a bad quarter.

Do not annualise the $3.12. The first four LIP numbers were wrong by an
order of magnitude each, and early-tick $32/day is the same trap again.

## "There are thousands of strats online"

This desk already ran the catalog. Round 1 was thirteen trend dresses.
Round 2 was twelve families from ten agents. Breadth was measured on all
20 tradable crypto perps. Residual cross-sectional momentum is the only
thing that improved the book, and it still failed the deflated-Sharpe gate
(0.695 vs 0.95) because the coins did not exist long enough.

The trial registry is append-only and now has **246 rows**. On this history
a candidate already needs an out-of-sample Sharpe near 1.4 to clear DSR
0.95. Registering a hundred YouTube grids does not search a larger space.
It raises the bar for the next idea that might be real.

| internet name | already tested as | result |
|---|---|---|
| grid / DCA / martingale | intraday + leverage | 115%/yr fee hurdle; recovery sizing is ruin |
| funding farm / cash-and-carry | funding carry | deadband; ETH still ~89% zero; offshore short is not a US account |
| basis / "funding says crowded" | `basis_crowding` | 1.100 vs 1.131, 0.996 correlated with the long book |
| scalping / tape / MM | `kalshi_micro` | 6.8 bps gross vs 49 bps hurdle; no retail rebates |
| EMA / MACD / RSI / Ichimoku | trend, MA, TSMOM, trend_v2 | all lost to vol-targeted long-only |
| weekend / TOM / OpEx | seasonality | 1.026 / 0.958; fees ate the gap |
| crash / VIX / vol spike | `crash_filter_beta` | 1.011; the working configs rode 2022 |
| dual / relative momentum | `dual_momentum` | 1.047, still trails the passive book |
| alt rotation / "more coins" | xsec + `BREADTH_FINDING.md` | 16 names = 1.98 bets; 10 of 16 lost money 2021–25 |
| GPT / copy-trading | Alpha Arena | 4/6 models lost 31–63% in 17 days |

The math that kills the fast ones is not a vibe. Tier-0 taker is 12 bps of
**notional** on open and on close. A 24 bps round trip, twenty times a
month, at 2x, is a 115% annual hurdle before the spread on anything that
is not BTC. Slow is the only operating point this venue pays.

## Live venue, this session (sorted by funding time)

Kalshi `/margin` 2026-09-18. The API returns newest-first; `tail(90)` on
an unsorted series reads June. Disk loaders already `sort_index()`. Live
numbers below are sorted.

| market | last-90 holding cost | last-30 | last-12 | now |
|---|---:|---:|---:|---|
| BTC | **+15.13%/yr**, 20% zero (was +14.25% / 24% zero on disk through 09-15) | +13.72%, 17% zero | +9.9%, 33% zero | estimate **0**; last two prints 0 |
| ETH | −1.51%/yr, 89% zero | −0.41%, 97% zero | **0**, 12/12 zero | estimate 0 |
| gold | 7 prints, 5 zero | — | — | too thin; do not quote a rate |
| silver | 7 prints, 6 zero | — | — | too thin |

BTC carry is still live and a bit stronger on the 90-window than on 09-15.
ETH went quieter. Metals still have a week of history. `perps_watch`
was annualising metals as if they printed three times a day; that 3× error
is fixed in this change and is why gold's "9.9%" from an unsorted 3× formula
is not used here. The CLI, which uses `funding_per_day`, printed gold at
+3.29% over 7 intervals — still two nonzero prints, still not a rate.

Listings: 20 tradable crypto + gold + silver. DOT / HBAR / XLM still
inactive. **No copper, no US500, no WTI.** The missing diversifier has not
arrived.

## "JS perps" — Jupiter, Hyperliquid, just perps

Reading it both ways.

**Just perps in general.** The offshore literature is the same set: funding
carry (compressed in 2025–26, and it needs a short), basis arb (95% forced
exits in the large-sample study; two taker fees exceed the spread), market
making (adverse selection, rebate floors), and trend (this desk's
incumbent). Retail track records are bad in the way that is no longer a
debate: median Hyperliquid wallet −$67 over 30 days; 97% of persistent
Brazilian day traders lost. At $257 the constraint is not a missing
indicator. It is cost, correlation, and sample.

**Jupiter perps / JLP.** Solana, no KYC, $10 min, 1.1–250×, trader-vs-LP.
US person + unregulated perp + this firm's existing Kalshi deposit is a
custody and conduct change, not a strategy upgrade. Holding JLP is being
the house, which is a different bet (trader PnL + SOL/BTC/ETH inventory)
and is not what the $257 was deposited for.

**Hyperliquid.** The interface geoblocks US users. The only public
LLM-on-HL contest this desk already cited lost real money. It is not a
venue we can fund from this account.

The US-legal retail perp is Kalshi. That is why the desk exists, and why
the $257 staying on Kalshi is not a lack of imagination.

## The one opening that is still an opening

§9 of `docs/KALSHI_PERPS.md` named a funding-conditional overlay if Kalshi
BTC funding stayed outside the deadband. It has: last 90 intervals cost a
long **+15.13% a year** zeros included. That is a cost, not a crash signal.
`basis_crowding` already cut BTC/ETH when *offshore* funding/basis looked
crowded and produced a book 0.996-correlated with the control.

A cost overlay ("do not hold BTC while this venue bills ~15%") is
arithmetically motivated and still **not registered here**. Three months,
one name, and a registry that already taxes the next trial. Let
`scripts/perps_watch.py` keep measuring it. The first registration wants
more Kalshi-native history and a grid of at most two points, declared
before the first run, against the existing miss.

Gold carry is still "two nonzero weekday prints." Wait.

## What to do with the $257

1. Leave it in predictions. Do not transfer it to margin.
2. Let the incentive paper book reach 48h and speak. The gate is in
   `scripts/kalshi_incentive_paper.py`. Agents report the code's verdict.
3. If that verdict is `GO`, the first real money is **~$40 across two
   long-duration markets**, not $257 across eight. That is already written
   down. A credited reward is the thing nobody has seen.
4. If that verdict is `NO` and stays `NO`, the $257 is free. Perps is then
   an owner risk decision on gated beta, after the §7 paper → demo → canary
   ladder, not a strategy search.
5. Do not start a swarm that mines TradingView scripts. The next useful
   perps work is a listing that is not crypto, or a funding overlay with
   enough of Kalshi's own history to be a real test.

Paper books on 2026-09-16, when the owner halted them, were $249.75 /
$249.92 / $249.83 after two days. That is not a result in either
direction.
