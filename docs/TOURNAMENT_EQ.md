# Equity tournament #1 — results and verdict (2026-07-31)

**Verdict: NO-GO on the firm's strict statistical gate — but with a
qualified, deployable fallback.** Unlike the crypto tournament (where every
candidate failed the holdout outright), the equity field *held up* out of
sample; what failed was the claim of *alpha* beyond benchmark beta at this
sample size.

## Format

5 designer agents (3 on the survivorship-free ETF track, 2 on the stock
track with a 0.70 Sharpe haircut), ~199 registered trials, shared eval
(4-fold walk-forward net OOS Sharpe, 5bps/side, dev 2016-06→2024-07), sealed
holdout 2024-08→2026-07 opened once by the judge, then two adversarial
attackers. All five dev claims reproduced exactly; all five modules passed
line-by-line and empirical causality audits.

## Holdout results (5bps, haircut applied where noted)

| strategy | dev OOS | holdout | holdout maxDD | CAGR | verdict |
|---|---|---|---|---|---|
| **allweather_trend** (ETF) | 0.90 | **1.34** | **−7.5%** | 12.0% | winner; fails DSR gate |
| xsec_refined (stock, ×0.70) | 1.35→0.94 | 1.47→1.03 | **−39%** | 58% | DQ: capital preservation |
| regime_sector (ETF) | 0.61 | 0.98 | −11% | 12.1% | beats SPY by noise only |
| etf_adaptive (ETF) | 0.70 | 0.98 | −17% | 15.3% | beats SPY by noise only |
| hybrid_lowturn (stock, ×0.70) | 0.89→0.62 | 1.19→0.83 | −8.4% | 13.0% | fails vs SPY after haircut |
| *spy_hold* | 0.69 | 0.97 | −19% | 16.2% | benchmark |
| *faber_sma* | 0.50 | **1.00** | −11% | 12.5% | **recommended fallback** |
| *xsec_momentum (×0.70)* | 0.91→0.64 | 1.63→1.14 | −37% | 95% | vanity number: bias-inflated, B&H-level DD |

Holdout regime: bull (+37% SPY) with one sharp crash (−19%, spring 2025) —
one real stress test of every candidate's risk layer, which the winner and
faber_sma passed conspicuously (−7.5%/−11% vs −19%).

## Why NO-GO despite a winner that beat SPY out of sample

1. **Deflated Sharpe 0.18** (bar: 0.95). Two years of daily holdout cannot
   statistically separate a 1.34 from the expected maximum of ~199 noise
   trials. The dev-period DSR is 0.35–0.58 — same conclusion.
2. **Rebalance-phase luck** (attacker finding): shifting the 21-day
   rebalance anchor swings dev Sharpe 0.60–0.98 (median ~0.78). The
   headline sat at the lucky edge of its own phase distribution. Honest
   expectation: mid-0.7s Sharpe, maxDD to −18% at bad phases.
3. **It is a risk-reducer, not alpha**: full-period CAGR 7.6% vs SPY 13.4%
   at 0.61 average exposure; removing the trend gate collapses it to 0.19
   Sharpe — i.e. the entire edge is a (well-executed, well-known)
   Faber-style trend overlay on a diversified menu.

## Attacker findings fixed in code

- Run-lock: one rebalance plan per UTC day (duplicate session firings were
  able to double-plan).
- Kill-switch liquidation now defers lots bought with unsettled proceeds
  (good-faith-violation guard).
- Rebalance hysteresis band (15% of target position, $5 floor) — the $0.01
  SEC sell fee made the previous $2 threshold generate ~64 tiny drift
  orders/yr costing ~14bps/yr unmodeled.

## Known data caveat

The panel is split-adjusted but **dividend-unadjusted** (venue serves 'all'
adjustment for intraday only). TLT's ~3-4%/yr distributions are invisible,
distorting bond-sleeve momentum slightly and understating all absolute
returns. Direction of bias on the *comparison* is roughly neutral (both
strategy and benchmark understated) but the research desk should source
total-return series before any promotion decision.

## Standing decision

- `config/equity_live.json`: `enabled: false`, lifecycle
  `NO_GO_DSR_FALLBACK_AVAILABLE`.
- **WATCH seat: allweather_trend** (nightly-revalidated as data accrues).
- **Qualified fallback available: faber_sma (or allweather_trend) as an
  explicitly-labeled BETA-WITH-BRAKES book** — deployable if the human
  principal chooses capital-preservation-first exposure over cash, with
  documented expectations: ~SPY-like Sharpe, materially smaller drawdowns,
  *lower* expected return than buy-and-hold SPY, no alpha claim. The firm's
  gates distinguish "verified alpha" (nothing qualified) from "verified
  honest implementation of a defensible defensive strategy" (two
  candidates qualified).
- The pure-return maximizer at $250, per the evidence, is buying SPY (or
  nothing). The firm will not dress that up as quant alpha.

## Next-round backlog

- Total-return (dividend-adjusted) data source.
- Phase-averaged rebalancing (spread the rebalance across 4 weekly
  quarter-tranches — kills the phase-luck sensitivity by construction).
- Point-in-time universe reconstruction for an honest stock track.
- Longer holdout via earlier dev cutoff once total-return data exists.
