# Changelog

Versions describe the **firm**, not just the code: a release can change what
the desk is allowed to do with real money, so each entry says plainly what
moved and what evidence backs it.

---

## 0.2.5 — 2026-09-18 — incentive desk killed; $257 goes to perps

Owner killed the Kalshi Liquidity Incentive Program book. The collector,
quoter, scan, stress test, runbook, research memo, and paper state are
removed. The GitHub Actions workflow is gone, which is what stops the
20-minute tick. Nothing was ever armed; no live LIP orders existed to
cancel.

The $257 that sat in predictions for that book transfers to Kalshi perps
**by the owner**. This release does not lift `KILL_SWITCH_PERPS`, does not
set `live: true`, and does not send a perps order. Next work is the perps
desk, behind the existing promotion gate in `docs/KALSHI_PERPS.md` §7.

---

## 0.2.4 — 2026-09-15 — three paper books, and a daily report the owner actually reads

### Added

**A third paper book, `growth`, because the owner said risk is acceptable.** Same
blend, dial turned up: an 18% volatility target and a 40% sleeve. Measured out of
sample 2021-10 to 2025-06 before it was started, not after:

| config | return | volatility | max drawdown | Sharpe |
|---|---:|---:|---:|---:|
| core only, 12% target | 15.37% | 12.25% | −10.12% | 1.255 |
| blend, 12% target, 30% sleeve | 15.22% | 8.99% | −8.64% | 1.694 |
| blend, 18% target, 40% sleeve | 21.96% | 12.76% | −13.14% | 1.721 |
| blend, 24% target, 40% sleeve | 27.22% | 16.44% | −16.51% | 1.655 |

The 18% blend carries about the same realised risk as the plain core book at a
12% target and earns half again as much. The sleeve weight optimum is 40% at
every volatility level, so the dial that matters is the target, not the mix.
P(better than its own core) 0.869. Every caveat of the 12% version applies and
scales with it: one regime, a well-published and likely crowded effect, and a
failed deflated-Sharpe gate. Raising the target multiplies the loss too if the
edge is not real.

**A daily email report** (`scripts/perps_daily_report.py`). Reads every book's
status, compares against yesterday's snapshot in
`state/perps_report_history.jsonl`, and prints JSON with `subject`, `html` and
`text`. The HTML is inline-styled and table-based because email clients strip
`<style>` blocks; Markdown is deliberately not used, since an email client
renders HTML and a raw asterisk is not a bullet. A daily routine at 02:00 UTC
ticks the books, runs the script and sends the mail.

### Fixed

**The paper engine's rebalance band was fixed at 0.03** while a twenty-name book
wants 1–2% per leg, so a wide book held only its four core legs and was quietly
the incumbent at 70% size. The band now scales with the universe and is still
exactly 0.03 at four names. **The CLI's `--universe` defaulted to the research
four** rather than to nothing, so it was indistinguishable from "not given" and
overrode a book's own universe; it defaults to None now and resolves to the
research four, leaving every published number byte-identical.

---

## 0.2.3 — 2026-09-15 — a sleeve that improves the book, and four defects that nearly hid it

### Added

**`xsmom_residual`: market-residual cross-sectional momentum, registered as a
sleeve rather than a replacement.** Two rounds and twenty-two trials had found
nothing because every candidate was the long book in a hat, correlated 0.68 to
0.996 with the thing it was meant to beat. On a universe whose first principal
component is two thirds of the variance, a raw cross-sectional return sort IS a
beta sort. Strip each name's beta to the equal-weight crypto market first and
the residual correlation among names averages −0.08 where the raw correlation
averages 0.594.

Out of sample, 2021-10 to 2025-06, four folds: sleeve Sharpe 1.028 with 4/4
folds positive, correlation to the long book **−0.156**. Blended at 30% the
book goes from Sharpe 1.255 to **1.694 at the same 15.2% return**, volatility
12.25% to 8.99%, drawdown −10.12% to −8.64%. Paired bootstrap P(blend beats
core) 0.947, and every weight from 20% to 60% beats the core. Under 1.5× fees
and Binance proxy funding the blend scores 1.532 against the core's 1.154 — the
advantage widens under stress. Timing-null percentile 0.983 against a null mean
of −0.368, the strongest of either round.

**It is not promoted.** The deflated Sharpe is 0.695 against a bar of 0.95:
1,119 out-of-sample days at 82 registered configurations need an annual Sharpe
of 2.33. That is a window-length failure, since most of the coins had not
listed before 2021-10, and it cannot be fixed except by waiting. It goes to
paper beside the incumbent.

**A protocol finding worth more than the family.** `beats_benchmark_oos`
compares a candidate's standalone Sharpe to the benchmark's. That is right for
an overlay 0.9-correlated with the long book and wrong for a sleeve at −0.156,
where the blend is the object and the standalone number is nearly meaningless.
The gauntlet needs a portfolio-level gate, and every family should report its
correlation to the long book as a headline number.

### Fixed

Four defects found by adversarial verification of the breadth engine, two of
which had already reached published numbers:

- **`run(start=None)` began in 2000 instead of 2016.** `min_assets` defaulted to
  1, so the window started where ANY asset quoted. The tournament calls
  `run_strategy(start=None)` for every control, dev grid point and stress run,
  so the published control table and 87 tournament entries were produced by a
  call whose window had silently moved. `min_assets` now defaults to all assets.
- **The wide book was never held.** `rebalance_band` was fixed at 0.03 while the
  wide weight step is 0.05×4/n, so for any universe past six names one step
  never cleared the band: twenty markets quoted and 2.51 were held. The band now
  scales with the step, and `avg_n_held` sits beside `avg_n_available`.
- **Maker orders were charged a spread.** A model with no flat spread is a maker
  model and pays the fee alone.
- **Positions were opened in markets that printed no bar.** Exposure in a 24/7
  market may now be held or cut without a bar today, never increased.

Also: the three listed-but-unquoted markets are capped at zero weight rather
than priced as the cheapest on the board, and the kSHIB note no longer teaches
the arithmetic the code was fixed to reject.

### Corrected

`BREADTH_FINDING.md` reported the wide passive book at Sharpe 0.49 and called
the gap economic. Both the sizing path and the rebalance band were wrong. The
corrected comparison, with both books holding their names at target volatility:
the wide book earns 12.0% a year against the narrow book's 18.0% at the same
risk, P(wide better) 0.142. The verdict did not change; the magnitude did,
twice, and the file keeps the correction note rather than quietly restating.

---

## 0.2.2 — 2026-09-15 — the whole perps universe, and the finding that it does not help

### Added

**The desk covers all 23 listed Kalshi perps.** Specs for every market with
its own contract size, maintenance rate (6.6% on gold to 59% on WLD) and
measured top-of-book half-spread; Coinbase spot proxies for all 21 crypto
names, from LTC in 2016 to HYPE in 2026; a native-bar availability mask so a
delisted or not-yet-listed asset contributes nothing rather than a
forward-filled price; and per-asset trading costs, so a book trading LINK is
charged 21.7 bps a side rather than BTC's 14.5.

`quantfirm/perps/tournament.py` can now score one universe against another:
`reference_universe` runs the benchmark on a second universe over the same
folds and adds a `beats_reference_oos` gate, because a wide book has to beat
the narrow book the desk would otherwise hold, not just its own passive
version. Runs are tagged so one never overwrites another.

### Fixed

**The backtester could not simulate a universe whose members list at
different times.** It started every run where the *last* asset had a price,
so any wide universe silently began years late. Assets now enter and leave as
they list and delist, with no phantom equity at either boundary.

**A kSHIB contract was priced at half a cent instead of $5.21.** KXKSHIBPERP's
underlying is kSHIB, a thousand SHIB, so one contract is 1,000,000 SHIB.
Multiplying by contract size alone understated it a thousandfold and would
have made SHIB look infinitely divisible to the $250 account this desk is
sized for. Checked against the venue's own marks for BTC, DOGE, LINK and
kSHIB.

Every published four-asset number reproduces exactly across both fixes:
`vol_target_hold` from 2018 is still Sharpe 0.94, CAGR 15.45%, drawdown
−21.15%, turnover 1.68.

### Verdict

**Breadth is an illusion on this venue, and the round was closed without
registering a single family.** Eighteen crypto names carry 2.51 effective
independent bets against the four researched assets' 2.44, at a mean pairwise
correlation of 0.589; by the definition that maps to a long-only book's
Sharpe, both books score 2.02 — a multiplier of exactly one. Eleven of
seventeen names lost money over 2021-10 to 2025-07. Correctly sized, the
passive wide book is statistically indistinguishable from the narrow one — a
paired block bootstrap puts P(wide better) at 0.300 from 2018 and 0.556 from
2021-10 — and earns a third as much, 6.7% a year against 18.0%, because alt
maintenance margin of 26% to 59% will not let those names be held in size at
any sensible risk target. What advantage the wide book appears to have is a
rebalancing return that survivorship manufactures. Cross-sectional
momentum produces no t-statistic above 0.52 at any formation or holding
horizon, gross of costs. Time-series trend with a short side — the one thing
four assets could never test — scores 0.86 at a 30-day lookback and −0.03 at
90 days, which is noise across a parameter, not a signal.

Ten configurations that a free screen already shows to be empty would raise
the deflated-Sharpe bar for every future idea and buy nothing, so none was
registered. `research/kalshi_perps/BREADTH_FINDING.md` has the measurement.

The practical consequence for the backlog: more coins are not the missing
diversifier. All twenty tradable crypto perps together are two and a half
bets, so the only thing worth waiting for is a perp outside crypto.

---

## 0.2.1 — 2026-09-15 — perps research campaign: twelve ideas, none passes

### Added

**A ten-agent research campaign on the perps desk** under a written protocol
(`research/kalshi_perps/CAMPAIGN.md`): each agent took one strategy family,
declared its hypothesis, mechanism, external evidence and a grid of at most
six configurations before the first backtest, ran on the DEV window only, and
reported what the tools printed. Families: perp basis and funding as a
crowding gauge, the Deribit DVOL variance risk premium, dual momentum,
cross-sectional momentum, turn-of-month and weekend seasonality, weekly
reversal, Bollinger mean reversion, a macro-gated metals sleeve, a drawdown
and volatility crash filter, EWMA trend strength, a meta-allocator, and
Kalshi-native intraday microstructure. Code in `quantfirm/perps/families/`,
reports in `research/kalshi_perps/families/`, referee write-up in
`research/kalshi_perps/CAMPAIGN_RESULTS.md`.

### Verdict

**No family passes; the sealed holdout was not opened.** Twenty-two
walk-forward trials: the best, a perp-basis crowding gauge, scores
out-of-sample Sharpe 1.100 against the passive control's 1.131 and is
0.996-correlated with it. Best deflated Sharpe 0.824 against a bar of 0.95 at
113 registered trials; CSCV probability of backtest overfitting 0.586 across
62 configurations against a bar of 0.10. Every gate-style overlay has a
0.13–0.36 probability of beating the control on a paired block bootstrap: it
gives back more in missed rallies than it saves in the 2018 and 2022 bear
legs. No Kalshi-native intraday effect clears twice the round-trip cost.

The paper incumbent (`trend_long_only`, 12% vol target) is unchanged, and so
is the conclusion from 0.2.0: what the desk runs is vol-targeted long beta
behind a trend gate, which is a posture, not an edge.

### Honest caveat

Seven of the ten designer agents were terminated mid-run by the account's
monthly spend limit. `trend_v2` and `allocator_blend` have code and registry
rows but no designer report, and the planned adversarial round was not
spawned; the referee ran those four robustness checks itself. The truncation
cut the campaign's breadth, not its verdict — the tournament, deflated Sharpe
and overfitting test ran over every registered configuration.

### Not changed

Nothing trades. `config/perps.json` still has `live: false`.

---

## 0.2.0 — 2026-09-15 — perps desk: research, shadow book, NO-GO for alpha

### Added

**A Kalshi perpetual-futures desk** (`quantfirm/perps/`, `docs/KALSHI_PERPS.md`)
built against the `/margin` API: venue specs read from the public endpoints
(20 contracts, maintenance rates, the 0.01% funding deadband, the 12/5 bps
tier-0 fees from the CFTC filing), a keyless data layer (Coinbase spot and
Yahoo futures as multi-year proxies, Kalshi's own candles and funding for the
live period), a daily portfolio backtester that books fees, funding,
collateral interest and intraday liquidation, walk-forward with in-sample
parameter selection, CSCV probability of overfitting, deflated Sharpe, a
pre-registered tournament, a risk policy with three rungs, a shadow / demo /
live engine with a deterministic order path, a LangGraph loop, a supervisor
script, a daily shadow workflow and 32 unit tests.

### Verdict

Thirteen registered trials on BTC/ETH/gold/silver, 2016–2025 dev window:
**no candidate beats vol-scaled long-only out of sample** (benchmark OOS
Sharpe 1.13 vs the best candidate, a long-only trend gate, 0.80; PBO 0.30;
DSR 0.66). Long/short trend scores 0.4–0.5, the gold–silver ratio idea is
negative, the coin-flip control loses. The trend gate halves the drawdown
(−12.5% vs −18.4% OOS) at the cost of return. The holdout was opened once
for the paper incumbent: +23.7% at −4.9% drawdown from 2025-07-01, against
the benchmark's +27.1% at −11.6%.

Funding carry is not a strategy on Kalshi: rates below 0.01% per interval
round to zero and 55–97% of intervals are zero. Market making, cross-venue
arbitrage and intraday mean reversion are excluded by the 24–29 bps
round trip.

### Not changed

Nothing trades. `config/perps.json` has `live: false`; the engine refuses
live without that flag, `KALSHI_LIVE=1`, a perps key and no
`state/KILL_SWITCH_PERPS`. The promotion gate is in `docs/KALSHI_PERPS.md` §7.

---

## 0.1.3 — 2026-08-09 — a fresh clone no longer arrives holding someone else's book

### Fixed

**A new owner's first clone came with the previous owner's live positions and
trading switched on.** The books are committed (`state/`,
`dashboard/reports/`), so `git clone` handed over six real positions, $16.19 of
cash, eight equity marks and `enabled: true`. Point that at your own brokerage
account and the planner believes it owns things you do not own, and it is armed
from the first minute. The README told an *agent* to clear the books; nothing
enforced it, and nobody following the quickstart by hand would have.

`scripts/setup.py` now detects an inherited book and refuses, printing exactly
what it found:

```
REFUSING: this clone still holds the previous owner's book.
  positions : INTC, LRCX, MU, SNDK, STX, WDC
  cash      : $16.19
  marks     : 8
  trading   : ENABLED
```

`--clear-books` wipes their state, trade log and reports and disarms trading;
`--keep-books` is the escape hatch for an owner who really is resuming their
own book. `--check` flags positions held with no account configured. A test
covers both paths.

Found by cloning the public repo the way a new owner would, rather than
assuming the documented setup order would be followed.

### Added

A **Getting started (new owner)** quickstart at the top of the README with the
correct three commands.

---

## 0.1.2 — 2026-08-09 — upgrading an existing clone, and no ETFs on the stock rungs

### Added

**`scripts/upgrade.py`** — moving a running clone to a newer version.

This is not `git pull`, because the books are committed. `state/`,
`config/equity_live.json` and `dashboard/reports/` are all tracked, so a clone
that has been trading has diverged on exactly the paths upstream also changes.
A plain pull conflicts, and the tempting resolution — take theirs — merges the
upstream owner's positions into your ledger. For a live trading system that is
a corrupted book, not a merge conflict.

So the repo is split in two and the halves are treated differently:

| | |
|---|---|
| **SYSTEM** — code, docs, workflows, profiles | taken from upstream wholesale |
| **OWNER** — books, live config, reports, keys | never overwritten, only migrated |

```
python scripts/upgrade.py --check     # what would change, touches nothing
python scripts/upgrade.py             # do it (books backed up first)
```

If you are on a version that predates this script, bootstrap it with git
rather than piping anything into a shell:

```
git remote add upstream https://github.com/vinilpolepalli/quantfirm.git
git fetch upstream main
git checkout upstream/main -- scripts/upgrade.py
python scripts/upgrade.py --check
```

It refuses to run with local edits to system files, with the kill switch
tripped, or with an unresolved pending order — an upgrade should never be
tangled up with an incident. Migrations are a registry keyed by version, so
adding 0.1.3 means appending one function.

The 0.1.0 → 0.1.1 migration tags your existing configuration against the
profile ladder **without changing it**: if your params match a shipped
profile it is labelled as that, and if you tuned your own they are left
untouched and marked `custom`. It seeds `cost_basis` from your own bankroll,
and prints the two behaviour changes that release introduced.

### Changed

**The stock rungs no longer carry defensive-ETF config.** `balanced`,
`aggressive` and `ultra_aggressive` declare `holds_etfs: false`, and
`def_menu` / `def_lookback` / `def_k` are gone from their params.

This is a truth-in-config change, not a behaviour change. Those three rungs
never held an ETF: measured max ETF weight across the entire dev window is
**0.0000**, and removing the config produces bit-identical weight matrices.
The sleeve was dead for the reason recorded in 0.1.1 — `abs_filter` never
fires, so `def_total` is always zero at `gate_mode=none`.

`conservative` still holds ETFs, and now says so loudly, because that is
where its conservatism comes from. Every stock-only alternative was measured
and none reaches below −28% drawdown: low-vol ranking −28.1%, twelve names
−32.5%, twenty names −32.9%, against the ETF book's −14.8%. On a long-only
single-stock universe you are always fully exposed to the equity market. A
new test asserts the declared `holds_etfs` against the actual weights rather
than trusting the label.

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
