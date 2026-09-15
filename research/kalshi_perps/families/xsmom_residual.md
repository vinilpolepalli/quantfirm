# xsmom_residual — market-residual cross-sectional momentum, as a sleeve

Referee-run family, 2026-09-15, round 2. Code
`quantfirm/perps/families/xsmom_residual.py`. Universe: the 20 tradable perps
(crypto legs only; gold and silver are not part of the market being
residualised). DEV window only; the holdout is sealed and was not opened.

**Verdict in one line: the first candidate in two rounds that improves the
book out of sample, and it still fails the deflated-Sharpe gate — on window
length, not on economics.**

## 1. Why this is not round 1's cross-sectional family

Round 1's `xsec_momentum` scored 0.154 on six assets and round 2's own screens
found nothing in a raw cross-sectional rank on twenty names at any formation
from 30 to 365 days. Both tested the RAW sort, and on a universe whose first
principal component is about two thirds of the variance, a raw return sort is
a beta sort: it goes long the high-beta alts after the market rises. That is
the long book again, which is why round 1's version correlated 0.745 with it.

Two measurements say the breadth appears only once the market is removed:

* raw daily correlation among the crypto names averages 0.594, and a long book
  carries about two independent bets however many names it holds
  (`effective_bets.py`: 2.03 on four assets, 1.98 on sixteen);
* after removing the equal-weight market, an independent analyst measured
  residual correlation averaging −0.081, an eigenvalue participation ratio of
  9.49 of 12, and per-name idiosyncratic dispersion of about 45% a year.

So a market-neutral book on twelve names has roughly nine bets where a long
book on the same names has two.

The horizon was not chosen by search. Borri, Liu, Tsyvinski & Wu (2026,
arXiv:2510.14435; 16,468 coins, 2014–2025) find the effect at a **two-week**
formation with a one-week hold: +2.6%/week full sample (t 3.89), +2.1%/week
post-2020 (t 3.70), with 12-week and 24-week momentum insignificant. Round 2's
earlier screens tested 30, 60, 90, 180 and 365 days — exactly the horizons that
paper reports dead — so finding nothing there was consistent with the
literature rather than evidence against it.

## 2. Registered grid, verbatim, written before the first run

```python
TRIALS = {"xsmom_residual": {"params": {"target_vol": 0.12, "lookback": 14,
                                        "beta_window": 180, "tranches": 7},
                             "grid": {"k": [2, 3]}}}
```

Two grid points, not six. The registry already carried 79 distinct
configurations and every extra point raises the deflated-Sharpe bar for every
future idea. The lookback was not swept.

Mechanism: beta to the equal-weight market of the available names, 180-day
rolling, used for the weight decided at that close and executed at the next
open; signal is the sum of the last 14 daily residuals; rank, long the top `k`,
short the bottom `k`, inverse-volatility within each leg, dollar-neutral; seven
overlapping weekly tranches so the answer does not depend on which weekday the
backtest starts; the sleeve is scaled to its own 12% volatility target on a
trailing estimate. Availability is the native-bar mask, so no name is held
before it lists or inside a delisting gap and no return spans a gap.

## 3. Walk-forward, 2021-10 → 2025-06, 4 folds, 250-day warmup

`k=3` was selected in every fold.

| fold | window | sleeve OOS | core OOS | 30% blend |
|---|---|---:|---:|---:|
| 0 | 2022-06-08 → 2023-03-13 | 1.252 | 0.092 | 0.716 |
| 1 | 2023-03-14 → 2023-12-18 | 1.763 | 1.413 | 2.019 |
| 2 | 2023-12-19 → 2024-09-23 | 0.669 | 1.872 | 2.348 |
| 3 | 2024-09-24 → 2025-06-30 | 0.401 | 1.485 | 1.615 |

oos_sharpe_concat **1.028**, oos_cagr 18.59%, oos_max_drawdown −14.51%, folds
positive 4/4, WFE 1.099, zero liquidations, turnover 12.8–18.9 a year.

Read the first two columns against each other. The sleeve carried the book in
fold 0, when the long book earned nothing; the long book carried it in folds 2
and 3, when the sleeve faded. That is not decay, it is the anticorrelation the
whole idea rests on, and it is why the blend beats both in three folds of four.

## 4. The blend is the object, not the sleeve

Daily correlation of the sleeve's out-of-sample excess returns to the core
book's: **−0.156**. For a sleeve that uncorrelated, the standalone Sharpe is
nearly irrelevant and the question is what it does to the book.

| blend | Sharpe | ann return | ann vol | max DD |
|---|---:|---:|---:|---:|
| core only (4-asset long book) | 1.255 | 15.37% | 12.25% | −10.12% |
| 20% sleeve | 1.562 | 15.27% | 9.78% | −8.98% |
| **30% sleeve** | **1.694** | 15.22% | 8.99% | −8.64% |
| 40% sleeve | 1.761 | 15.17% | 8.61% | −8.43% |
| 50% sleeve | 1.734 | 15.12% | 8.72% | −8.39% |
| 60% sleeve | 1.624 | 15.06% | 9.27% | −8.89% |
| sleeve only | 1.028 | 14.86% | 14.46% | −16.15% |

The same return at three quarters of the volatility and a smaller drawdown.
Every weight from 20% to 60% beats the core, so the result does not balance on
the weight; 30% is quoted throughout as the conservative end of that range.

Paired circular block bootstrap, 3000 resamples, on the out-of-sample streams:

| blend | Sharpe difference | 90% band | P(blend > core) |
|---|---:|---|---:|
| 30% sleeve | +0.439 | [−0.004, +0.896] | **0.947** |
| 40% sleeve | +0.506 | [−0.138, +1.150] | 0.898 |

## 5. Robustness

**Timing null** (60 block-shuffled resamples of the position timing): real
0.742, null mean −0.368, null p95 0.651, **percentile of real 0.983**. The
returns come from when the signal holds its positions, not from the exposure
it happens to carry. This is the strongest timing-null result of either round;
round 1's best was 0.925 and most families sat between 0.4 and 0.6.

**Cost and funding stress**, walk-forward out of sample, 30% blend:

| scenario | sleeve | core | blend | blend return | blend DD |
|---|---:|---:|---:|---:|---:|
| taker tier 0 / Kalshi funding | 1.028 | 1.255 | 1.694 | 15.22% | −8.64% |
| **1.5× fees / Binance proxy funding** | 0.891 | 1.154 | **1.532** | 13.75% | −8.77% |
| taker tier 0 / proxy funding | 0.967 | 1.169 | 1.583 | 14.22% | −8.62% |
| maker tier 0 / Kalshi funding | 1.156 | 1.273 | 1.772 | 15.93% | −8.41% |

The firm's stress gate is a positive total return under 1.5× fees and proxy
funding; the blend clears it with a higher Sharpe advantage than in the base
case, because the core degrades faster than the sleeve does.

**Whole contracts at the owner's size.** The sleeve holds 12.7 legs on average
at about 0.0497 of equity each, which is $12.42 of notional per leg at $250,
against contracts costing $0.21 (ADA) to $11.57 (LINK). So it is
implementable, but at $250 quantisation dominates: the blend scores 1.623 at
$250 against 1.427 to 1.446 at $1,000, $2,500 and $10,000. That spread is
rounding luck in both directions, not an economic effect, and the trustworthy
number is the large-bankroll one.

## 6. What it fails, and why

**Deflated Sharpe: 0.695 against a bar of 0.95.** At the registry's 82 unique
configurations, a 1,119-day out-of-sample stream needs an annual Sharpe of
**2.33** to clear 0.95. The blend measures 1.694. This is a window-length
failure, not an economic one: the sleeve cannot exist before 2021-10 because
most of the names had not listed, so it has 1,119 out-of-sample days against
the benchmark's 2,767 and cannot be given more without waiting.

It also fails `beats_benchmark_oos` as the gauntlet currently writes that gate,
because the gate compares a candidate's *standalone* Sharpe (1.028) to the
benchmark's (1.255). That comparison is correct for an overlay 0.9-correlated
with the long book, which is what every round-1 candidate was, and wrong for a
sleeve at −0.156: a 1.03-Sharpe sleeve that takes the book from 1.255 to 1.694
and cuts its drawdown is more valuable than a 1.10-Sharpe overlay that is
0.996-correlated with the thing it is meant to improve. The gauntlet should
gain a portfolio-level gate; that is a protocol change and is recorded as one,
not quietly assumed here.

## 7. Honest reservations

* **One regime.** Three years, four folds, and 2022–25 is a single alt bear
  market followed by a recovery. The effect is well published and therefore
  likely crowded; the prior should be that most of it is already gone.
* **Turnover 13 to 19 a year** on names whose round trip is 29 to 43 bps. Costs
  are booked in every number above, but a spread widening hurts this more than
  it hurts the long book, and the venue is three months old.
* **Survivorship.** The twenty names are the set Kalshi lists today. For a
  dollar-neutral book the bias cuts both ways — the long leg is missing the
  coins that died, the short leg is missing the chance to have shorted them —
  but it is not zero and it is not quantified here.
* **The blend weight is a choice.** 20% to 60% all beat the core, which is the
  robustness that matters, but nothing in the data picks 30% over 40%.

## 8. Recommendation

Not promotable: it fails the deflated-Sharpe gate and cannot pass it on this
window. It is the first candidate worth **paper-trading beside the incumbent**,
because it improves the book on every out-of-sample measure the desk has and
its edge comes from timing rather than exposure. The right next step is the
promotion ladder in `docs/KALSHI_PERPS.md` §7, at a size where whole contracts
do not dominate, with a pre-committed 30% weight and a review when the
out-of-sample window reaches the length the deflated Sharpe needs.
