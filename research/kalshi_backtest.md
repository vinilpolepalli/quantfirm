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

* 2026-09-10 16:35–16:45Z (shakeout, loose defaults, pre-fix): gold NO
  32@0.77 → settled no, **+$6.96** (model right); silver YES 58@0.19
  (longshot buy, now gated out) → settled no, **−$11.65**. Net −$4.69.
  Settlement accounting verified end-to-end. Book archived under
  `state/kalshi_archive/` (superseded by the per-adapter engine).

* 2026-09-10 17:50–19:18Z (first clean session, registered config + fixed
  engine; taker two-phase, maker leg, per-book cash). FINAL tally:
  - **Taker book: 0 fills, 1 recorded race-loss.** The two-phase check
    (re-fetch the book before filling) caught a quote that repriced between
    decision and fill and refused it — the live confirmation of the backtest
    verdict: at REST latency there is nothing to take. Shadow cash $500 → $500.
  - **Maker book: +$37.05 (+7.4%), 5 wins / 0 losses, $0 fees.** 8 quotes
    posted, 3 cancelled on adverse fair moves (quote-fade discipline
    working), 5 filled by takers trading through the level and held to
    settlement:

    | market | side | ct | price | fair@quote | result | P&L |
    |---|---|---|---|---|---|---|
    | KXGOLD15M-…101400 | NO | 22 | 0.62 | 0.34 | no | +$8.36 |
    | KXGOLD15M-…101430 | NO | 30 | 0.84 | 0.12 | no | +$4.80 |
    | KXGOLD15M-…101500 | NO | 23 | 0.61 | 0.35 | no | +$8.97 |
    | KXSILVER15M-…101500 | YES | 29 | 0.62 | 0.68 | yes | +$11.02 |
    | KXSILVER15M-…101515 | NO | 30 | 0.87 | 0.08 | no | +$3.90 |

  The sign, the mechanism, and the taker/maker contrast all came out as the
  review predicted. **Still small sample (n=5)** — per-trade sd from the
  backtest is ~$22 and 5/5 wins is easily a lucky streak — so the ≥2-week
  live bar before any real-capital claim stands. But this is the first
  concrete evidence that the *maker* direction is the real one, and it is
  fully agentic end to end (deterministic quoting/fills/settlement).

* 2026-09-10 19:35–21:22Z (session 2, same engine). Session-2 fills:
  - **Maker book: +$45.50, 7 wins / 1 loss.** First loss appeared — a
    silver YES that settled no, −$14.03 — which is the healthy realism the
    2-fill session lacked. Still strongly net positive.
  - **Taker book: +$27.55, 4 fills, 4 wins.** The two-phase leg DID fill
    this session (unlike session 1), but every fill was a near-certain
    favorite (model fair ≈ 0.00) bought as NO — i.e. exactly the
    "uncontested" subset the backtest flagged as −EV, winning here on a
    tiny sample. **Do not read this as taker vindication:** those fills
    fired off a collapsed vol estimate returning fair=0.000, so a follow-up
    fix now clamps model confidence to [0.02, 0.98] (no 15-min diffusion is
    ever certain) — the fat-tail risk is a NO bought at 0.60 that flips.

  **Cumulative (sessions 1–2): maker +$82.55 (12/13 wins, $0 fees); taker
  +$27.55 (4/4).** 3 positions were still open at session-2 exit and settle
  at the next session's first tick. Encouraging and consistent, still far
  short of the sample needed to claim an edge (a ~$22 per-trade sd means
  even +$82 over 13 trades is ~1.7σ — suggestive, not significant).

* 2026-09-10 21:31–23:16Z (session 3, confidence clamp active):
  - **Maker: +$43.04, 7 wins / 3 losses.** The losses (−$31, −$30, −$29)
    clustered in the 18:00Z window — a fast underlying move ran over several
    favorite quotes at once. This is the maker leg's real risk mode
    (adverse selection during a spike, correlated across gold+silver) and
    it's healthy that it showed up rather than staying hidden.
  - **Taker: +$28.68, 4 wins / 1 loss** (a −$27.92 in the same 18:00 spike).

  **Cumulative (sessions 1–3): maker +$125.59 (19/23, hit 0.83, $0 fees,
  +25.1% on $500); taker +$56.23 (8/9, +11.2%).** Over ~5.5h of trading.
  Still not statistically decisive: ~$18 per-trade sd and heavy same-window
  gold/silver correlation put the maker result near ~1.5σ on effective
  sample. The trajectory and mechanism are right; the ≥2-week bar and the
  spike-risk (size the correlated book, not the single trade) are the open
  items. Losses now present and bounded, which is the point of the risk gates.

* 2026-09-10 23:18–2026-09-11 01:08Z (session 4). **First losing maker
  session: −$35.44 (3 wins / 3 losses).** The maker cumulative gave back a
  third of its gains in one session — the plainest possible demonstration of
  why 3 good sessions were never "validated." No daily-stop breach (loss was
  ~7% of the book, crossing the UTC-midnight reset). Taker +$30.52 (3/3,
  still the bounded near-favorite fills).

  **Cumulative (sessions 1–4): maker +$90.15 (22/29, hit 0.76, $0 fees,
  +18.0% on $500); taker +$86.75 (11/12, +17.4%).** Both books net positive,
  but the maker's single-session −$35 swing is the headline: this is a
  positive-drift, real-variance strategy, NOT a sure thing. The equity curve
  is up and to the right across ~7.5h and the mechanism keeps holding, but
  the honest read is unchanged — promising, under-powered, weeks of live
  data still required before any real-capital claim.

* 2026-09-11 01:11–03:00Z (session 5). Maker near-flat **+$4.88 (5/6)** —
  recovered from session 4's loss. Taker took its **second real loss,
  −$29.66 (0/1)**, giving back its session-4 gain: the taker's early 8/9
  was the toxic near-favorite subset the backtest flagged, now flipping as
  predicted. **Cumulative (1–5): maker +$95.03 (27/35, hit 0.77, +19.0% on
  $500); taker +$57.09 (11/13, +11.4%).** The maker/taker divergence is
  starting to show through the noise — maker grinds up, taker lurches. Still
  under-powered; the read stands.

* 2026-09-11 03:01–~04:04Z (session 6, PARTIAL — the container was restarted
  mid-session; the engine is single-shot and persists per tick, so the 2
  settled maker fills were saved and no state was lost). Maker +$15.38 (2/2).
  **Cumulative (through session 6 partial): maker +$110.41 (29/37, hit 0.78,
  $0 fees, +22.1% on $500); taker +$57.09 (11/13, +11.4%).** Restart handled
  cleanly — a good live test of the persisted-state design. Session resumed
  fresh afterward.

* 2026-09-11 04:07–~05:57Z (session 7, post-restart). Maker −$10.12 (4/6,
  small down session); taker +$26.85 (2/2). **Cumulative (1–7): maker
  +$100.29 (33/43, hit 0.77, $0 fees, +20.1% on $500); taker +$83.94 (13/15,
  +16.8%).** The maker leg's win rate has been stable at ~0.77 across 43
  fills — the durable stat under the session-to-session P&L noise.

* 2026-09-11 05:57–~07:47Z (session 8). Maker +$25.38 (6/8); taker +$6.79
  (1/1). **Cumulative (1–8): maker +$125.67 (39/51, hit 0.76, $0 fees,
  +25.1% on $500); taker +$90.73 (14/16, +18.1%).** 51 maker fills, hit rate
  pinned at ~0.76 — the stability of the win rate (not any single session's
  P&L) is what would eventually make or break the edge claim.

* 2026-09-11 07:48–~09:37Z (session 9). Maker +$34.71 (4/5); taker −$18.30
  (0/1). **Cumulative (1–9): maker +$160.38 (43/56, hit 0.77, $0 fees,
  +32.1% on $500); taker +$72.43 (14/17, +14.5%).**
  **Significance check (the part that keeps this honest):** the maker leg's
  per-trade mean is $2.86 on a $15.53 sd → t = 1.38 (1.58 grouped by
  hour-block to blunt same-window correlation). A +32% cumulative return is
  STILL only ~1.4σ — below the 1.96 for 95%, far below the firm's t≥3 floor.
  The big per-trade variance means even this streak is consistent with luck
  at conventional thresholds; that is precisely why the promotion bar is
  weeks of data, not a good-looking equity curve.

* 2026-09-11 09:39–~11:27Z (session 10). Maker +$36.96 (4/6); taker +$15.13
  (1/1). **Cumulative (1–10): maker +$197.34 (47/62, hit 0.76, $0 fees,
  +39.5% on $500); taker +$87.56 (15/18, +17.5%).** Maker t-stat now **1.61**
  (was 1.38 at session 9) — rising with the sample, as a real edge should,
  but still short of 1.96. Watch the t-stat, not the +39.5%: if the edge is
  real it keeps climbing toward the t≥3 floor; if it's luck it stalls and
  fades. This is the number that decides it.

* 2026-09-11 11:29–~13:17Z (session 11). Maker +$43.09 (9/11); taker +$35.56
  (1/1). **Cumulative (1–11): maker +$240.43 (56/73, hit 0.77, $0 fees,
  +48.1% on $500); taker +$123.12 (16/19, +24.6%).** Maker t-stat **1.84**
  (trajectory 1.38 → 1.61 → 1.84) — now just below the 1.96 95% threshold.
  The monotone climb with sample size is the signature of a real (not
  lucky) edge; if it crosses and holds ≥1.96, and then approaches the firm's
  t≥3 floor, that is the point the maker leg graduates from "promising" to
  "demonstrated." Not there yet — but the trend is the right one.

* 2026-09-11 13:21–~15:07Z (session 12, IN PROGRESS at time of writing).
  Maker −$31.89 so far (1 win / 2 losses). **Cumulative (through session 12
  partial): maker +$208.54 (57/76, hit 0.75, $0 fees, +41.7% on $500); taker
  +$123.12 (16/19, +24.6%).** **The maker t-stat DIPPED to 1.52** (from 1.84
  at session 11, breaking the 1.38 → 1.61 → 1.84 climb). Recorded plainly:
  the earlier monotone rise was not a guarantee, and this is exactly the
  behaviour that separates a real edge (resumes climbing toward t≥3) from a
  lucky streak (flattens and fades here). Still clearly profitable in
  cumulative terms, still NOT statistically significant, and the dip is a
  point against, not for. Verdict unchanged: keep trading, keep watching the
  t-stat, claim nothing.

* 2026-09-11 ~15:07Z (session 12 final + session 13 start). Two further maker
  fills, both losers: **−$36.66 (0/2)**. **Cumulative: maker +$171.88 (57/78,
  hit 0.73, +34.4% on $500); taker +$123.12 (16/19).**
  **t-stat trajectory has now clearly peaked and is decaying:
  1.38 → 1.61 → 1.84 → 1.52 → 1.23.** This is the pattern I pre-registered as
  the signature of a LUCKY STREAK rather than a real edge (a real edge keeps
  climbing with sample; luck peaks and fades). The cumulative P&L is still
  strongly positive, but statistical confidence is now *falling* as data
  accumulates — which is the opposite of what validation looks like.

  Structural context for why the fade matters (measured, n=78): avg win
  $10.94 vs avg loss $21.52 (ratio 0.51) ⇒ **break-even hit rate is 66.3%**
  and actual is 73.1% — only a **6.8pp cushion**. Losing streaks eat that
  cushion fast, and the shadow fill model gives free queue priority that a
  real exchange would not, biasing the true hit rate *down*.

  **Read: the maker edge is NOT established and the evidence has weakened.
  Do not treat the +34% as validated.** Continue collecting; the decisive
  test is real demo-exchange execution (queue position), not more shadow.

---

## Maker backtest attempt (2026-09-11) — BUILT, THEN INVALIDATED

Motivation: judging the maker leg on ~78 live fills cannot separate a
73%-hit edge from a 66%-hit break-even run. The 6,655-market candle history
should have supplied n in the thousands. It could not, and finding out why
is the useful result.

**First run reported +944%, t=11.07.** Two red flags: the "queue" fill mode
produced MORE fills than the looser "through" mode, and realised P&L was
11.5¢/contract when the strategy only demanded a 4¢ margin.

**Bug 1 (fixed).** The fill test read the QUOTE range: `bid_low <= our_price`.
Since quotes are posted at `best_bid + 1¢`, that condition is true by
construction — every quote filled instantly and unconditionally. Fixed to
require an actual TRADE print at our level (`px_low`/`px_high` from the
candle's last-trade OHLC, which the loader now carries).

**Bug 2 (fatal, not fixable at this resolution).** After the fix the result
barely moved (+793%, t=10.36). The null-model control settles it:

| variant | fills | P&L | hit | t |
|---|---|---|---|---|
| model-driven | 1,405 | +$3,963 | 0.773 | 10.36 |
| **market-mid (NO model)** | 2,480 | **+$6,342** | 0.750 | **12.05** |

Removing all predictive input makes the backtest *better*. The P&L is
therefore not coming from prediction — it is fill mechanics. Root cause:
trade prices swing widely inside one minute (a 0.40/0.41 quote routinely
sees prints from 0.41 to 0.58), so "a print touched my level → fill me at my
limit" hands the strategy the intra-minute extreme on every fill. That is
the buy-the-low fallacy, and it is the same family of error as the taker
backtest's zero-latency fill, arrived at by a different route.

**Consequence: 1-min OHLC cannot validate a maker strategy at all.** Queue
position, partial fills, and intra-minute path are all unmodellable from it.
A valid version needs the per-print trades tape (`GET /markets/trades`:
price, taker_side, timestamp) so a resting YES bid at P fills only against
real SELL prints at ≤P, after enough volume clears the queue ahead.

**What shipped from this:**
- `quantfirm/kalshi/maker.py` — the engine, with the invalidation stated at
  the top of the module so its numbers can never be quoted innocently.
- `MarketMidControl` + `cli.py maker-control` — the null-model test as a
  permanent guard. It prints `*** INVALID ***` on the current fill model.
  **Any future fill-model change must beat this control before belief.**
- 3 regression tests (`TestMakerFillRealism`) pinning the quote-touch bug.

**Net effect on the desk's conclusions: none of them improve.** The maker
leg's only honest evidence remains the live shadow record (n≈78, t decaying
1.84 → 1.52 → 1.23). This exercise removed a false source of confidence
rather than adding a true one — which is the correct outcome when the data
cannot support the claim.

* 2026-09-11T15:03Z (auto check-in). Maker +105.60 (80 fills, 57/80 won). Taker +91.82 (20). **Cumulative maker +105.60 (80 fills, hit 0.713 vs break-even 0.673, cushion +3.94pp, t=0.71).** t-history: 0.71.

* 2026-09-11T16:05Z (auto check-in). Maker +100.00 (12 fills, 11/12 won). Taker +35.49 (2). **Cumulative maker +205.60 (92 fills, hit 0.739 vs break-even 0.671, cushion +6.76pp, t=1.35).** t-history: 0.71 → 1.35.

* 2026-09-11T16:42Z (auto check-in). Maker -19.57 (2 fills, 1/2 won). **Cumulative maker +186.03 (94 fills, hit 0.734 vs break-even 0.675, cushion +5.91pp, t=1.19).** t-history: 0.71 → 1.35 → 1.19.

* 2026-09-11T17:03Z (auto check-in). Taker -19.03 (1). **Cumulative maker +186.03 (94 fills, hit 0.734 vs break-even 0.675, cushion +5.91pp, t=1.19).** t-history: 0.71 → 1.35 → 1.19.

* 2026-09-11T19:05Z (auto check-in). Maker -10.43 (4 fills, 3/4 won). Taker -20.72 (2). **Cumulative maker +175.60 (98 fills, hit 0.735 vs break-even 0.682, cushion +5.31pp, t=1.09).** t-history: 0.71 → 1.35 → 1.19 → 1.09.

* 2026-09-11T19:20Z (auto check-in). Maker -8.46 (2 fills, 1/2 won). **Cumulative maker +167.14 (100 fills, hit 0.730 vs break-even 0.680, cushion +4.99pp, t=1.03).** t-history: 0.71 → 1.35 → 1.19 → 1.09 → 1.03.

* 2026-09-11T20:04Z (auto check-in). Maker -32.72 (4 fills, 2/4 won). Taker -29.13 (1). **Cumulative maker +134.42 (104 fills, hit 0.721 vs break-even 0.683, cushion +3.79pp, t=0.80).** t-history: 0.71 → 1.35 → 1.19 → 1.09 → 1.03 → 0.8.

* 2026-09-11T21:05Z (auto check-in). Maker +25.10 (2 fills, 2/2 won). Taker +3.78 (1). **Cumulative maker +159.52 (106 fills, hit 0.726 vs break-even 0.682, cushion +4.41pp, t=0.94).** t-history: 1.35 → 1.19 → 1.09 → 1.03 → 0.8 → 0.94.

* 2026-09-11T22:05Z (auto check-in). Maker +73.31 (6 fills, 4/6 won). Taker -2.29 (3). **Cumulative maker +232.83 (112 fills, hit 0.723 vs break-even 0.665, cushion +5.82pp, t=1.22).** t-history: 1.19 → 1.09 → 1.03 → 0.8 → 0.94 → 1.22.

* 2026-09-11T22:37Z (auto check-in). Maker +15.62 (4 fills, 2/4 won). Taker -0.69 (2). **Cumulative maker +248.45 (116 fills, hit 0.716 vs break-even 0.658, cushion +5.76pp, t=1.20).** t-history: 1.09 → 1.03 → 0.8 → 0.94 → 1.22 → 1.2.

* 2026-09-11T23:08Z (auto check-in). Maker +65.76 (4 fills, 4/4 won). Taker +19.57 (2). **Cumulative maker +314.21 (120 fills, hit 0.725 vs break-even 0.655, cushion +7.01pp, t=1.50).** t-history: 1.03 → 0.8 → 0.94 → 1.22 → 1.2 → 1.5.

* 2026-09-12T00:04Z (auto check-in). Maker -162.77 (6 fills, 1/6 won). Taker -56.48 (2). **Cumulative maker +151.44 (126 fills, hit 0.698 vs break-even 0.667, cushion +3.10pp, t=0.67).** t-history: 0.8 → 0.94 → 1.22 → 1.2 → 1.5 → 0.67.

* 2026-09-12T01:18Z (auto check-in). Maker +1.65 (5 fills, 3/5 won). Taker +0.76 (9). **Cumulative maker +1.65 (5 fills, hit 0.600 vs break-even 0.574, cushion +2.57pp, t=0.10).** t-history: 0.1.

* 2026-09-12T01:42Z (auto check-in). Taker +3.09 (3). **Cumulative maker +1.65 (5 fills, hit 0.600 vs break-even 0.574, cushion +2.57pp, t=0.10).** t-history: 0.1.

* 2026-09-12T01:53Z (auto check-in). Taker +4.20 (4). **Cumulative maker +1.65 (5 fills, hit 0.600 vs break-even 0.574, cushion +2.57pp, t=0.10).** t-history: 0.1.

* 2026-09-12T02:11Z (auto check-in). Taker +2.05 (2). **Cumulative maker +1.65 (5 fills, hit 0.600 vs break-even 0.574, cushion +2.57pp, t=0.10).** t-history: 0.1.

* 2026-09-12T02:29Z (auto check-in). Taker -7.42 (3). **Cumulative maker +1.65 (5 fills, hit 0.600 vs break-even 0.574, cushion +2.57pp, t=0.10).** t-history: 0.1.
