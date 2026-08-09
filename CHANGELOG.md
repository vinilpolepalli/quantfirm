# Changelog

Versions describe the **firm**, not just the code: a release can change what
the desk is allowed to do with real money, so each entry says plainly what
moved and what evidence backs it.

---

## 0.1.1 — 2026-08-09 — selectable risk profiles

### Added

**Risk profiles.** A new owner cloning this repo picks a risk posture at setup
instead of inheriting the previous owner's.

```
python scripts/setup.py                 # interactive first-run
python scripts/profile.py list          # the ladder and its measured numbers
python scripts/profile.py apply <name>
python scripts/profile.py current       # what is actually running, and why
```

| profile | strategy | drawdown (median of 21 anchors) | CAGR | holdout |
|---|---|---|---|---|
| conservative | `allweather_trend` | −14.8% (−18.0% … −9.7%) | 5.6% | not measured |
| balanced | `xsec_refined` top_n=6 | −30.9% (−38.3% … −27.1%) | 31.6% | Sharpe 1.47, DD −39% |
| aggressive | `xsec_refined` top_n=4 | −32.9% (−36.5% … −24.2%) | 34.4% | not measured |
| ultra_aggressive | `xsec_refined` top_n=2 | −36.4% (−48.6% … −23.7%) | 39.7% | not measured |

`ultra_aggressive` is the only setting above `aggressive` that buys anything: more
return (39.7% vs 34.4%) for more risk (−36.4% vs −32.9%). Everything more extreme
was measured and rejected — `top_n=1` returns *less* than `top_n=4` at a −50.9%
drawdown with a negative fold; dropping vol-scaling reaches −52.8% worst-anchor,
which would need a −79% halt line, i.e. no meaningful kill switch at all.

Every rung carries the numbers it actually produced, the disclosure of what it
does *not* protect against, and a `not_for` line. `apply` refuses on a funded
book unless the caller acknowledges that switching forces a rebalance, replaces
the params block wholesale rather than merging, and asserts the write
round-trips before returning.

`VERSION` and this changelog now exist; the state before this release is
retroactively 0.1.0.

### Fixed

**`config/equity_live.json` claimed a defense that does not exist.** The notes
credited the per-name absolute-momentum routing with capping the holdout
drawdown at −39%, and said removing it was untested. Both halves were wrong.
It was tested here: `abs_filter=false` produces bit-identical weight matrices
(`DataFrame.equals() == True`), and the filter rejects a name on **0 of 89**
dev rebalance dates at every `top_n` from 3 to 12. It is structurally
unreachable — a non-positive-momentum name can only enter the rank band when
fewer than `band_mult * top_n` of ~193 names have positive 8-month momentum
(9.3% breadth at `top_n=6`, against a dev floor of 16.6%). So the −39% holdout
drawdown happened with **no** defensive routing engaged. At `gate_mode=none`
the kill switch is the only risk control this book has, and the profile picker
now says so out loud. Live params unchanged pending a tournament.

### Changed

Nothing about the running book. `balanced` is the incumbent configuration
exactly; `config/equity_live.json` gains `risk_profile: "balanced"` to record
what it already was.

### Known-wrong, logged not fixed

- **`walk_forward` fits nothing in-sample**, so its output is arithmetically
  identical to a single run over the same bars. Every `oos_sharpe` in this repo
  — including the incumbent's 1.349 — is an in-sample dev-window figure. The
  profile UI labels them correctly; the field name is still a lie. (backlog M.1)
- **No trial registry exists**, so the 24 distinct configurations measured for
  this release cannot be registered and the deflated-Sharpe denominator is
  unknowable. CSCV on the sweep gives **PBO = 0.496** against the firm's own
  ≤0.10 bar, which is why rungs were chosen on mechanical grounds — number of
  names, whether a gate can de-risk, where the halt line sits — and not by
  sweep rank. (backlog M.2)
- **`quantfirm/equities/reconstruct.py` duplicates the dead `abs_filter`
  branch**, so the post-incident recovery path carries it too. (backlog L.2)

### Rejected during review

A first draft shipped `xsec_refined top_n=8, gate_mode=half` as "conservative"
on a −25.4% drawdown. Adversarial review killed it: −25.4% was the best of 21
rebalance anchors, the median is −29.2%, and it loses to the incumbent on every
duration-aware measure — Ulcer index, average drawdown, time below −20%,
recovery time (24 months vs 10 weeks) and 2022 return (−19.5% vs −5.4%). The
same draft paired it with `kill_drawdown=0.35`, inside the strategy's own
drawdown distribution and below its only out-of-sample drawdown, which would
have converted a normal momentum drawdown into a permanent liquidating exit.
Both are recorded in `config/profiles.json` under `rejected` so they are not
re-proposed.

---

## 0.1.0 — 2026-07-31 → 2026-08-07 — the firm as first built

Crypto desk researched and rejected (tournament NO-GO). Equity desk built,
tournament-tested, and funded at $250 under an explicit owner override of the
capital-preservation recommendation. Execution desk, risk committee and
research desk running on schedules; dashboard and daily reports published;
venue-truth reconciliation, T+1/GFV-safe execution, stale-panel guard and
cash-contribution accounting added as defects were found.
