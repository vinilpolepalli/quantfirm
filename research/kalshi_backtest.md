# Kalshi 15M metals — backtest results & verdict (2026-09-10)

Protocol and honesty constraints: `docs/KALSHI.md` §4. Data: full settled
history of KXGOLD15M / KXSILVER15M / KXCOPPER15M (6,655 markets, series
inception → Sep 10) with per-market 1-min contract candles; underlying =
GC=F/SI=F/HG=F 1-min bars (Aug 13 → Sep 10 coverage), re-anchored to the
settlement print at every window open. $500 starting bankroll everywhere.

## Headline verdict

**The taker (divergence-repricing) strategy is NOT validated by this
backtest.** Every honest evaluation of the selection process was negative
or unstable; the desk therefore holds at PAPER with $0 real capital, and
the live shadow experiments below are the decisive next evidence.

## What was run (in order, all pre-registered before looking at test data)

1. **Calibration measurement** (gold, ~3,880 windows/horizon):
   market Brier 0.1915 / model Brier 0.1945 at τ=10min (market ≈ model
   skill on average). Longshots overpriced +2.3¢ at τ=10min, ≈calibrated at
   τ=5min — mild FLB in the documented direction, fee-scale only.
2. **Train-split autopsy** (Aug 13–27, gold, default gates): entries in the
   window's first ~3 minutes lost −$341/41 trades; longshot buys (≤0.30)
   lost −$345/107; the τ 5–9 min mid-window band was +$240 even in this
   losing period. Model q of entered side 0.471 vs realized 0.368 —
   winner's-curse on selected trades. These findings (plus external FLB
   evidence) motivated the restrictive gates.
3. **192-config sweep on train** (θ × vol-halflife × τ-window × price
   bounds; split fixed at 2026-08-27T00:00Z before sweeping): 94/192
   positive; marginal means favored θ=0.07, halflife 60, τ∈[300,600],
   price≥0.30 — consistent with the autopsy on every dimension.
4. **Single test look** (chosen config θ=0.07/hl30/τ[120,600]/p[0.35,0.92],
   picked for all-weeks-positive train consistency, +120.9% train):
   **−11.4% test** (215 trades, hit 0.553); −23.9% under +1¢ slippage
   stress. Per-metal P&L flips sign across splits (silver +991→−341, gold
   −386→+376): the signal is regime-unstable at this granularity.
5. **Weekly walk-forward** (the primary evaluation; 384 configs incl. a
   flow/stale regime gate, fixed selection rule — n≥25, positive in ≥½ of
   selection weeks, max P&L — trade the next week out-of-fold):

   | fold | chosen (on prior weeks) | sel P&L | OOS P&L | n | hit |
   |---|---|---|---|---|---|
   | W35 | θ.05 hl60 τ[300,600] p[.15,.85] off | +$537 | **−$130** | 137 | .41 |
   | W36 | θ.07 hl30 τ[120,600] p[.35,.92] off | +$1,406 | **−$216** | 83 | .48 |
   | W37 | θ.07 hl30 τ[300,600] p[.35,.92] off | +$1,659 | **+$95** | 44 | .59 |

   **OOS total: −$250.44.** The regime gates (flow_only/stale_only) were
   never selected and their tagged trades showed no OOS edge either
   (mixed-origin divergences drove the losses).

## Why this does NOT close the question

* The backtest's signal is a ~10-min-delayed 1-min futures bar; the live
  engine's signal is Swissquote at ~1s / ~1bp from the settlement index.
  The backtest refutes the SLOW version of the signal under optimistic
  fills; it cannot measure the fast version. (It also cannot see sub-minute
  sniping against us — its optimism and its pessimism are both unmeasured.)
* Maker economics (zero fee; Whelan: makers in favorites +2.6% while takers
  −31%) are invisible to a candle backtest entirely.

## The two live shadow experiments now running (prod books, $0 at risk)

1. **Taker leg** — the restrictive family (θ=0.07, hl30, τ∈[300,600],
   p∈[0.35,0.92]) driven by the real-time feed, fills only when prod
   top-of-book size covers the order. Explicitly labeled: unvalidated by
   backtest; live shadow IS the validation attempt.
2. **Maker leg** — passive quotes on the favorite side at fair−4¢
   (join/improve the touch, never cross), conservative tape-based fills
   (book must trade THROUGH the level, or sweep 3× size at it), quote-fade
   on 2¢ adverse fair moves, no quotes in the last 3 minutes, zero fees.

Both legs share the $500-per-book sizing rules (quarter-Kelly, 5% cap,
daily −10% stop). Results accumulate in `state/kalshi_paper_state.json` /
`state/kalshi_paper_trades.csv`; first session's log below is appended by
the desk as sessions complete.

## Promotion bar (unchanged)

≥2 weeks of live shadow with P&L consistent with a positive edge net of
fees, demo-env plumbing green, before any CANARY discussion. A profitable
week of shadow is NOT sufficient — see the walk-forward table for what
2-week win streaks are worth here.

## Session log

* 2026-09-10 16:35–16:45Z (shakeout, loose defaults): gold NO 32@0.77 →
  settled no, **+$6.96** (model right); silver YES 58@0.19 (longshot buy,
  now gated out) → settled no, **−$11.65**. Net −$4.69. Settlement
  accounting verified end-to-end.
