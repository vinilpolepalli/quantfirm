# Perps research campaign, round 2 — breadth

You are one designer in a swarm. Round 1 tested twelve ideas on four assets
and none beat a vol-targeted long-only book. Read
`research/kalshi_perps/CAMPAIGN_RESULTS.md` before you start: it says what
has already failed and why, and repeating one of those experiments is the one
way to waste this round.

The protocol is `CAMPAIGN.md` — pre-register, DEV only, one file, causal by
construction, the venue's costs, report what the tools printed. Everything
below is what changed for round 2.

## Why this round exists

Round 1's diagnosis was structural. Four assets at 0.9 BTC–ETH correlation
are two bets, not four, so nothing cross-sectional was testable: the
cross-sectional momentum family scored 0.154 because a four-name cross-section
is not a cross-section. Kalshi lists **23 perps**. The desk now has specs,
price proxies and a backtester that handles a universe whose members list at
different times. Round 2 asks the questions that needed breadth.

## The universe you now have

Twenty of the 23 perps have a real two-sided quote (`TRADABLE_UNIVERSE`);
DOT, HBAR and XLM are listed with zero open interest, zero volume and no
quote, so they are not tradable and are excluded. `BREADTH_UNIVERSE` is the
subset with Coinbase spot history from 2021-09-30 or earlier — that is what a
cross-sectional backtest starting 2021-10 can actually use.

Spot proxies start at very different times: BTC 2015-07, ETH 2016-05, LTC
2016-08, BCH 2017-12, XRP 2019-02, LINK 2019-06, ZEC and AAVE 2020-12, ADA
2021-03, DOGE / DOT / SOL 2021-06, SHIB 2021-09, NEAR 2022-09, HBAR 2022-10,
SUI 2023-05, VVV 2025-01, WLD 2025-04, BNB 2025-10, HYPE 2026-02. The
backtester now starts when the minimum number of assets is available rather
than when the last one lists, and an asset contributes nothing before it
lists or during a delisting gap. Use the availability mask; do not hand-roll
your own.

## Three things that will decide your result

**1. Spreads are per asset now, and the alts are wide.** Measured at top of
book on 2026-09-15, half-spreads run from 0.2 bps (BTC) and 0.4 (ETH) to 9.7
(LINK), 9.1 (WLD), 8.2 (NEAR) and 7.6 (ZEC). With the 12 bps tier-0 taker
fee, a round trip on BTC costs about 24 bps and on LINK about 43 bps. A
weekly-rebalanced fifteen-name cross-sectional book turns over a lot; at 40
bps a round trip, the gross edge has to be large before anything reaches the
Sharpe. Slow beats fast here, and you should expect to find that cadence
matters more than signal cleverness. Report fees as a fraction of the gap
between your book and the control — round 1's seasonality families lost
24–63% of their edge to fees and that is what killed them.

**2. Survivorship bias is real and you must quantify it.** These 23 perps are
the ones Kalshi lists *today*. A 2021 investor did not know that SUI or HYPE
would exist, nor which 2021 alts would still be quoted in 2026. A long-only
cross-sectional book over today's survivors is biased upward, and you must
say by how much: run your strategy on the assets that a point-in-time
investor could have held, and report both numbers. A long/short book is less
exposed to this than a long-only one — say which yours is. A family that
reports a beautiful number without this test will be failed by the referee.

**3. The bar is higher than round 1's, because round 1 happened.** The trial
registry is append-only and now holds 79 distinct configurations. The
deflated Sharpe counts every trial anyone has ever run, so on this history a
candidate needs an out-of-sample Sharpe close to 1.4 to clear 0.95, while the
expected best of 113 null trials is about 0.76. Six configurations, declared
before the first run, is the limit and it is not a target. Fewer, better
motivated trials beat more.

## What you must beat

Two benchmarks, and you report both:

* `vol_target_hold` **on your own universe** — does your idea add anything to
  holding the same assets passively at the same risk?
* `vol_target_hold` **on (btc, eth, gold, silver)**, OOS Sharpe 1.131, on the
  window you share with it — is your idea better than what the desk would
  otherwise run? This is the one that decides deployment.

A wide passive book may itself beat the four-asset one purely through
diversification. That is a legitimate and valuable result — it is not alpha,
it is a better posture — and whoever measures it should say so plainly rather
than dressing it up.

## Size

The owner starts with **$250** and scales. Kalshi contracts are whole units
and fractional trading is off. One contract costs between $0.21 (ADA) and
$11.59 (LINK) of notional, so a $250 book at a 12% vol target holds roughly
$100 of notional and a sixteen-name equal-risk book wants about $6 per name:
zero or one contract each. Run your headline configuration **twice** — at
fractional sizing and with `BacktestConfig(bankroll_usd=250)` — and report
both. A strategy that only works above $5,000 is still worth knowing about,
but say so.

## Report

As `CAMPAIGN.md` section 8, plus two extra rows: the survivorship test from
(2), and the $250 whole-contract run from the paragraph above. Under 900
words. Numbers exactly as printed. A family that fails is a useful result and
gets written up the same way — round 1's honest failures are why this round
knows where to look.
