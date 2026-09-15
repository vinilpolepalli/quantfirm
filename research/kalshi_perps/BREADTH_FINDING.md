# Breadth is an illusion on this venue

Referee measurement, 2026-09-15, after extending the desk to all 23 listed
Kalshi perps. Dev window only; the holdout is sealed. Daily bars on the
Coinbase and Yahoo proxies, availability judged on native bars so a delisted
or not-yet-listed name contributes nothing.

> **Correction, same day.** The first version of this note reported the wide
> passive book at Sharpe 0.49 against the narrow book's 0.94 and called the
> gap economic. It was not: those runs called `vol_target` with its default
> 5% weight step, which is the *narrow* sizing path. Twenty equal-risk weights
> are about 0.007 of equity each, so the step rounded almost every alt to
> zero and measured a metals book wearing a wide book's name. `strategies.py`
> ships `BREADTH_SIZING` (pairwise covariance, 60-of-120 minimum, a step that
> scales with the universe) for exactly this, and every number below uses it.
> The conclusion survives the correction. The reason changed, and one claim —
> that the wide book is much *worse* — did not survive and is withdrawn.

## 1. Twenty names buy almost no extra bets

| universe | effective independent bets |
|---|---:|
| the four researched assets (btc, eth, gold, silver) | 2.44 |
| all 18 crypto names with usable history | 2.51 |

Effective bets here is the inverse Herfindahl of the correlation matrix's
normalised eigenvalues. Mean pairwise correlation among the crypto names is
0.589, median 0.592. Fourteen additional coins add seven hundredths of one
independent bet, because they are all the same trade.

An independent analyst working the same question used the other standard
definition, the squared diversification ratio 1/(u'Cu), which is the variant
that maps to a long-only book's Sharpe. It gives **2.02 for the four-asset
book and 2.02 for the fourteen-asset book** — a Sharpe multiplier of exactly
1.000 — and reports the mechanism precisely: equal-risk weighting collapses
the metals' share of book variance from 48.7% to 6.0%, and that loss cancels
the gain from dropping intra-crypto correlation from 0.83 to 0.59. A
crypto-only twelve-name book scores 1.60, worse than the four-asset book,
because dropping the metals destroys the only uncorrelated bloc the venue
offers: crypto against gold correlates +0.044, against silver +0.098.

## 2. The alts lost money

Annualised, 2021-10 → 2025-07, each name on its own available history:

| asset | ann. return | ann. vol | Sharpe | total |
|---|---:|---:|---:|---:|
| gold | +16.8% | 15.4% | 1.09 | +87.5% |
| xrp | +101.6% | 106.5% | 0.95 | +640.1% |
| silver | +12.4% | 29.2% | 0.43 | +59.3% |
| btc | +21.3% | 54.2% | 0.39 | +122.5% |
| sui | +41.9% | 107.9% | 0.39 | +143.3% |
| kshib | +10.4% | 110.7% | 0.09 | +47.9% |
| sol | −1.1% | 101.2% | −0.01 | −4.2% |
| bch | −1.9% | 84.6% | −0.02 | −7.0% |
| aave | −2.6% | 100.6% | −0.03 | −9.3% |
| doge | −8.0% | 93.0% | −0.09 | −25.9% |
| eth | −7.6% | 70.3% | −0.11 | −24.9% |
| link | −18.1% | 90.3% | −0.20 | −49.2% |
| ltc | −17.6% | 79.0% | −0.22 | −48.2% |
| near | −24.9% | 99.7% | −0.25 | −50.6% |
| zec | −29.4% | 92.8% | −0.32 | −66.7% |
| ada | −36.6% | 88.1% | −0.42 | −74.6% |
| vvv | −270.8% | 191.3% | −1.42 | −67.9% |

Eleven of seventeen lost money. Gold and XRP are the only Sharpes above 0.43.

## 3. Correctly sized, the wide book is indistinguishable — and earns a third as much

`vol_target_hold` at a 12% target, tier-0 taker costs with each asset's own
measured half-spread, weekly check, 3% band, wide universes sized with
`BREADTH_SIZING`. Every figure is what `backtest.run` printed.

| window | universe | Sharpe | CAGR | max DD | excess vol | turnover |
|---|---|---:|---:|---:|---:|---:|
| 2018-01 → 2025-07 | 4 researched | 0.940 | 15.45% | −21.15% | 12.68% | 1.68 |
| | 14 breadth | 0.746 | 7.79% | −9.04% | 5.94% | 0.57 |
| | 20 tradable | 0.835 | 9.59% | −12.40% | 7.41% | 0.55 |
| 2021-10 → 2025-07 | 4 researched | 1.161 | 18.04% | −15.55% | 12.12% | 1.84 |
| | 14 breadth | 1.124 | 7.53% | −2.39% | 3.63% | 0.23 |
| | 20 tradable | 1.188 | 6.70% | −2.42% | 2.76% | 0.16 |

Paired circular block bootstrap of the Sharpe difference, 2000 resamples, on
the backtester's own excess-return series:

| window | comparison | difference | 90% band | P(wide > narrow) | corr |
|---|---|---:|---|---:|---:|
| 2018-01 → | 20 tradable vs 4 | −0.106 | [−0.475, +0.254] | 0.300 | 0.834 |
| | 14 breadth vs 4 | −0.195 | [−0.483, +0.066] | 0.105 | 0.893 |
| 2021-10 → | 20 tradable vs 4 | +0.026 | [−0.377, +0.421] | 0.556 | 0.877 |
| | 14 breadth vs 4 | −0.038 | [−0.447, +0.365] | 0.449 | 0.880 |

**The wide book is not better and not much worse. It is the same bet, and it
cannot carry its risk budget.** Look at the excess volatility column: the wide
book realises 2.76% against a 12% target while the narrow one realises 12.12%.
That is not a bug in the sizing, it is the venue. Alt maintenance margin runs
from 26% (LTC) to 59% (WLD) against gold's 6.6% and BTC's 16.5%, and the
liquidation-distance rule caps each name by its own maintenance rate, so the
alts simply cannot be held in size. A book that cannot reach its risk target
earns 6.7% a year where the narrow book earns 18.0%, and most of its capital
sits in collateral at 3.25%.

The independent analyst adds the finding that decides it. In their
vol-matched replica the wide book's entire advantage is a *rebalancing
return*: a daily-rebalanced equal-weight alt basket returned +26.6% while
nine of eleven alts lost money and the average buy-and-hold was −12.7%. That
quantity is exactly what survivorship manufactures, and substituting a single
dead-alt path for one of the eleven drops the replica below the narrow
benchmark.

## 4. The cross-section carries nothing either

These screens are **exploratory**: raw return arithmetic, no strategy
registry, no trial registry, nothing promotable. They exist to decide where
registered trials are worth spending.

**Cross-sectional momentum, gross of all costs.** Rank every available name by
trailing return, hold the top quartile against the bottom, 2021-10 → 2025-07:

| formation | hold | rebalances | long-short, annualised | t | hit rate |
|---:|---:|---:|---:|---:|---:|
| 30d | 7d | 191 | +12.8% | 0.44 | 52% |
| 30d | 30d | 44 | −3.4% | −0.11 | 50% |
| 60d | 7d | 186 | −9.6% | −0.34 | 50% |
| 90d | 7d | 182 | +16.1% | 0.52 | 55% |
| 90d | 30d | 42 | +2.8% | 0.09 | 55% |
| 180d | 30d | 39 | −15.6% | −0.46 | 51% |
| 365d | 7d | 143 | −23.9% | −0.71 | 45% |
| 365d | 30d | 33 | −28.7% | −0.90 | 52% |

No t-statistic reaches 1, the sign flips with the formation horizon, hit rates
sit at the coin flip, and this is before the 29–43 bps round trip a quartile
book pays on the thin names.

**Time-series trend with a short side**, the one thing four assets could never
test because there was nothing worth being short of. Equal-risk by trailing
volatility, book scaled to 12%, gross of costs:

| universe | lookback | long/short | short only | long only |
|---|---:|---:|---:|---:|
| 20 tradable, 2021-10 → | 30d | 0.86 | 0.09 | −0.01 |
| | 60d | 0.50 | 0.28 | −0.07 |
| | 90d | −0.03 | −0.24 | 0.34 |
| | 180d | 0.21 | −0.01 | −0.33 |
| | 365d | 0.13 | −0.74 | 0.88 |
| 14 breadth, 2018-01 → | 30d | 0.68 | 0.32 | −0.03 |
| | 60d | 0.69 | 0.17 | 0.11 |
| | 90d | −0.04 | −0.70 | 0.55 |
| | 365d | 0.36 | −0.50 | 0.74 |

Read across, not down. A configuration scoring 0.86 at 30 days and −0.03 at
90 has told you about noise. The short side is negative at every long lookback
in both universes: the alts fell, but through violent rallies that whipsaw
anything systematic. All of these Sharpes are gross, against a benchmark whose
0.94 is net.

## 5. Verdict

The premise of this round was that round 1 failed for want of breadth. It is
false, in every way it can be tested:

* twenty names are two and a half bets, and by the definition that maps to a
  long-only book's Sharpe, exactly as many as four names;
* correctly sized, the wide passive book is statistically indistinguishable
  from the narrow one and earns a third as much, because the venue's own
  maintenance margin will not let the alts be held in size;
* what advantage the wide book appears to have is a rebalancing return that
  survivorship manufactures;
* the cross-section carries no momentum, and adding a short side does not
  change that.

No wide-universe family was registered. Ten configurations that a free screen
already shows to be empty would raise the deflated-Sharpe bar for every future
idea and buy nothing.

The practical consequence for the backlog: **more coins are not the missing
diversifier.** Gold and silver are the only genuinely uncorrelated bloc the
venue offers, and the thing worth waiting for is a perp in an asset class that
is not crypto.
