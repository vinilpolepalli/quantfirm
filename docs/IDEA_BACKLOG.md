# IDEA_BACKLOG.md — Canonical Idea Pipeline

**Source:** `github.com/paperswithbacktest/awesome-systematic-trading` (README strategy catalog, ~45 entries + 97 libraries) plus the paperswithbacktest.com ecosystem (SSRN originals, AllocateSmartly OOS tracking, HuggingFace datasets), mined 2026-08-01 across five lenses: equity-stock, etf-taa, crypto, tooling, method.
**Date:** 2026-08-01
**Maintainer:** Head of Research. This is the canonical pipeline document; the weekly research desk consults this file and does not re-mine the source.

**How this backlog feeds tournaments:** Ideas enter here graded and pre-triaged. Tier 1 entries carry a ready-to-use designer brief; the designer turns a brief into a registered tournament candidate (trial registry entry, parameter grid declared up front). Candidates run the gauntlet: 4-fold walk-forward net Sharpe on dev (2016-2024), deflated-Sharpe penalties against the full trial registry, adversarial review, then — only for survivors — the sealed holdout (2024-08+). Gauntlet survivors that beat the incumbent go live. Nothing in this file, however promising it reads, is evidence of anything until it has been through that sequence.

**Incumbent to beat:** `xsec_refined` (vol-adjusted 6-1 momentum, top-6, rank-band, defensive rotation) — dev OOS Sharpe **1.35**, holdout **1.47**, stock track.

**Headline finding of this mining cycle (read before pitching anything):** Nothing in this catalog is likely to beat `xsec_refined` standalone under our constraints. The catalog's own QuantConnect replications — an unusually honest feature of the source — show most published anomalies at Sharpe 0.15-0.72 before our cost and long-only haircuts (generic stock momentum replicates at **-0.008**). The real yield of this cycle is: (a) two cheap upgrade experiments on the incumbent itself, (b) one genuinely new strategy shape on the bias-free ETF track, (c) a data-correctness fix (total-return prices) that may retroactively change past GO/NO-GO calls, and (d) method upgrades that make the gauntlet stricter. Tier 1 reflects that.

---

## TIER 1 — Next Tournament Candidates

Six entries. The sixth slot was deliberately left empty rather than padded in the 2026-08-01 cycle; 1.6 was added 2026-08-07 from a live-desk observation and is graded honestly rather than promoted to fill space — its expected uplift is the lowest in the tier and it is blocked on a data adoption. Ordered by probability-weighted expected uplift against the incumbent, not by standalone Sharpe.

### 1.1 XSEC-CANARY — Momentum-selected canary defense for `xsec_refined`

- **Thesis:** The incumbent's defensive rotation is its weakest module. The Keller family's two post-2022 fixes — HAA's TIPS canary (go risk-off when TIP's 13612W momentum, the average of 1/3/6/12-month returns, turns negative) and BAA's momentum-selected defensive asset (pick the best of TIP/BIL/IEF/TLT/LQD by momentum instead of defaulting to bonds) — are documented answers to exactly the failure mode (2022: bonds fell with equities) that a cash/bond-default rotation carries. Upgrading the incumbent directly attacks the 1.35 with the smallest possible change surface.
- **Cadence:** Monthly, unchanged from incumbent. Turnover impact near zero.
- **Evidence grade:** B for the canary mechanisms (SSRN 4166845, 4346906; only 3-4 years true OOS, and the Keller papers form a sequential chain where each fixes the last one's most recent OOS failure — treat post-2018 improvements as partly in-sample by construction). A for the chassis it drops into.
- **Honest net expectation:** The best shot in this entire backlog at actually beating 1.35: plausibly +0.05-0.15 Sharpe and materially lower drawdown at regime turns, but the canary designs partly overlap our dev window (HAA was published *after* 2022 with the 2022 solution built in), so lean hard on deflated Sharpe and fold consistency. Kill if not fold-consistent.
- **Designer brief:** Take `xsec_refined` exactly as it stands and replace only the defensive-rotation module, in two registered variants. Variant A (canary trigger): compute 13612W = (r1+r3+r6+r12)/4 on TIP from daily closes resampled monthly; when TIP 13612W <= 0, move the book to the defensive destination; when > 0, run the incumbent unchanged. Variant B (defensive destination): when the incumbent's existing risk-off condition fires, allocate to the single best of {TIP, BIL, IEF} by 13612W momentum instead of the current default. Also register the A+B combination. Run all three against the incumbent on identical folds, identical universe, identical costs (5bps/side + $0.01/sell). Success criterion: fold-consistent improvement in net Sharpe or in MaxDD at equal-or-better Sharpe, surviving deflated-Sharpe with the trial count of this whole experiment family registered up front. Pre-declare the kill: if no variant is fold-consistent on dev, the family dies and does not return.

### 1.2 XSEC-LOWVOL-SLEEVE — Low-volatility sleeve as the incumbent's rotation destination

- **Thesis:** Low-vol (Blitz & van Vliet 2007, SSRN 980865) is the rare anomaly where the killer question passes cleanly: the published effect is substantially a long-leg phenomenon, confirmed by decades of academic OOS and live long-only fund records (USMV/SPLV). The catalog's replication (SR 0.717) is the best price-only equity entry in the table. Standalone it will not beat 1.35 — but as the *destination* of the incumbent's defensive rotation (hold the lowest-vol decile of our 200 names instead of cash/bonds when risk-off), it converts dead defensive time into a carrying position.
- **Cadence:** Monthly; vol ranks are sticky, effective sleeve turnover ~3-6 rotations/yr with rank-band hysteresis. Well inside budget.
- **Evidence grade:** A for the anomaly; the specific sleeve application is our own construction and carries no published evidence.
- **Honest net expectation:** On 2016-2024 US large caps (mega-cap growth bull), long-only low-vol lagged SPY on raw return — expect ~0.8-1.1 standalone, i.e., backlog padding as a submission. As a sleeve: real odds of improving drawdown-adjusted metrics and a modest Sharpe bump; this is a cheap experiment, not a promised edge.
- **Designer brief:** Build a defensive sleeve from the incumbent's own 200-name universe: rank by trailing 252d realized vol, hold the bottom decile-to-quintile (sweep 10 vs 20 names as a declared parameter, equal weight, fractional shares), with rank-band hysteresis to suppress churn. Wire it in as the risk-off destination of `xsec_refined`'s existing rotation, replacing the current cash/bond default; leave every other module untouched. A/B against the incumbent on identical folds. Also run the sleeve standalone once, purely to document that it does not beat the incumbent (pre-registered expectation: it will not) so the desk never re-litigates it. Success criterion: fold-consistent improvement in MaxDD and Calmar at non-degraded net Sharpe. Note for adversarial review: the sleeve inherits the stock track's survivorship haircut.

### 1.3 CAL-TOMOPEX — Turn-of-Month + OpEx-week calendar composite (ETF track)

- **Thesis:** The only genuinely *new* strategy shape this mining cycle produced. Two documented long-only calendar effects with non-overlapping windows: Turn-of-Month (hold equities ~T-4 to ~T+3 around month-end; pension/payroll flows; found in 19 of 20 countries, persistent through 2024 — SSRN 917884) and Option-Expiration week (long large caps Mon-Fri before 3rd Saturday; delta-hedge unwinding — SSRN 1571786). Composite deploys capital ~11 days/month in SPY, cash otherwise. Both effects are long-only *by construction* — the killer question passes because the published effect IS the long leg.
- **Cadence:** ~24 round trips/yr on a single ETF, ~1.2%/yr total drag at 5bps tickets. At the edge of the 12-20 rebalance budget but each event is one SPY ticket.
- **Evidence grade:** A for TOM; B for OpEx (in-sample ended 2008; post-2013 persistence unverified — treat as a live hypothesis, not a fact).
- **Honest net expectation:** Net Sharpe ~0.6-0.9 standalone — below the incumbent, and deflated Sharpe will punish the low observation count (~120 TOM windows in dev; OpEx worse). Its honest value: bias-free ETF-track diversifier with low correlation to momentum, and a cash-deployment overlay for whatever fraction of the book sits idle. Do not pitch it as an incumbent-beater.
- **Designer brief:** On the bias-free ETF track: build a trading-day calendar from daily bars; Leg 1 buys SPY at the close of month-day T-4 and exits at the close of T+3; Leg 2 buys SPY at the prior-Friday close before the 3rd Friday and exits at the OpEx-Friday close; cash (BIL proxy) otherwise. The windows never overlap by construction — verify and assert this in code. Register three trials: TOM alone, OpEx alone, composite. Optional fourth (registered): substitute the incumbent's top-momentum names for SPY in the TOM window to test compositing with `xsec_refined`. Costs at 5bps/side + $0.01/sell; also run the 15bps torture test since cadence is sub-monthly. Pre-declared kills: OpEx alone dies if it shows no post-2013 edge on dev folds (its in-sample ended 2008); the composite dies if deflated Sharpe on the low observation count cannot distinguish it from SPY buy-and-hold.

### 1.4 TAA-HAA — Keller Hybrid Asset Allocation standalone (ETF track)

- **Thesis:** Best risk/complexity ratio in the entire TAA family and the most likely of them to survive our gauntlet: a single canary (TIP 13612W) gates between top-4 of 8 risky ETFs by momentum and the best of IEF/BIL. Its legitimate claim on the book is not raw Sharpe but the bias-free ETF track, single-digit published MaxDD (vs -50% buy-and-hold), and serving as the honest flagship for capital that must show survivorship-clean evidence.
- **Cadence:** Monthly; turnover ~300-500%/yr → ~30-50bps drag. Costs are a non-issue; this family dies on whipsaw, not costs.
- **Evidence grade:** B (SSRN 4346906, 2023; documented 1970-2022 backtest but only ~3 years true OOS, and the TIPS-canary design is partly an in-sample answer to 2022 — which sits inside our dev window).
- **Honest net expectation:** Published Sharpe ~1.0 haircuts to ~0.6-0.9 on our walk-forward. It will NOT beat 1.35 raw. Expect holdout below dev — the sealed holdout contains the Apr-2025 tariff V-shock, exactly the whipsaw shape monthly TAA historically fails; that is not a bug. Portfolio-level warning: every TAA variant in this backlog is one trade in a trench coat (long US beta gated by trend with a duration/gold leg; cross-correlations 0.7-0.9), so HAA is the family's single tournament slot — the rest are Tier 2 ablations, not independent ideas.
- **Designer brief:** Universe: SPY/IWM/VWO/VEA/VNQ/DBC/IEF/TLT risky + TIP/BIL (all inside the 25-ETF bias-free list; if the no-futures rule extends to futures-holding ETFs, swap DBC for GLD and register the swap). Monthly at the close: compute 13612W per asset from daily closes resampled monthly; if TIP 13612W > 0, equal-weight the top-4 risky assets by 13612W; else 100% to the better of IEF/BIL by 13612W. Benchmark on identical folds against: SPY buy-and-hold, 60/40, and GEM (Tier 2.3) as the low-turnover family baseline. Register a Faber-GTAA-chassis variant (Tier 2.1) as the only permitted family ablation in this tournament. Success criterion: survives deflated Sharpe and beats 60/40 on Sharpe AND MaxDD on the bias-free track; explicitly NOT required to beat `xsec_refined` — it is competing for the ETF-track book, and the brief must say so to keep adversarial review honest.

### 1.5 XSEC-RESIDMOM — Residual momentum ranking A/B (feature experiment, near-zero cost)

- **Thesis:** Rank by momentum of residuals (daily returns regressed on SPY + sector ETFs) instead of raw returns — Blitz/Huij/Martens (SSRN 2319861) show halved vol and doubled risk-adjusted profit *in long-short form*. The critical decomposition (Hanauer & Windmüller): long-only conventional momentum Sharpe 0.47 vs long-only idiosyncratic 0.44 — the published improvement lives almost entirely in the short leg and vol reduction. So the honest prior is roughly zero uplift. It earns a Tier 1 slot for one reason only: it drops into the incumbent's pipeline unchanged, needs no new data, and costs approximately one day to test — a free lottery ticket on possible crash-resistance at regime turns.
- **Cadence:** Monthly, identical to incumbent; no turnover change.
- **Evidence grade:** A for the paper and the OOS confirmation (Huij & Lansdorp 2009-2015); the long-only decomposition that caps our expectation is equally A-grade.
- **Honest net expectation:** ±0.05-0.1 Sharpe around zero. The incumbent already vol-adjusts, capturing much of the same effect. One cheap A/B; kill immediately if no fold-consistent improvement. Never standalone.
- **Designer brief:** For each of the 200 names, run a rolling 252d regression of daily returns on SPY and its sector ETF; compute 6-1 momentum on the residual series, scaled by residual vol. Swap this ranking into `xsec_refined` in place of the raw vol-adjusted 6-1 rank; keep top-6, rank-band, and rotation modules untouched. A/B against the incumbent on identical folds. Declare the full parameter surface up front (regression window, momentum window) with no sweeping — use the paper's spec, one variant, one trial. Success criterion: fold-consistent net-Sharpe improvement OR materially reduced drawdown in the 2018/2020/2022 fold segments at equal Sharpe. Pre-declared kill: anything less, the experiment closes permanently and this file's Rejected table gains a row.

### 1.6 XSEC-INSIDER — Opportunistic Form 4 insider-buy overlay on the incumbent ranking

- **Origin:** Desk owner, 2026-08-07, from TipRanks "Trading Trends" panels on SNDK. Filed with a correction: those panels showed net insider *selling* over the trailing three months and two net-selling hedge-fund quarters — the eye-catching green bars were 9-15 months stale. The idea is worth testing anyway; the specific observation that prompted it was not evidence for it.
- **Thesis:** Insider *purchases* are among the better-surviving anomalies, but only once routine trades are stripped out. Cohen, Malloy & Pomorski (2012, JF) show insiders who trade in the same calendar month every year carry no information, while "opportunistic" traders earn ~82bps/month abnormal — the pooled signal is a blend of the two and is correspondingly weak. Purchases inform; sales barely do (Jeng/Metrick/Zeckhauser 2003), because executives sell constantly for diversification and scheduled comp. Form 4 is due within 2 business days, so unlike 13F the data is genuinely timely.
- **Cadence:** Overlay only — no change to the incumbent's 21-bar cadence. Turnover impact ~0.
- **Evidence grade:** A for the anomaly in its published universe. **D for our universe.** The effect concentrates in small caps with thin analyst coverage; our 227 names are large/mega-cap, where it is weakest and most arbitraged.
- **Honest net expectation:** Low. The binding problem is not signal quality, it is **breadth**: we rank 227 names and hold 6, so a ranking input needs a value for most of the universe most of the time. Opportunistic insider *buys* in mega-caps are rare — likely single digits per month across the whole universe. That rules it out as a standalone ranker before any backtest is run. The only shapes worth registering are the cheap ones: (a) a tie-breaker among names already close in momentum rank, (b) a veto/underweight on a held name with clustered opportunistic insider selling. Expected uplift if real: +0.02-0.08 Sharpe. Register with that expectation, not with the 82bps/month headline.
- **Blocked on:** Tier 3.7 (EDGAR Form 4 ingestion). No work starts until filing-date-stamped data exists — a signal built on trade dates rather than filing dates is lookahead, and would pass a backtest it does not deserve.
- **Designer brief:** Ingest Form 4 non-derivative acquisitions/dispositions per symbol, stamped by *filing* datetime. Classify each insider routine-vs-opportunistic on a trailing 3-year window per CMP 2012 (same-calendar-month repeat = routine). Build a monthly per-name score from opportunistic net buys only, scaled by insider count and by dollar value relative to the insider's holdings. Register three variants against the incumbent on identical folds: (A) tie-break within +/-2 momentum ranks, (B) veto a held name on clustered opportunistic selling, (C) A+B. Pre-declared kill: if fewer than 25% of universe-months carry a non-zero opportunistic score, the family dies on breadth grounds regardless of Sharpe — measure this *first*, before any backtest, because it is a cheap check that probably ends the experiment.

---

## TIER 2 — Worth Testing Later (one line each)

1. **Faber GTAA (10m SMA gate, 5 asset classes)** — B+ evidence, ~18yrs live OOS, net ~0.5-0.7; the defensive chassis / trend-definition ablation for TAA-HAA, not a standalone winner.
2. **Keller BAA (breadth canary + momentum-selected defense)** — blocked until our own replication matches the paper's 2004-2022 segment (QuantConnect forum replications reportedly do NOT); NO-GO fast if it can't.
3. **Antonacci GEM (dual momentum)** — the mandatory low-turnover benchmark every fancier canary must beat; live 2014-2022 underperformed SPY, so expectations are set accordingly; prefer ensemble-of-lookbacks over single 12-1.
4. **Keller PAA / VAA / DAA** — family ablations only (graded-vs-binary risk scaling; canary generations); expect HAA/BAA to dominate and these to be dropped.
5. **Keller LAA (unemployment-rate Growth-Trend filter)** — attractive do-no-harm floor (~0.6-0.75) but needs an explicit data-policy ruling on FRED UNRATE (point-in-time via ALFRED vintages) before any work; without it, skip.
6. **Paired Switching SPY/TLT (13-week momentum, quarterly)** — cheapest cost profile in the backlog but 2022 broke both legs; only worth testing with a GLD third leg + BIL absolute-momentum gate, which converges it toward HAA anyway.
7. **Sector momentum rotation (top-3 of 11 SPDRs, 12-1)** — replication SR 0.401 and post-2010 decay; only plausible as the risky-sleeve selector inside a canary chassis; XLK-dominance means one regime drives the backtest — flag for adversarial review.
8. **52-week-high proximity blend into incumbent ranking** — replication SR 0.153 says the standalone edge is mostly gone; one cheap weight-sweep for reduced crash beta (+0.05 best case), then kill.
9. **Vol-targeting overlay on the ETF sleeve (Moreira-Muir)** — Cederburg et al. (JFE 2020) show implementable versions generally don't beat unmanaged; one ablation on the best canary strategy, capped at 1x, reject if deflated Sharpe doesn't improve.
10. **Crypto long-flat trend gate (BTC/ETH, 10m-SMA or 13612W, hysteresis band, monthly)** — NOT a reopening of the desk: filed as the documented *precondition* under which crypto exposure could ever be allowed at 93bps/side (~1-3 flips/yr survives the cost math; nothing faster does), with 5pp-threshold monthly rebalancing as its construction rule.

11. **13F hedge-fund holdings tilt** — the other half of the owner's 2026-08-07 observation, graded well below the Form 4 leg: 13F is filed up to 45 days after quarter end, so a position you can see may be 4.5 months old, and the panel that prompted this showed a +50K-share quarterly change on a name with millions of shares of quarterly flow — noise, not signal. Only worth touching as Cohen/Polk/Silli "best ideas" concentration (manager's top position by weight), and only after 1.6 has cleared its breadth check.

---

## TIER 3 — Tooling & Data Adoptions

Nothing here adds alpha. Everything here adds correctness, evidence quality, or reporting capability. Total integration cost ~1 week. Priority order:

### 3.1 Tiingo EOD API — dividend/split-adjusted TOTAL-RETURN data ★ HIGHEST PRIORITY
The single biggest data capability we lack. Free tier: 30+yrs history, adjClose adjusted for both splits and dividends, explicit divCash/splitFactor columns; our 225-symbol universe fits one throttled refresh (~50 symbols/hr). **Why it matters:** if our current history is price-only, every defensive/low-vol/bond sleeve is understated by ~1.5-4%/yr of yield (SPY ~1.3%, TLT ~3-4%) — that distorts strategy-vs-benchmark comparisons enough to have flipped past GO/NO-GO calls in either direction. **Action:** register key, pull 2015-12-onward, reconcile vs incumbent feed (flag >25bps daily divergences), switch the backtester to total-return series. First check whether incumbent data is already dividend-adjusted; if yes, value drops to redundancy/QA. ~1 day.

### 3.2 Point-in-time universe — HEADLINE NEGATIVE FINDING + the calibration path
The catalog contains **no free point-in-time constituent source**; its own ecosystem gates the closest thing (paperswithbacktest Universe-Daily-Price, subscription). Real fixes are paid (Norgate, Sharadar, ~$30-60/mo — recommend budgeting for one if the stock track scales). Interim policy stands: keep haircutting the stock track, keep the ETF track as the bias-free flagship. **Cheap calibration path:** the maintainer's HuggingFace `Stocks-Daily-Price` dataset (7000+ US stocks, verified anonymously downloadable 2026-08-01, license ambiguous — clear it or subscribe first) claims delisted coverage; if verified (spot-check PXD/ATVI/TWTR/CELG), rebuild a monthly top-200-by-dollar-volume universe and re-run `xsec_refined` to *measure* our survivorship haircut instead of guessing it (literature suggests ~0.1-0.3 Sharpe inflation for large-cap momentum). One-off audit, 2-3 days, never a production dependency.

### 3.3 FRED via pandas-datareader — risk-free rate + auditable regime inputs
Free, stable daily series we cannot derive from OHLCV: DTB3 (correct risk-free for net Sharpe — expect the incumbent's 1.35 to print marginally lower, which is honest), VIXCLS, T10Y3M, BAMLH0A0HYM2 (HY OAS). Market-derived series are unrevised; enforce a 2-trading-day availability lag in the backtester. Any VIX/OAS-conditioned defensive trigger is a registered tournament hypothesis, not a freebie. ~0.5 day.

### 3.4 bt + ffn — second-paradigm verification engine
The firm's entire evidence base rests on one vectorized engine. bt's tree/algo-stack paradigm independently reproduces a promoted strategy's monthly target-weight schedule and diffs equity curves — catching rebalance off-by-ones, cost-application-order bugs, rounding, dividend handling. Run once per strategy promotion (before holdout unsealing) and once per engine change; assert cumulative tracking error < ~5bps/mo. Compare curves, not bt's summary stats. 1-2 days once, reusable forever.

### 3.5 quantstats (pinned v0.0.81) — tear-sheet reporting layer ★ REPORTS UPGRADE
One-call HTML tear sheets (~50 metrics, drawdown tables, rolling Sharpe, benchmark comparison) for research reports and adversarial-review artifacts. **Presentation layer ONLY:** documented metric bugs (#458 CAGR day-count, #480 benchmark inconsistencies, #499 import regressions) mean our audited engine remains the sole source of truth for all statistical gates — quantstats numbers are never used for GO/NO-GO. Validate once against our engine on 3 known equity curves; if diffs exceed rounding, restrict to plots. Pass benchmarks as pre-fetched Series to avoid its yfinance dependency. ~0.5 day.

### 3.6 Stooq — free third price source for triangulation
No-key CSV endpoints with split+dividend-adjusted option; quarterly reconciliation pulls (incumbent vs Tiingo vs Stooq majority vote isolates a bad feed) plus one-off delisting spot-audits. Grade C (informal terms, throttling); never a production dependency. Hours.

**Explicitly not adopting:** yfinance (ToS/stability — fails the legal-reachable bar for pipeline use), FMP free fundamentals (restated, not point-in-time — any factor backtested on it embeds lookahead), vectorbt OSS (frozen; paid PRO successor; same paradigm as our engine so it wouldn't catch our bug classes), zipline/backtrader/Lean migration (dead/frozen/cloud-tied; migration risk exceeds benefit at monthly cadence), pyfolio (abandoned), indicator libraries (multiple-testing surface, dependency risk), portfolio optimizers for a top-6 book (estimation error dominates below ~20 assets; DeMiguel 1/N), MlFinLab (relicensed closed-source — see Tier 4 for the open replacements).

### 3.7 SEC EDGAR Form 4 ingestion — unblocks 1.6

Free, authoritative, and filing-timestamped, which is the part that matters: building an insider signal off trade dates instead of filing dates is lookahead. Reachability verified 2026-08-07 from this environment — `data.sec.gov/submissions/CIK*.json` and the browse-edgar Atom feed both return 200 with a declared User-Agent (SEC requires a contact string; unattended jobs must set one or get blocked). Work: CIK map for the 227-name universe, Form 4 XML parse (non-derivative table, transaction code P/S, shares, price, filing datetime), routine-vs-opportunistic classification per CMP 2012, cached to `data/insider/`. Estimated 1-2 days. Do the breadth check in 1.6 *before* building the full pipeline.

---

## TIER 4 — Method Upgrades for the Gauntlet

Adoptable practices only, in recommended adoption order. All distribution-based machinery MUST run on daily strategy-return paths (~2,100 dev observations), never monthly aggregates (103 points cannot support it).

1. **CPCV + PBO/CSCV overfitting layer** (Bailey-Borwein-López de Prado-Zhu, JCF 2017; AFML chs. 11-12). Replace the single 4-fold walk-forward path with combinatorial purged CV (N=8 blocks choose k=2 → 28 synthetic OOS paths, purging/embargo at month-end boundaries): a *distribution* of net Sharpes per candidate plus a Probability of Backtest Overfitting across the tournament grid. Gate: median path Sharpe above threshold AND 5th-percentile path > 0; PBO < ~20%. Expect it to kill more candidates than the current gauntlet — that is the value — and to reveal whether 1.35 is path-lucky. **Licensing trap:** do NOT use MlFinLab (closed-source/paid since 2020); use `eslazarev/purged-cross-validation` or `skfolio.model_selection.CombinatorialPurgedCV` (BSD-3). Highest-priority adoption in this cycle.
2. **SPA / Reality Check / StepM family-wise testing on the trial registry** (White Econometrica 2000; Hansen JBES 2005; via Kevin Sheppard's `arch`). Bootstrap the actual daily return series of every registered trial jointly (stationary bootstrap, ~21d blocks) for a nonparametric family-wise p-value that a tournament winner beats the benchmark — an independent cross-check on deflated Sharpe that handles correlated trials properly (and a momentum-variant tournament's trials are highly correlated). Require SPA consistent p < 0.05 before any winner advances to holdout. ~1 day of glue code.
3. **Effective-number-of-trials correction + E[max SR] benchmark** (Bailey & López de Prado JPM 2014; MLAM 2020). Cluster the trial-return correlation matrix to estimate effective independent trials; plug into the existing DSR formula and benchmark the winner against the closed-form expected max Sharpe of that many null trials. Shifts thresholds by tens of percent when the tournament is momentum look-alikes (it is). ~100 lines.
4. **Fundamental Law / Transfer Coefficient intake calculator** (Grinold-Kahn; Clarke-de Silva-Thorley FAJ 2002). Operationalizes our "does the edge live in the short leg?" rule into arithmetic at backlog intake: expected long-only IR ≈ published IR × TC(~0.3-0.6 long-only) × sqrt(breadth ratio) − costs; auto-reject anything that lands below 1.35 before backtest code is written; auto-flag implausible implied ICs (>0.1 from daily OHLCV). Use to reject, never to accept.
5. **Carver cost speed limit + position buffering** (Systematic Trading, 2015). Per-strategy turnover ceiling: reject any candidate whose annualized cost drag exceeds ~1/3 of its conservative pre-cost Sharpe — a principled replacement for the blanket 12-20 rebalances/yr rule. Weight-level buffering (trade only positions drifted >10% from target) typically cuts rebalance count 30-50% at equal signal. Port the logic, not pysystemtrade's futures plumbing.
6. **CAR25 / bootstrap-drawdown retirement rule** (Bandy, grade C but fully specified). Fills a genuine gap: the gauntlet gates entry but has no live-strategy *exit* criterion. Stationary-bootstrap daily strategy returns → rolling CAR25 (25th-percentile compound return); hard rule: CAR25(2y) < 0 for 2 consecutive months → paper-only. Calibrate the threshold on momentum's known 2016-2024 drawdown profile first so a normal momentum drawdown doesn't whipsaw a sound strategy out. The rule itself is a trial — register it.
7. **Walk-forward matrix / WFE** (Tomasini-Jaekle; grade C, folklore thresholds) — cheap lucky-boundary detector (3×3 IS/OOS window grid, require verdict stability in >2/3 of cells); largely subsumed by CPCV, so adopt only as the fallback if CPCV integration stalls.
8. **CDaR-constrained defensive-sleeve weights** (Chekhlov-Uryasev-Zabarankin, IJTAF 2005; via Riskfolio-Lib or skfolio) — principled long-only tail-drawdown weights for the 25-ETF sleeve; lowest priority; expect adversarial pushback on concentration.
9. **Execution salvage (the only one worth anything at $250):** log live Robinhood fills vs decision prices to empirically validate the 5bps/side cost model. Everything else in the execution/microstructure literature is irrelevant at $40 clip sizes.

---

## REJECTED FAMILIES — do not re-litigate

This table exists so the weekly desk never re-opens a dead end. A family leaves this table only via new evidence of the specific kind named in its kill reason, presented to the head of research — not via re-reading the original paper.

| Family (catalog examples) | Kill code | One-line reason |
|---|---|---|
| Short-term reversal (daily/weekly; catalog SR 0.816) | frequency + short-leg | 10-50x the cost budget; edge concentrates in small caps and the short leg; monthly long-only large-cap version is ~zero signal |
| Overnight / close-to-open effects (equity SR 0.369; BTC 22:00-24:00 SR 0.892) | frequency-impossible | Requires a daily close-to-open round trip (~10bps/day drag vs ~3-4bps gross); BTC version costs ~470%/yr at 93bps/side |
| Betting Against Beta (SR 0.594) | leverage + short-leg-defined | The factor IS levered-long-low-beta vs short-high-beta; unlevered long-only collapses into the low-vol tilt already in Tier 1.2 |
| Earnings announcement premium (SR 0.192) | evidence-dead + data-unavailable | US premium documented dead post-2004 disclosure regulation (Heitz et al. 2020); historical announcement dates aren't in our data anyway |
| Earnings-announcement reversal (SR 0.785) | frequency + data + short-leg | Daily cadence, needs announcement-date history we lack, edge leans on the short/limit-order side — triple fail |
| Fundamental-data anomalies (asset growth 0.835, ROA, accruals, FSCORE, R&D, short interest, filings NLP, ESG momentum, mutual-fund momentum) | data-unavailable | No point-in-time fundamentals/text/short-interest history exists in our stack; scanner snapshots cannot backtest; several replicate negative anyway |
| Pairs trading / stat arb (stocks 0.634, country ETFs 0.257, WTI/Brent) | short-leg IS the edge | Market-neutral by construction; no long-only version exists |
| Volatility risk premium / dispersion (0.637 / 0.432) | venue-banned | Options positions; hard ban on execution and signals |
| Heston-Sadka same-month seasonality (SR 0.34) | statistically-untestable | ~9 same-month observations per name on 2016+ data; pure noise-fitting in a 4-fold walk-forward |
| Calendar one-shots (January Barometer 0.365, Payday 0.269) | deflated-Sharpe-kills-by-construction | 1-12 independent observations/yr; classic file-drawer survivors |
| Long-only ATR-stop trend on stocks (Wilcox-Crittenden, 0.569) | universe-mismatch + evidence-C | Payoff comes from thousands of small/mid-cap lottery tickets our top-200 universe removes; whipsaw turnover eats the budget in chop |
| Generic/consistent/style momentum variants (SR -0.008 to 0.128) | replication-dead + subsumed | Catalog's own replications at or below zero; the incumbent is already the tuned member of this family |
| Crude-oil-predicts-equities (0.599) | evidence-decayed + DSR-bait | Post-publication decay documented; one signal, one asset, ~12 obs/yr |
| FX carry / dollar carry / FX momentum & value | venue-banned | FX prohibited; replication Sharpes 0.25 to -0.10 anyway |
| Commodity futures cross-sectional (term structure, skewness, momentum) | short/roll-leg + venue | Long-short futures anomalies; long-only ETF versions lose the anomaly and keep the contango drag |
| Crypto cross-sectional rotation (Liu-Tsyvinski-Wu style) | breadth + short-leg + cost-impossible-at-93bps | Needs a wide altcoin universe, weekly cadence, and shorts; top-1-of-3 at 0.7-0.85 correlations has ~zero cross-sectional information |
| Crypto carry / funding-basis analogs | venue-banned + data-unavailable | Requires perp/futures access and funding-rate data; long-only spot cannot harvest basis |
| Crypto daily-cadence anything (rebalancing premium as published, reversal, calendar effects) | cost-impossible-at-93bps | 1.87% round trips vs bps-scale edges; monthly threshold-rebalance modification is the only surviving residue (Tier 2.10) |
| Unlevered "true" risk parity standalone | leverage-dependent | Without leverage the theorem doesn't deliver; 2022 showed the failure mode; inverse-vol weighting inside a sleeve is already absorbed |
| Smart-factor momentum (0.388), mutual-fund momentum (0.414) | universe/vehicle-unavailable | Factor-ETF sub-universe outside our 25; mutual funds untradable on venue |
| ML/DRL stacks as strategy source (FinRL, Qlib recipes, DQN bots) | sample-starved + irreproducible | 10y of daily bars vs model capacity; published results notoriously fail costs + walk-forward; our gates would correctly kill ~everything produced |
| Framework migrations, indicator zoos, tick-scale infra, broker APIs for venues we don't use | no-capability-gain | Adds bug surface, dependency risk, and multiple-testing surface; zero statistical power added (bt as verification harness is the one exception, adopted in Tier 3.4) |

**Crypto desk status:** remains NO-GO for return-seeking strategies. Ten years of daily crypto data contains only ~8-12 independent regime transitions — a long-flat trend system is statistically indistinguishable from buy-and-hold at our sample size, and trails B&H in bull-heavy holdouts by its flip costs. The Tier 2.10 gate is the *precondition* for any future exposure, not a strategy.

---

## Footer

**Nothing in this document skips the gauntlet.** Not the Tier 1 briefs, not the "free" feature experiments on the incumbent, not the method upgrades themselves (the CAR25 retirement rule and any vol-targeting overlay are registered trials like everything else). Every experiment — including A/Bs on `xsec_refined` — enters the trial registry before the first backtest runs and counts against the deflated-Sharpe budget. The sealed holdout is unsealed once, after the full gauntlet, or not at all. An idea graded A in this file is still just an idea.

---

## LIVE-DESK FINDINGS — queued for the next tournament

*Added 2026-08-05 from live operation, not from the source catalog. These are
questions the live book raised that research should settle with evidence.*

### L.1 Inverse-vol weighting concentrates violently in mixed-vol ranks ★ PRIORITY

`xsec_refined` weights by 1/volatility. When the top ranks contain both calm
names (banks: TD, RY) and volatile ones (semis: SNDK, MU), the calm names
collect a dominant share — a live re-rank on 2026-08-05 would have put
**52% in TD alone**, and a full rebuild **75% into two Canadian banks**,
funded by selling names ranked #2 and #3. Backtest history confirms the
pattern is intrinsic, not a one-off: median max single-name weight 25%, 90th
percentile 33%, max 45% (JNJ, 2026-05-13), with 8% of rebalances exceeding
the firm's declared 34% cap.

Two consequences worth testing, not asserting:
1. **Risk-mandate drift.** A max-risk momentum mandate silently becomes a
   majority-defensive book whenever low-vol names enter the ranks. Nobody
   chose that; the weighting scheme did.
2. **The cap now binds live** (implemented 2026-08-05 — it was declared in
   config and never enforced), which is a deliberate live-vs-research
   divergence: ~8% of historical rebalances would have been clipped. The
   attribution desk should expect small tracking error from this and NOT
   flag it as a defect.

Designer brief: A/B the weighting scheme on the tested chassis — inv_vol
(incumbent) vs equal-weight vs vol-scaled-with-floor (cap the inverse-vol
multiplier so no name exceeds ~2x the equal-weight share) vs explicit
cap-and-redistribute at 25/34/50%. Score on the standard eval, and report
max single-name weight and sector concentration alongside Sharpe — a variant
that matches incumbent Sharpe with materially lower concentration is a win
even at equal return. Pre-declared kill: if every capped variant loses more
than 0.15 Sharpe on dev, the concentration is load-bearing and the firm
should instead raise the declared cap to match reality rather than keep a
limit that fights the strategy.
