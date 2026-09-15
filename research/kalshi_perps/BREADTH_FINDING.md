# Breadth is an illusion on this venue

Referee measurement, 2026-09-15, after extending the desk to all 23 listed
Kalshi perps. Window 2021-10-01 → 2025-07-01 (dev only; the holdout is
sealed), daily log returns on the Coinbase and Yahoo proxies, availability
judged on native bars so a delisted or not-yet-listed name contributes
nothing.

Round 1's diagnosis was that four assets at 0.9 correlation are two bets, not
four, and that nothing cross-sectional was testable. That diagnosis was half
right. The universe is now twenty tradable perps, and the measurement says
the missing breadth was never there.

## 1. Twenty names buy 0.07 of an extra bet

| universe | effective independent bets |
|---|---:|
| the four researched assets (btc, eth, gold, silver) | 2.44 |
| all 18 crypto names with usable history | 2.51 |

Effective bets is the inverse Herfindahl of the correlation matrix's
normalised eigenvalues. Mean pairwise correlation among the crypto names is
0.589, median 0.592. Fourteen additional coins add seven hundredths of one
independent bet, because they are all the same trade.

## 2. The alts were a drag, not a diversifier

Annualised, 2021-10 → 2025-07, on each name's own available history:

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

Eleven of seventeen names lost money over the window. An equal-risk book
dilutes the two assets that worked, gold and BTC, with a dozen that did not.

## 3. So the passive wide book is worse, and by a lot

`vol_target_hold` at a 12% volatility target, tier-0 taker costs with each
asset's own measured half-spread, weekly check, 3% band:

| window | universe | Sharpe | CAGR | max DD | turnover |
|---|---|---:|---:|---:|---:|
| 2018-01 → 2025-07 | 4 researched | **0.94** | 15.5% | −21.2% | 1.68 |
| 2018-01 → 2025-07 | 14 breadth | 0.60 | 9.0% | −25.8% | 1.62 |
| 2018-01 → 2025-07 | 20 tradable | 0.49 | 7.7% | −25.8% | 1.52 |
| 2021-10 → 2025-07 | 4 researched | **1.16** | 18.0% | −15.6% | 1.84 |
| 2021-10 → 2025-07 | 14 breadth | 0.74 | 6.8% | −3.8% | 1.07 |
| 2021-10 → 2025-07 | 20 tradable | 0.76 | 5.8% | −2.5% | 0.80 |

Sharpe is scale-free, so this is not a sizing artefact: the wide book earns a
worse return per unit of risk. Note also how small the wide book becomes —
turnover 0.8 and a 2.5% drawdown — because the alts' 80–110% volatilities and
their 28–59% maintenance margin rates cap their weights hard. Most of the
wide book is collateral earning 3.25%.

## 4. What this kills, and what it leaves

**Killed by measurement, not by assertion:**

* Diversified beta. Twenty names are 2.5 bets. There is no diversification
  premium to collect here.
* Any long-only cross-sectional tilt. Tilting toward alts tilts toward assets
  that lost 20–40% a year in this sample.
* The hypothesis this round was built on — that round 1 failed for want of
  breadth. It failed because the desk's benchmark is genuinely hard to beat,
  and breadth does not help.

**Left standing, and worth exactly one careful test:** a *long/short*
cross-sectional book. The dispersion is enormous, from +102% a year to −37%,
and the losers were persistently weak rather than randomly weak. Two things
make this specifically interesting on Kalshi rather than offshore:

* Kalshi's funding deadband zeroes almost every interval, so a short position
  costs nothing to carry and the collateral still earns 3.25%. Offshore, a
  short in a contango market receives funding but pays it in backwardation;
  here the carry is simply absent in both directions.
* Survivorship runs the *helpful* way for a short book. These twenty names are
  the ones Kalshi lists today; the alts that died are not in the sample. A
  short-biased backtest on survivors therefore understates what the short side
  would have earned, which is the opposite of the usual bias and makes a
  negative result trustworthy.

Against it: the window is one regime, the post-2021 alt bear market, and 3.7
years supports few honest folds. A long/short book fitted here is fitted to
that regime, and the referee should weight it accordingly.
