# Tournament #3 — five backlog candidates vs the live incumbent (2026-08-01)

**Verdict: no promotion. `xsec_refined` defended its seat.** Three
candidates KILLED, two WATCH-listed. Registry now at ~486 trials. New this
round: an independent replication phase — every designer claim was reproduced
from scratch by a separate auditor before judging (all five reproduced; two
surfaced a production bug, fixed below).

## Results

| candidate | dev OOS | vs incumbent 1.343* | verdict | why |
|---|---|---|---|---|
| xsec_canary (TIP canary defense) | 1.342 | tie, fold-inconsistent | **KILL** (pre-declared kill fired) | canary whipsaw: buys the 2022 fold by wrecking folds 1+3; fragile (fold 1 → −0.56 under ±25% perturbation) |
| xsec_lowvol (low-vol risk-off sleeve) | 1.343 | bit-identical | **KILL** (success criterion unmet) | structurally inert — see headline finding |
| xsec_residmom (residual momentum) | 0.999 (1.067 clean) | loses every fold | **KILL** (pre-declared kill fired) | beta-hedging strips exactly the market-trend component the incumbent's edge rides |
| cal_tomopex (turn-of-month + OpEx) | 0.829 | best fold-consistency in field | **WATCH** | holdout printed **−0.615 vs SPY 1.071** — the TOM effect inverted post-2024; genuine contrary evidence (holdout losses count even when holdout wins wouldn't) |
| taa_haa (Keller HAA) | 0.707, maxDD −8.3% | beats 60/40, not the mandate | **WATCH** | passes its own bar (vs 60/40) with tiny drawdowns; DSR 0.119 at 486 trials fails the gate. Noted as the capital-preservation alternative if the mandate ever flips |

*The incumbent re-runs at 1.343 on the extended panel (vs 1.349 recorded) — see the bug below.

## Headline finding: the incumbent's risk-off routing is dead code

The lowvol experiment proved that under champion parameters
(`gate_mode=none`), `xsec_refined`'s documented "rotate failing slots into
defensive ETFs" path **never fires on dev**: with 200 names, at least 6
always pass the per-name momentum filter (median 120 qualify). The live
strategy is, in practice, always fully long its top 6. Implications:
- Its −39% holdout drawdown happened *without* any defensive mechanism
  engaging — the real risk profile is "always-long concentrated momentum."
- The gated A/B showed low-vol-stock sleeve > bond menu *when* risk-off
  actually fires — but every gate tested costs more Sharpe than the
  destination improvement recovers. Filed to the backlog: defensive-routing
  work needs a trigger worth its cost before destinations matter.

## Production bug found by replication (fixed this commit)

Designers added TIP/BIL price files for their briefs; `load_panel()` globs
the data directory, and the incumbent's hardcoded ETF-exclusion list
predated those files — so a fresh live run would have ranked **bond ETFs as
momentum stocks** (residmom's backtest actually held TIP at up to 76%).
Fix: the stock universe is now defined positively from `universe.json`
(fallback to an extended exclusion set), in both `xsec_refined` and the
baseline. Verified: live targets unchanged, TIP/BIL unholdable.

## Process notes

- Two families honored **pre-declared kill conditions** and reported their
  own deaths — the anti-overfitting registry working as designed.
- The judge applied one-sided holdout skepticism correctly: the holdout
  (opened in tournament #2) can't confirm winners anymore, but a decisive
  holdout LOSS (cal_tomopex) is still disqualifying evidence.
- Composition testing wasn't reached: no module improved the incumbent
  fold-consistently, so there was nothing to compose.

## Standing state

- Live seat: `xsec_refined`, unchanged, contamination-fixed.
- WATCH: cal_tomopex (gate: TOM inversion must resolve), taa_haa
  (capital-preservation alternative).
- Graveyard additions: canary defenses on this chassis, low-vol destination
  swaps without a firing gate, residual momentum on this chassis.
- Next research lever remains **data, not strategies**: total-return prices
  (Tiingo) per IDEA_BACKLOG Tier 3.
