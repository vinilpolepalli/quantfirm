# Kalshi 15M metals — backtest results & verdict (2026-09-10)

Protocol and honesty constraints: `docs/KALSHI.md` §4. Data: full settled
history of KXGOLD15M / KXSILVER15M / KXCOPPER15M (6,655 markets, series
inception → Sep 10) with per-market 1-min contract candles; underlying =
GC=F/SI=F/HG=F 1-min bars (Aug 13 → Sep 10 coverage), re-anchored to the
settlement print at every window open. $500 starting bankroll everywhere.

## Headline verdict

**The taker (divergence-repricing) strategy has NO demonstrable edge and
loses at realistic latency.** A 5-agent adversarial review (findings +
reproductions in `research/kalshi_review.md`) proved the original backtest's
"conservative" fill was a zero-latency artifact, and the corrected,
latency-aware backtest is negative on every split. The desk holds at PAPER
with $0 real capital. The one structurally sound direction — a passive
**maker** leg, where latency works *for* you — is untested by any backtest
(candles can't model queue position) and is being measured live in shadow.

### The fill-model correction (why the first pass looked profitable)

Kalshi 1-min candle side-price *opens* are carry-forward snapshots of the
prior close (ask_open(T+60) = ask_close(T) in 97–99% of minute pairs), so the
"fill only if the next candle's open is inside our limit" gate rejected ~1%
of intents and always filled at the very quote whose displacement triggered
the trade — a **zero-latency, always-filled** model, not a conservative one.
The timed trades tape shows 78% of fill-minutes reprice through the limit
with a median deadline of ~1.4–4.1s; a REST poll loop cannot win that race.

`fill_mode` now exposes both bounds (`--fill-mode touch|lag`):

| mode | what it models | FULL | TEST |
|---|---|---|---|
| `touch` | zero-latency ceiling (fills at the stale quote) | +103.7% | −7.5% |
| `touch`, **uncontested subset** | the certain fills a slow taker actually gets | **−$631** (hit .42) | **−$220** (hit .36) |
| `lag` | realistic floor: fills only levels that survived the fill minute, at that minute's close, capped at traded volume | **−14.6%** | **−15.7%** |

The uncontested subset is the tell: the order fills with certainty *exactly
when the signal was wrong* (winner's curse), and only probabilistically when
it was right. Every honest number is negative.

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

## Statistical verdict (FIRM.md §2 applied)

* **DSR = 0.27** (0.70 under maximal trial-dedup) vs the firm's 0.95 gate;
  the +120.9% train Sharpe (5.65) is *below* the expected max of pure noise
  for N=192 trials — consistent with zero edge.
* **PBO = 0.40** (gate ≤0.10); **walk-forward efficiency = −0.31** (gate
  ≥0.5); OOS positive in **1 of 3** folds (gate ≥5/8); test max DD 58.6%
  (gate 30%). **Score = 0.**
* The registered defaults lose ~50% on *both* splits; the theory-motivated
  gates were derived from the August train autopsy (in-sample) and only
  reduce losses — they carry zero evidence of positive edge. The weekly
  walk-forward's OOS weeks had all been inspected before it was written, so
  it is a robustness illustration, not clean OOS evidence.
* Effective coverage is ~4 weeks (underlying 1-min bars start Aug 13);
  copper was "tested" with zero training history. Per-metal P&L sign-flips
  between splits are noise, not signal.

## Why the maker direction is still open

* The taker refutation is specific: a REST-latency taker cannot win the
  sub-second race, and at realistic latency it loses. This says nothing
  about **resting** entries, where the race *inverts* — a passive quote is
  filled *by* the impatient taker, so latency is an asset, not a liability.
* Maker economics (zero fee on metals; Whelan's 313k-obs Kalshi study:
  makers in ≥50¢ favorites +2.6% while takers −31%) are invisible to a
  candle backtest — queue position and adverse selection need the live tape.
  This is why the maker leg is a *live* experiment, not a backtested claim.

## The live shadow experiments now running (prod books, $0 at risk)

Separate $500 books, per-book sizing (quarter-Kelly on all-in cost, 5% cap,
persisted daily −10% stop), per-adapter dedupe so the books don't censor
each other.

1. **Taker leg** — the registered config (θ=0.07, hl30, τ∈[300,600],
   p∈[0.35,0.92]) on the ~1 bp Swissquote signal, **two-phase fill**: the
   decision quote and the fill quote are separate REST fetches, and the
   order fills only if the limit is still marketable on the *second* fetch —
   so the live record MEASURES the race-loss rate instead of assuming it
   away. Expectation given the backtest: near-flat-to-negative; the value is
   the measured race-loss and uncontested-fill P&L, not profit.
2. **Maker leg** — passive quotes on the favorite side at fair−4¢
   (join/improve the touch, never cross), conservative tape-based fills
   (book must trade THROUGH the level, or sweep 3× size at it), quote-fade
   on 2¢ adverse fair moves, no quotes in the last 3 minutes, zero fees.
   This is the direction with a real chance; it needs ≥2 weeks of live fills
   before any claim.

Results accumulate in `state/kalshi_paper_state.json` /
`state/kalshi_paper_trades.csv`; the session log below is appended as
sessions complete.

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
