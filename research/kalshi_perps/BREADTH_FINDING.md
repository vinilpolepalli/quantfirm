# Breadth is an illusion on this venue

Referee measurement, 2026-09-15, after extending the desk to all 23 listed
Kalshi perps. Dev window only; the holdout is sealed. Daily bars on the
Coinbase and Yahoo proxies, availability judged on native bars so a delisted
or not-yet-listed name contributes nothing.

> **Corrected twice, same day, by adversarial verification.** The first
> version of this note put the wide passive book at Sharpe 0.49 and called the
> gap economic. Two separate defects were behind that number, both found by
> verifier agents pointed at the work with instructions to break it.
>
> 1. The runs called `vol_target` with its default 5% weight step, the *narrow*
>    sizing path. Twenty equal-risk weights are about 0.007 of equity each, so
>    the step rounded almost every alt to zero.
> 2. Even with the wide sizing path, `rebalance_band` was fixed at 0.03 while
>    the wide step is 0.05×4/n. For any universe past six names one step is
>    smaller than the band, so no single-step move ever traded: the twenty-name
>    book **held 2.51 names while fifteen quoted.**
>
> Both are fixed in the engine, the second with a band that scales with the
> step, and the output now carries `avg_n_held` beside `avg_n_available` so the
> failure is visible in every row. §3 below is the third and final version of
> that table: both books now hold their names and both reach their risk target.
> The verdict did not change. The magnitude did, twice, and saying so is the
> point of keeping the note.

## 1. Sixteen names carry no more bets than four

Reproduce with `python research/kalshi_perps/effective_bets.py` (dev window
only, availability judged on native bars). Sixteen of the twenty tradable
perps have at least 250 dev-window returns; bnb and hype list after the
holdout opens and have none at all, and vvv and wld have under 250.

| universe | eigenvalue participation ratio | squared diversification ratio |
|---|---:|---:|
| the four researched assets | 2.44 | **2.03** |
| the 14 crypto names with dev history | 2.45 | 1.61 |
| all 16 names with dev history | 3.07 | **1.98** |

Two standard definitions, because they answer different questions. The
participation ratio of the correlation matrix's normalised eigenvalues counts
independent directions in the data. The squared diversification ratio,
1/(u'Cu) for an equal-weight book, is the one that maps to a long-only book's
Sharpe — and by that measure **sixteen names carry slightly fewer effective
bets than four**, 1.98 against 2.03. Crypto alone is worse still at 1.61.

Mean pairwise correlation among the crypto names is 0.594, median 0.608. An
independent analyst working the same question from scratch got 2.02, 1.60 and
a mean correlation of 0.597, and supplied the mechanism: equal-risk weighting
collapses the metals' share of book variance from 48.7% to 6.0%, and that loss
cancels the entire gain from dropping intra-crypto correlation from 0.83 to
0.59. Gold and silver are the only uncorrelated bloc this venue offers —
crypto against gold correlates +0.044, against silver +0.098 — and spreading
the book over a dozen coins dilutes them.

## 2. Ten of sixteen names lost money

Annualised over 2021-10 → 2025-07, each on its own available history:

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

Gold and XRP are the only Sharpes above 0.43. Two caveats a reader should
carry into §3. XRP's +101.6% is measured on 719 days only, because it was off
Coinbase from 2021-01 to 2023-07, so it is the 2023–25 rally without the
preceding collapse. And this table is the set Kalshi lists **today**:
survivorship cuts both ways here, hiding the alts that died outright from the
long side as well as the short side, so the real 2021–25 alt cross-section was
worse than what is shown.

## 3. Correctly sized and actually held, the wide book is worse

`vol_target_hold` at a 12% target, tier-0 taker costs with each asset's own
measured half-spread, weekly check, wide universes sized with `BREADTH_SIZING`
and a band that scales with the step. Every figure is what `backtest.run`
printed.

| window | universe | Sharpe | CAGR | max DD | excess vol | turnover | names held | quoting |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2018-01 → 2025-07 | 4 researched | **0.940** | 15.45% | −21.15% | 12.68% | 1.68 | 4.00 | 4.00 |
| | 14 breadth | 0.812 | 13.38% | −21.50% | 12.42% | 1.34 | 10.38 | 10.70 |
| | 20 tradable | 0.824 | 13.43% | −21.85% | 12.26% | 1.43 | 11.08 | 11.44 |
| 2021-10 → 2025-07 | 4 researched | **1.161** | 18.04% | −15.55% | 12.12% | 1.84 | 4.00 | 4.00 |
| | 14 breadth | 0.792 | 12.52% | −16.13% | 11.65% | 0.93 | 13.28 | 13.53 |
| | 20 tradable | 0.770 | 12.02% | −15.42% | 11.37% | 1.11 | 14.66 | 15.00 |

This is an apples-to-apples comparison at last. Every book realises between
11.4% and 12.7% of volatility against its 12% target, and the wide books hold
essentially every name that quotes. The wide book earns **12.0% a year where
the narrow book earns 18.0%, at the same risk and the same drawdown.**

Paired circular block bootstrap of the Sharpe difference, 2000 resamples, on
the backtester's own excess-return series:

| window | comparison | difference | 90% band | P(wide > narrow) | corr |
|---|---|---:|---|---:|---:|
| 2018-01 → | 20 tradable vs 4 | −0.116 | [−0.491, +0.247] | 0.287 | 0.818 |
| | 14 breadth vs 4 | −0.128 | [−0.504, +0.222] | 0.263 | 0.824 |
| 2021-10 → | 20 tradable vs 4 | −0.391 | [−0.972, +0.233] | 0.142 | 0.755 |
| | 14 breadth vs 4 | −0.369 | [−0.943, +0.234] | 0.155 | 0.765 |

The wide book is behind on both windows and in both universes, with P(wide
better) between 0.14 and 0.29. The bands straddle zero, so this is not a
significant *difference* at 90%; what it is not, on any reading, is an
improvement. Four years of daily data cannot separate two books correlated
0.76 to 0.82, which is itself the point: they are the same bet.

The mechanism is the plain one. Equal-risk weighting spreads the book evenly
over names whose returns are in §2, so it dilutes the two that worked with a
dozen that did not, and it collapses the metals' share of book risk — an
independent analyst measured that share falling from 48.7% to 6.0%, which
cancels the entire gain from dropping intra-crypto correlation from 0.83 to
0.59. They add the finding that settles it: in their vol-matched replica the
wide book's whole apparent advantage is a *rebalancing return*, a
daily-rebalanced equal-weight alt basket returning +26.6% while nine of eleven
alts lost money and the average buy-and-hold was −12.7%. That is precisely the
quantity survivorship manufactures, and substituting one dead-alt path for one
of the eleven drops their replica below the narrow benchmark.

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
