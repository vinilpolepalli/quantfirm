# KALSHI PERPS DESK — plan, evidence, verdict, and how the agents run it

**Status: PAPER + SHADOW, restarted 2026-09-18. `live: false`. Nothing trades
real money.** Built 2026-09-15 on
`claude/kalshi-perps-trading-agents-h0cvkh`. Venue facts in
`research/kalshi_perps/venue_dossier.md`; the evidence behind every design
choice in `research/kalshi_perps/evidence_review.md`; the numbers in
`research/kalshi_perps/tournament.md`, `holdout_trend_long_only.json` and
`rungs.json`. Code: `quantfirm/perps/`.

## 0. The answer in one page

You asked for a plan to use agents to trade Kalshi perps for consistent,
not-too-risky, considerable returns, and to test it. Here is what the
research and the tests say.

1. **Kalshi perps are real, regulated and cheap to hold.** Twenty contracts
   (BTC, ETH, 16 alts, gold, silver), CFTC-approved, cleared, 24/7, BTC
   spread under 1 bp, up to ~4.7x entry leverage on BTC and ~11.7x on gold.
   Funding was almost always exactly zero and **is no longer**, at least on
   BTC: across the whole history 55% of intervals are zero, but over the last
   90 only 24% are, and the non-zero ones are consistently positive. Averaged
   over every interval, zeros included — which is what holding through them
   costs — that is **+14.3% a year paid BY longs** if it persists. ETH is still
   89% zero, and pays longs only 1.5% a year once its zeros are counted in.
   §1a has the measurement and a correction to an earlier version of it. This is the exact condition §9 named as something that would
   change the verdict, and it arrived. Idle
   margin earns about 3.25% APY, and there are server-side stops. The costs
   that matter are the exchange fees: 12 bps taker / 5 bps maker at tier 0,
   charged on notional, on open and on close.
2. **There is no edge to harvest at retail size, and the evidence says an
   LLM must not place orders.** Funding carry is dead here by construction;
   market making, cross-venue arbitrage and intraday mean reversion lose to
   a 24–29 bps round trip; every real-money LLM trading experiment with
   published results lost or churned fees away (four of six frontier models
   lost 31–63% in 17 days in the only public perps contest). The agents'
   job is research, review and supervision. Code decides and executes.
3. **The firm's own gauntlet returned NO-GO for alpha, twice.** First
   thirteen pre-registered trend/momentum configurations, then a campaign in
   which ten agents each gave one strategy family its best shot: perp basis
   and funding as a crowding gauge, the options-implied variance risk
   premium, dual momentum, cross-sectional momentum, turn-of-month and
   weekend seasonality, weekly reversal, a macro-gated metals sleeve, a
   crash filter, EWMA trend strength, a meta-allocator, and Kalshi-native
   intraday microstructure. Twenty-two walk-forward trials on
   BTC/ETH/gold/silver, 2016–2025, with in-sample parameter selection per
   fold. **None beat the control.** Best was 1.100 against the control's
   1.131, and it is 0.996-correlated with the control. Deflated Sharpe 0.824
   against a bar of 0.95 at 113 registered trials; probability of backtest
   overfitting 0.586 against a bar of 0.10. The coin-flip control loses
   money. §3 has the table; `research/kalshi_perps/CAMPAIGN_RESULTS.md` has
   the campaign.
4. **More assets do not help, and that was measured, not assumed.** The
   obvious objection to the first two rounds was that they tested only four
   assets. Kalshi lists 23 perps, so the desk was extended to all of them.
   By the measure that maps to a long-only book's Sharpe, sixteen names carry
   1.98 effective independent bets against the four researched assets' 2.03 —
   slightly fewer, not more, at a mean pairwise crypto correlation of 0.594.
   Ten of those sixteen lost money over 2021–25. Correctly sized and actually
   held, the passive wide book earns 12.0% a year against 18.0% at the same
   risk and the same drawdown, with a paired bootstrap putting P(wide better)
   at 0.142. Ranking the cross-section by
   trailing return produces no t-statistic above 0.52 at any horizon, gross of
   costs, and adding a short side gives 0.86 at a 30-day lookback and −0.03 at
   90 days, which is noise across a parameter. §3c.
5. **One thing did finally beat the book, and it is a sleeve, not a
   replacement.** Everything above failed for the same reason: every candidate
   was the long book in a hat, correlated 0.68 to 0.996 with the thing it was
   meant to beat, and an overlay that correlated cannot raise portfolio Sharpe
   however it scores. Strip each coin's beta to the crypto market before
   ranking the cross-section and the sort stops being directional: residual
   correlation among the names averages −0.08 where the raw correlation
   averages 0.594. That sleeve is **−0.156 correlated** with the long book, and
   blended at 30% it takes the book out-of-sample from Sharpe 1.255 to **1.694
   at the same 15.2% return**, with volatility down from 12.3% to 9.0% and
   drawdown from −10.1% to −8.6%. It survives 1.5× fees and proxy funding, and
   its timing-null percentile is 0.983, meaning the returns come from when it
   holds its positions rather than from the exposure it carries. It still
   **fails** the deflated-Sharpe gate at 0.695 against 0.95, because 1,119
   out-of-sample days need a Sharpe of 2.33 to clear that bar and the names did
   not exist before 2021-10. So it goes to paper beside the incumbent, not into
   production. §3d.
6. **What is deployable today is beta, sized by volatility, with a trend gate
   as drawdown insurance.** That is not alpha; it is a bet that BTC/ETH/gold/
   silver keep drifting up, made cheaply. Measured 2018–2025 with tier-0
   taker fees: vol-targeted long-only earned 13–20% a year with 15–32%
   drawdowns and lost money in 2018 and 2022; the same book behind a trend
   gate earned 9–14% a year with 6–12% drawdowns and no losing year, at the
   cost of ~4 points of return. On the sealed holdout (2025-07-01 → today,
   opened once), the gated book made +23.7% at a −4.9% drawdown versus
   +27.1% at −11.6% for the ungated one.
7. **"Consistent" means 61–72% positive months and about 77% positive
   quarters, not every month.** "Considerable" at $250 is about $25 a year.
   The owner starts at $250 and scales. Whole-contract simulation at $250
   (`research/kalshi_perps/granularity.json`) costs the incumbent 0.05 of
   Sharpe and half a point of CAGR against fractional sizing, with identical
   drawdowns, because ETH, gold and silver contracts are $2–6 each; only BTC
   (~$8) is lumpy. So $250 works as a canary size; the scaling ladder is in
   §7. Nothing here is a promise: the histories are proxies (Coinbase spot,
   Yahoo futures) because Kalshi's own perps are three months old and its
   gold/silver perps five days old.

The plan therefore has two parts: a **research process** that keeps trying
to find an edge under the same gauntlet (and keeps saying no until one
passes), and a **shadow book** that runs the gated-beta posture in paper
with the full production control stack, so that if the owner chooses to
fund it, it goes live as a measured posture rather than a hope.

## 1. The instrument (what you are actually trading)

| Fact | Value | Source |
|---|---|---|
| Contracts | BTC 0.0001 BTC (~$7.8), ETH 0.001, SOL 0.1, XRP 1, gold 0.001 oz (~$4.3), silver 0.1 oz (~$6.3); tick $0.0001; whole contracts | `GET /margin/markets`, 2026-09-14 |
| Maintenance margin (≈ 1 / published leverage at $1k) | BTC 16.5%, ETH 21.5%, SOL 33%, XRP 36%, gold 6.6%, silver 12.8% | same |
| Initial margin | 1.3 × maintenance → max entry leverage BTC 4.65x, ETH 3.6x, gold 11.7x | `GET /margin/risk_parameters` |
| Liquidation | margin ratio (maintenance / equity) 1.0; queue at 0.91; Klear market orders; deficit → default-fund waterfall | risk params + help center |
| Funding | crypto 3×/day (00/08/16 ET), metals 1×/day (10:00 ET, weekdays); deadband 0.01% (crypto) / 0.002% (metals); cap ±2%; no interest term | filed T&C, funding history |
| Realized funding since June | BTC +7.9%/yr mean but 55% zero; ETH −1.8%; alts ≈ 0 to −5%; Sept BTC +14.8% annualized | `GET /margin/funding_rates/historical` |
| Fees (tier 0) | taker 12 bps, maker 5 bps of notional, open and close; tier 1 (≥$100k/30d) 10/4 | CFTC filing 2026-06-24 |
| Collateral yield | ~3.25% APY on idle margin, subject to change | help center |
| Liquidity | BTC/ETH spread 0.3–0.5 bps, >$1M within 5 bps; gold 0.5 bps; silver 1.6–4 bps; platform $1.2B/day, OI $25–30M | orderbook pulls 2026-09-15 |
| Hours | 24/7; Thursday 03:00–05:00 ET maintenance (no new orders, marks frozen, liquidations paused) | docs |
| Account limit | default ~$5,000 notional per market on new accounts | `GET /margin/notional_risk_limit` |
| Access | US residents, KYC, separate margin application + tutorial, separate margin balance; dedicated API key recommended | help center |
| Regulatory risk | CME v. CFTC (filed 2026-06-18) argues perps are swaps; motion to dismiss pending | court filings |

Two consequences drive everything below. First, holding is nearly free:
zero funding most of the time plus interest on collateral means a slow
book pays only its fees, about 0.4–0.8% of equity a year at the turnover
measured here. Second, the venue's leverage is irrelevant: at 1x notional a
long can never be liquidated (price would have to reach zero), at 2x a 40%
adverse move liquidates BTC, and every published number on retail perps
says anything above ~2x is a coin flip over a quarter. The risk policy caps
gross leverage at 1.0–2.0x by rung.

## 0. PAPER RESTARTED — 2026-09-18

The owner halted perps on 2026-09-16 (not a risk event; nothing was live).
On 2026-09-18 they asked to paper the measured books — or backtest the one
we found — **before** transferring the $257. Paper first is the right
order. A pile of new internet systems is not; that catalog is the set
§2 already killed, and more registered trials raise the deflated-Sharpe
bar. The backtests that matter are already on disk. Do not re-run
`cli backtest` / `cli holdout` for a demo.

Three of the four halt layers are undone in this commit. Claude Routines
(daily digest, 4-hourly alert, weekly watch) are not files in this repo
and stay a human action. GitHub cron is the durable heartbeat.

| layer | state |
|---|---|
| `state/KILL_SWITCH_PERPS` | **removed** — paper ticks may trade again |
| `config/perps.json` | `status: PAPER`, `live: false` |
| `.github/workflows/perps.yml` | daily `schedule:` on at 01:20 UTC |
| routines (daily digest, 4-hourly alert, weekly watch) | still a Claude-side enable; not flipped here |

**The paper positions stay the frozen legs, not a wiped $250.** Paper
state is gitignored, so the engine now hydrates a missing local book
from the committed desk status. The books resume from:

| book | equity at halt | legs |
|---|---:|---:|
| incumbent | $249.75 | 1 (eth) |
| candidate | $249.92 | 8 |
| growth | $249.83 | 11 |

All three within a quarter of a percent of their $250 start after two days,
which means nothing in either direction — two days is not a result. A
reading takes weeks. The $257 stays in predictions until the owner moves
it. None of this promotes anything to live; the gate in §7 is unchanged
and was never met.

## 1a. Funding went live on BTC, and the desk noticed

Measured 2026-09-15 from Kalshi's own `funding_rates/historical`, which is what
both the backtester and the paper engine read:

| market | intervals | zero, all history | zero, last 90 | median when non-zero | **cost of holding** | cost when it charges |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 311 | 55.0% | **24.4%** | +0.0162% | **+14.3%/yr, paid by longs** | +17.8%/yr |
| ETH | 311 | 87.1% | 88.9% | −0.0118% | −1.5%/yr, received by longs | −13.0%/yr |
| gold | 4 | 50.0% | — | +0.0316% | too little history to read | — |
| silver | 4 | 75.0% | — | +0.0292% | too little history to read | — |

> **Correction, 2026-09-15.** The first version of this table gave BTC as
> +16.3%/yr and ETH as −13.6%/yr. Both were wrong in the same way: they
> annualised the median of the *charging* intervals and labelled it the cost of
> holding. A holder sits through the zero intervals too, so the cost of holding
> is the mean over **every** interval, zeros included. The two differ by the
> reciprocal of the live share, which is trivial on a market that always charges
> and an order of magnitude on one that rarely does. The error was largest
> exactly where it mattered most: it said a long ETH book is paid 13.6% a year
> when it is in fact paid 1.5%. Both conventions are now reported side by side,
> and `tests/test_perps_watch.py` pins the distinction.

BTC's last eight intervals read 0, +0.0118%, +0.0143%, +0.0173%, +0.0149%,
+0.0147%, 0, 0. That is not noise around a deadband; that is a market paying
carry most of the time.

**What it changes.** The claim that holding is free on this venue, which is a
large part of why the book rebalances weekly rather than daily (§3e), is now
half wrong: holding BTC long costs about 14% a year at these rates, while
holding ETH long still pays, though only just. It does not change the cadence
conclusion — trading more often would add cost without removing this one — but
it does mean a long BTC book's forward expectation is worse than the dev-window
backtests assumed, since Kalshi funding did not exist before 2026-06 and those
runs booked zero.

**What it does not change.** The desk already stress-tests against real funding:
the `proxy` scenario applies Binance's funding through Kalshi's deadband, and
the residual-momentum blend survives it at Sharpe 1.532 against the core's
1.154 (§3d). So the case was tested before it arrived, and the sleeve's
advantage widened rather than narrowed under it.

**What it opens.** §9 listed a funding-conditional overlay as one of the few
things that would be worth a new registered trial if Kalshi's own funding
persisted above the deadband. It now has for three months on BTC. That is a
genuine research opening, and the first one the desk has had since the campaign
closed. It is NOT taken here: one instrument with ninety intervals is a thin
basis, and the honest move is to let `scripts/perps_watch.py` keep measuring it
weekly until there is enough history to pre-register a test against. The watch
reports a **change**, not a state, so this finding is emailed once and then
lives here; the next email about funding means the picture moved again.

## 2. What the evidence rules out, and why

| Idea | Verdict | Reason (details and citations in `evidence_review.md`) |
|---|---|---|
| LLM decides entries, sizes, leverage | **out** | Alpha Arena S1: 4/6 lost 31–63%; S1.5: a third of $320k lost, 1,418 trades in a round; gated vs ungated agent drawdown 3% vs 46%; nof1: "that path doesn't work yet". Re-checked 2026-09-18 when the owner asked for a research-agent long/short: still out. `research/kalshi_perps/RESEARCH_AGENT_DISCRETION.md`. |
| Funding carry | **out on Kalshi** | deadband zeroes most intervals; collateral already earns 3.25%; 2026 basis below T-bills Feb–Jul everywhere |
| Cross-venue funding/basis arb | **out** | needs an offshore short a US retail account cannot hold; 95% forced exits in the one large-sample study; two taker fees exceed the spread |
| Market making / fast mean reversion | **out** | no rebates below 0.5% of venue maker volume; adverse selection; GSR quotes these books |
| Intraday / multi-hour signals, grid bots | **out** | 20 round trips a month at 12 bps and 2x is a 115%/yr fee hurdle |
| Long-tail alt perps | **tested, out** | measured: sixteen names carry 1.98 effective bets against four assets' 2.03; ten of sixteen lost money 2021–25; the wide book earns 12.0% a year against 18.0% at the same risk (§3c) |
| Perp basis / funding as a crowding gauge | **tested, out** | OOS Sharpe 1.100 vs 1.131; 0.996 correlated with the passive book; the BIS crash-after-high-carry pattern does not reproduce at a daily horizon on six episodes |
| Options-implied variance risk premium (Deribit DVOL) | **tested, out** | OOS 1.099; the tilt is the passive book with 0.29/yr more turnover, lower CAGR and a deeper drawdown |
| Dual momentum, absolute + relative | **tested, out** | OOS 1.047 with the skip month; real timing content (null percentile 0.93) but it trails the passive book and collapses to 0.40 at a 274-day lookback |
| Turn-of-month / weekend seasonality | **tested, out** | OOS 1.026 and 0.958; fees are 24–63% of the gap to the control |
| Cross-sectional momentum on four assets | **tested, out** | OOS 0.154 long/short, 0.578 long-only; four correlated assets are not a cross-section |
| Macro-gated metals (DXY, real yields, VIX) | **tested, out** | OOS 0.881; the metals sleeve alone earned less than the 3.25% collateral yield |
| Drawdown / vol crash filter | **tested, out** | OOS 1.011; the configuration that works was chosen with hindsight, and the walk-forward picked the ones that ride the 2022 legs |
| Kalshi-native intraday microstructure | **tested, out** | no effect above 2× round-trip cost across ~30 cells; largest gross effect 6.8 bps against a 49 bps hurdle |
| Gold–silver ratio mean reversion | **tested, out** | OOS Sharpe −0.80 here; no verifiable evidence elsewhere; double fees |
| Long/short trend on majors | **tested, weak** | OOS Sharpe 0.4–0.5, 3–5 of 6 folds positive; the short side has not paid on these assets |
| Slow trend gate on a vol-targeted long book | **tested, the incumbent** | OOS Sharpe 0.80, 6/6 folds positive, drawdown halved vs beta; does not beat beta on Sharpe |
| Vol-targeted long-only beta | **tested, the benchmark** | OOS Sharpe 1.13 but −18% drawdowns and losing years; this is the bet, not an edge |

## 3. The tournament (how the plan was tested)

Protocol (`quantfirm/perps/tournament.py`, mirrors `docs/FIRM.md` §2):

* Universe BTC, ETH, gold, silver. Daily bars. DEV window 2016-06-01 →
  2025-06-30; HOLDOUT from 2025-07-01, sealed from every research command
  and opened once by the judge with `cli holdout --i-am-the-judge`, which
  records the opening.
* Costs: taker tier 0 (12 bps) + 2.5 bps half-spread per side, weekly
  rebalance check with a 3% band, execution at the next day's open, funding
  from Kalshi's own history (≈0) with Binance funding through Kalshi's
  deadband as the stress case, 3.25% interest on unencumbered collateral,
  liquidation checked on every day's intraday extremes with all positions
  marked at their worst point at once.
* Thirteen registered trials (four TSMOM lookback sets, three MA pairs,
  three breakout channels, the ensemble, its long-only variant, the ratio
  idea). Walk-forward: six folds from 2018 to 2025; the grid point with the
  best in-sample Sharpe strictly before each fold is scored on that fold
  only. Sharpe is on excess return over the collateral yield so an idle
  book scores zero.
* Gates: beat the benchmark out of sample, ≥4/6 folds positive, OOS
  drawdown ≤25%, no liquidations, positive under 1.5× fees + proxy funding,
  deflated Sharpe ≥0.95 against 13 trials, CSCV PBO ≤0.10.

Result (`research/kalshi_perps/tournament.md`, run 2026-09-15):

| family | OOS Sharpe | OOS CAGR | OOS max DD | folds + | stress SR | DSR | gates |
|---|---:|---:|---:|---:|---:|---:|---|
| vol_target_hold (benchmark) | 1.13 | 18.2% | −18.4% | 6/6 | — | — | control |
| trend_long_only | 0.80 | 9.8% | −12.5% | 6/6 | 1.25 | 0.66 | FAIL: benchmark, DSR, PBO |
| breakout | 0.46 | 7.2% | −13.3% | 5/6 | 0.56 | 0.31 | FAIL |
| tsmom | 0.45 | 7.2% | −13.3% | 5/6 | 0.80 | 0.30 | FAIL |
| ma_trend | 0.42 | 7.4% | −21.1% | 3/6 | 0.89 | 0.27 | FAIL |
| trend_ensemble | 0.38 | 6.5% | −15.5% | 5/6 | 0.79 | 0.23 | FAIL |
| gold_silver_ratio | −0.80 | 1.9% | −2.6% | 6/6 | −0.77 | 0.00 | FAIL |
| coin_flip (control) | −1.03 | −7.4% | −56.9% | — | — | — | control |

PBO across the 14 configurations = 0.30. **Every family scores 0 under the
firm's rule.** This is the gauntlet working: the same machinery said NO-GO
on the crypto spot desk and on the strict alpha gate for equities.

Holdout, opened once for the paper incumbent (`trend_long_only`, 12% vol
target), 2025-07-01 → 2026-09-15:

| | Sharpe | total | CAGR | max DD | positive months | avg gross |
|---|---:|---:|---:|---:|---:|---:|
| trend_long_only | 1.58 | +23.7% | 19.2% | −4.9% | 87% | 0.22 |
| vol_target_hold (benchmark) | 1.35 | +27.1% | 21.9% | −11.6% | 73% | 0.41 |

Fourteen months in which BTC fell about a third from its 2025 high and gold
rose about 30%: the gate held its BTC exposure near zero from March 2026 and
the book flat-lined at +0.0 to +0.3% a month while the ungated book gave
back more. That is exactly the shape the evidence review predicted
("drawdown mitigation, not monthly consistency") and it is one sample.

## 3b. The campaign (ten agents, one family each)

The first tournament tested one idea — trend — in several dresses. The
campaign tested twelve ideas. Ten agents each took one strategy family under
a written protocol (`research/kalshi_perps/CAMPAIGN.md`): state the
hypothesis, the mechanism and the external evidence, declare a grid of at
most six configurations **before** the first backtest, run on the DEV window
only, and report the numbers the tools printed including the bad folds. Every
run appends to an append-only trial registry, so each new idea raises the
deflated-Sharpe bar for every other idea. The referee ran the joint
tournament, the overfitting tests and the robustness checks; nobody promoted
their own work.

| rank | family | the idea | OOS Sharpe | folds + | DSR |
|---:|---|---|---:|---:|---:|
| — | `vol_target_hold` | the control: passive, equal-risk, vol-targeted long book | **1.131** | 6/6 | — |
| 1 | `basis_crowding` | cut the majors when perp basis and funding say longs are crowded | 1.100 | 5/6 | 0.824 |
| 2 | `vrp_options` | scale crypto by the Deribit DVOL variance risk premium | 1.099 | 6/6 | 0.823 |
| 3 | `dual_momentum_skip` | 12-1 month absolute momentum per bloc, relative tilt | 1.047 | 6/6 | 0.784 |
| 4 | `trend_v2_tsmom` | 12-month trend sign at a monthly cadence | 1.031 | 6/6 | 0.769 |
| 5 | `rs_turn_of_month` | half weight over month-end | 1.026 | 4/6 | 0.768 |
| 7 | `crash_filter_beta` | cut on drawdown-from-high and volatility spikes | 1.011 | 5/6 | 0.751 |
| 10 | `allocator_blend` | meta-allocator over the control and the incumbent | 0.911 | 5/6 | 0.661 |
| 12 | `macro_gold` | metals sleeve gated on the dollar and real yields | 0.881 | 4/6 | 0.631 |
| 13 | `xsec_momentum` | cross-sectional momentum on four assets | 0.876 | 5/6 | 0.628 |
| 15 | `trend_long_only` | the incumbent | 0.798 | 6/6 | 0.544 |
| 21 | `rs_bollinger_mr` | Bollinger mean reversion | 0.358 | 6/6 | 0.140 |

Twenty-two trials in all; the full table is in
`research/kalshi_perps/CAMPAIGN_RESULTS.md`. **Nothing passed.** The bar was
a deflated Sharpe of 0.95 against 113 registered trials and a probability of
backtest overfitting of 0.10; the best trial reached 0.824 and the PBO across
all 62 walk-forward configurations was 0.586.

Three things the campaign settled, which are worth more than another
backtest:

* **Every gate gives back more than it saves.** On a paired block bootstrap
  against the control, every overlay — trend, dual momentum, macro, crash
  filter, basis — has a probability between 0.13 and 0.36 of being the better
  book. They miss more of the rallies than they save in the 2018 and 2022
  bear legs.
* **Overlays that read a new series add no information at a daily horizon.**
  Options-implied volatility, perp basis, funding, the dollar, real yields,
  the VIX: each tilt comes out either 0.87–0.996 correlated with the control
  or worse than it.
* **Multiple testing is now the binding constraint.** The registry holds 79
  distinct configurations in 225 rows. On this history a candidate needs an
  out-of-sample Sharpe near 1.4 to clear the deflated-Sharpe bar, while the
  expected best of 113 null trials is about 0.76. The honest consequence: the
  desk should run few, well-motivated tests, not many.

One caveat on how this campaign ran: seven of the ten agents were terminated
mid-run when the account hit its monthly spend limit. Two families have code
and registry rows but no written report, and the planned adversarial round
was not spawned; the referee ran those robustness checks instead. That cut
the campaign's breadth, not its verdict — the tournament, the deflated Sharpe
and the overfitting test all ran over every registered configuration.

## 3c. Breadth, and why twenty assets are the same bet as four

Round 1's post-mortem blamed the universe: four assets at 0.9 correlation are
two bets, not four, so nothing cross-sectional was testable and the
cross-sectional family duly scored 0.154. Kalshi lists 23 perps and every one
has a spot proxy going back years, so the desk was extended to all of them —
specs, data, per-asset spreads, and a backtester that holds each asset only
while it is actually listed. Then the premise was measured, and it is false.

**Twenty names are 2.5 bets.**

| universe | effective independent bets |
|---|---:|
| btc, eth, gold, silver | 2.44 |
| all 18 crypto names with usable history | 2.51 |

Mean pairwise correlation among the crypto names is 0.589. Fourteen extra
coins buy seven hundredths of one independent bet, because they are the same
trade wearing different tickers.

**The alts were a drag.** Over 2021-10 to 2025-07, eleven of seventeen names
lost money. Gold returned 16.8% a year at a 1.09 Sharpe and XRP 101.6% at
0.95; below them everything sits at 0.43 or worse, down to ADA at −36.6% a
year and ZEC at −29.4%.

**Correctly sized, the wide book is indistinguishable, and earns a third as
much.** An earlier version of this section reported the wide book at Sharpe
0.49 and called the gap economic; those runs used the narrow sizing path,
whose 5% weight step rounds a twenty-asset book's weights to zero. With the
wide sizing path the numbers are:

| window | universe | Sharpe | CAGR | max DD | excess vol |
|---|---|---:|---:|---:|---:|
| 2018-01 → | 4 researched | 0.940 | 15.45% | −21.15% | 12.68% |
| | 20 tradable | 0.835 | 9.59% | −12.40% | 7.41% |
| 2021-10 → | 4 researched | 1.161 | 18.04% | −15.55% | 12.12% |
| | 20 tradable | 1.188 | 6.70% | −2.42% | 2.76% |

A paired block bootstrap puts P(wide beats narrow) at 0.300 on the long window
and 0.556 on the short one: the same bet, not a better one. The return gap is
the story. The wide book realises 2.76% of volatility against a 12% target,
because alt maintenance margin runs from 26% on LTC to 59% on WLD against
gold's 6.6%, and the liquidation-distance rule caps each name by its own
maintenance rate. The alts cannot be held in size on this venue at any
sensible risk target, so most of the wide book sits in collateral at 3.25%.

An independent analysis adds the finding that decides it: in a vol-matched
replica the wide book's whole advantage is a rebalancing return — a
daily-rebalanced equal-weight alt basket returned +26.6% while nine of eleven
alts lost money and the average buy-and-hold was −12.7% — and substituting one
dead-alt path for one of the eleven drops it below the narrow benchmark. That
is precisely the quantity survivorship manufactures.

**Nor is the cross-section worth trading.** Ranking every available name by
trailing return and holding the top quartile against the bottom, gross of all
costs, produces no t-statistic above 0.52 at any formation or holding horizon,
with the sign flipping between horizons and hit rates at the coin flip.
Time-series trend with a short side — the one thing four assets could never
test, because there was nothing worth shorting — scores 0.86 at a 30-day
lookback and −0.03 at 90 days in the same universe. That is noise across a
parameter, not a signal, and the short side is negative at every long lookback
because the alts fell through rallies that whipsaw anything systematic. All of
these numbers are gross, against a benchmark whose 0.94 is net.

So no wide-universe family was registered. Ten configurations that a free
screen already shows to be empty would raise the deflated-Sharpe bar for every
future idea and buy nothing. The full measurement is in
`research/kalshi_perps/BREADTH_FINDING.md`.

The infrastructure was still worth building: the desk can now price, size and
simulate any of the 20 tradable perps with each one's own spread and
maintenance rate, which is what any future idea on this venue will need. And
the answer to "would more assets have helped?" is now measured rather than
assumed.

## 3d. The one thing that worked: a sleeve, not a replacement

Round 2's screens killed raw cross-sectional momentum at every formation from
30 to 365 days. That turned out to be the right answer to the wrong question.
On a universe whose first principal component is two thirds of the variance, a
raw return sort **is a beta sort** — it buys the high-beta alts after the
market rises — which is why round 1's version correlated 0.745 with the long
book. And the horizons screened were the ones the literature reports dead:
Borri, Liu, Tsyvinski & Wu (2026) find crypto cross-sectional momentum at a
**two-week** formation with a weekly hold, and report 12-week and 24-week
momentum insignificant.

Strip each name's beta to the equal-weight crypto market, rank the residual
over 14 days, go long the top three and short the bottom three, inverse-vol
within each leg, seven overlapping weekly tranches. Two grid points were
registered before the first run and the lookback was not swept.

| | out-of-sample, 2021-10 → 2025-06 |
|---|---|
| sleeve standalone Sharpe | 1.028, 4/4 folds positive |
| correlation to the long book | **−0.156** |
| core book (4 assets, vol-targeted long) | Sharpe 1.255, 15.37% return, −10.12% drawdown |
| **core + 30% sleeve** | **Sharpe 1.694, 15.22% return, −8.64% drawdown** |
| P(blend beats core), paired bootstrap | 0.947 |
| under 1.5× fees and proxy funding | blend 1.532 against core 1.154 |
| timing-null percentile | **0.983** (null mean −0.368) |

The same return at three quarters of the volatility. Every blend weight from
20% to 60% beats the core, so the result does not balance on the weight. The
fold detail shows the mechanism plainly: the sleeve scored 1.252 in the fold
where the long book earned 0.092, and the long book scored 1.872 in the fold
where the sleeve faded to 0.669. They fail at different times, which is the
entire point of a sleeve and is what nothing in round 1 offered.

**It fails the gauntlet anyway, and that is recorded rather than argued away.**
The deflated Sharpe is 0.695 against a bar of 0.95: at 82 registered
configurations a 1,119-day out-of-sample stream needs an annual Sharpe of 2.33,
and the blend measures 1.694. That is a window-length failure — most of these
coins had not listed before 2021-10 — and it cannot be fixed except by waiting.

It also fails `beats_benchmark_oos` as that gate is written, because the gate
compares a candidate's *standalone* Sharpe (1.028) against the benchmark's
(1.255). That is the right comparison for an overlay 0.9-correlated with the
long book, which is what every round-1 candidate was, and the wrong one for a
sleeve at −0.156: a 1.03-Sharpe sleeve that lifts the book to 1.694 and cuts
its drawdown is worth more than a 1.10-Sharpe overlay that is 0.996-correlated
with the thing it is supposed to improve. **The gauntlet needs a
portfolio-level gate** — blended Sharpe against the benchmark, with the
candidate's correlation to the long book reported as a headline number rather
than a robustness footnote. That is a protocol change, recorded here as one.

Reservations, in full: three years and four folds is one regime; the effect is
well published and therefore likely crowded; turnover runs 13 to 19 a year on
names whose round trip is 29 to 43 basis points; the twenty names are the set
Kalshi lists today, so survivorship is present in both legs; and nothing in
the data picks 30% over 40% as the weight. At $250 the sleeve is implementable
— about $12 of notional per leg against contracts costing $0.21 to $11.57 —
but quantisation dominates, and the trustworthy numbers are the large-bankroll
ones. `research/kalshi_perps/families/xsmom_residual.md` has the detail.

## 3e. Why the book trades weekly

A reasonable question, since a perpetual future sounds like an instrument you
watch minute by minute. The cadence was chosen before any results, on the
venue's own arithmetic, and the instrument is the reason.

**On Kalshi, holding is free and trading is not.** Offshore perps pay funding
three times a day, which is a standing reason to manage a position actively.
Kalshi's deadband rounds any rate under 0.01% per interval to zero. That was
true of 55–97% of intervals across the venue's whole history, and it is
**no longer true of BTC**: over the last 90 intervals only 24% were zero and
the rest were positive, which longs pay — about 14% a year once the remaining
zeros are averaged in (§1a). Carry is therefore not free on BTC any more,
though it is still close to free on ETH, and idle collateral still earns
about 3.25%. Meanwhile every trade costs 12
bps of fee plus the spread: about 24 bps round trip on BTC and 43 on LINK. The
venue therefore pays you to sit still and charges you to move, which is the
opposite of the instrument's reputation.

**The signals are slow.** The sleeve ranks a 14-day residual; the trend gate
reads multi-month moves. Neither carries information that decays in hours, so
rebalancing faster re-expresses the same view at full cost.

Measured out of sample, 2021-10 → 2025-06, the 30% blend by cadence:

| rebalance | blend Sharpe | ann. return | max DD | sleeve alone | turnover |
|---|---:|---:|---:|---:|---:|
| daily | 1.625 | 14.44% | −8.59% | 0.730 | 18.6 |
| every 2 days | 1.675 | 14.91% | −8.64% | 0.834 | 17.9 |
| every 3 days | 1.611 | 14.37% | −8.53% | 0.773 | 17.3 |
| **weekly** | **1.694** | **15.22%** | −8.64% | 1.028 | 15.7 |
| fortnightly | 1.507 | 13.80% | −8.36% | 0.646 | 13.8 |
| monthly | 1.298 | 11.54% | −8.95% | 0.180 | 9.7 |

Read this as a shape, not a ranking. Everything from daily to weekly sits in a
band of 1.61 to 1.69, and the surface is not monotone — three days scores below
two. That is noise across a parameter. What the data does say clearly is that
past a fortnight the edge decays, sharply by a month, because a 14-day signal
held for thirty days is mostly stale.

**Weekly is therefore not a tuned optimum and must not be treated as one.**
It was picked a priori on cost grounds, it lands in the flat region, and the
measurement does not contradict it. Switching to whichever cadence topped this
table would be exactly the in-sample selection the whole gauntlet exists to
prevent, so nothing was changed on the strength of it. These six runs were
diagnostics executed directly rather than through the CLI, so they added no
rows to the trial registry and no deflated-Sharpe burden to future ideas.

One consequence worth knowing: the sleeve runs seven overlapping weekly
tranches, so roughly a seventh of it comes up for review each day even though
any single position is held about six weeks. The book's median gap between
trading days is exactly 7 and its median holding period is 42 days.

## 4. The agents (who does what, and what none of them may do)

Deterministic code makes every buy and sell. The language models research,
review, and supervise, and interact with the book only through git. This is
the firm's standing rule and the perps evidence makes it non-negotiable.

| Desk | Runs as | Cadence | May | May not |
|---|---|---|---|---|
| **Owner** (human) | you | as needed | hold the API key, fund the margin account, flip `live`, remove a kill switch, approve capital ramps, merge PRs | — |
| **Research desk** (LLM) | Claude Routine on a fresh clone, no keys | weekly | propose strategies, parameters, universe changes as PRs; extend `TRIALS` (version bump = new tournament); run `cli tournament`; write post-mortems | touch `config/perps.json`, `risk.py`, `state/`, or any key |
| **Referee** (LLM or human) | PR-triggered | per candidate | run `cli holdout --i-am-the-judge` once per family, check the seven gates, recommend PAPER → CANARY | merge; re-open a holdout (a second look is a new trial and is recorded as one) |
| **Risk desk** (LLM) | Claude Routine, read-only key or none | daily + on alert | read `state/perps_desk_status.json`, `GET /margin/risk`, the decisions log; trip `state/KILL_SWITCH_PERPS` by commit; page the owner | loosen a limit, re-enable trading, size a trade |
| **Execution engine** (code) | `scripts/perps_loop.sh` → `quantfirm.perps.cli agent` on a host you control | hourly tick, weekly rebalance | compute targets, run the pre-trade gate, send IOC limits inside the price band, reduce-only exits, keep a server-side stop under every position | anything a gate refused; anything while the kill switch exists |
| **Ops / reconciliation** (code, inside the tick) | same process | every tick | compare venue positions to the book, halt on mismatch, accrue funding and interest from venue data | "correct" a mismatch by trading |
| **Attribution** (code + LLM) | daily job | daily | compare realized P&L, fees, funding, slippage and turnover to the backtest's expectation; flag divergence | change parameters |
| **Data** (code) | `cli update-data`, GitHub workflow | daily 01:20 UTC | refresh daily bars, Kalshi funding and candles; stamp `META.json` | — |

Loops and where they live:

| loop | where | why there |
|---|---|---|
| hourly tick + weekly rebalance | daemon on a VPS (`perps_loop.sh`, watchdog on the decisions file) | GitHub cron can be delayed hours or dropped; Routines have a 1-hour floor; a leveraged book needs a host you control |
| daily shadow heartbeat | `.github/workflows/perps.yml` | research signal only; commits `state/perps_desk_status.json` |
| daily data refresh | same workflow + the daemon at session start | public data, idempotent |
| weekly research, daily risk read, monthly capital review | Claude Routines | judgement work, no order authority |
| dead-man's switch | external monitor (Healthchecks.io / Uptime Kuma) pinged by the daemon | the thing that notices silence must live elsewhere |

Controls in the order path (`quantfirm/perps/risk.py`, `paper.py`):
kill-switch file; venue status (`trading_active`); data age ≤ 30h; per-order
notional cap; price collar ±0.5% of the venue mark; per-tick order count;
gross and per-asset leverage caps; liquidation distance ≥ 35% (30% growth
rung) computed from the venue's maintenance rates; margin ratio ≤ 0.5;
daily and weekly loss stops; drawdown ladder (halve at −8%, flatten and
trip the kill switch at −15%); `reduce_only` on every risk-reducing order;
a bracket stop 20% away under every venue position; idempotent
`client_order_id`; a timeout on `create_order` never retries (a lost
response is an IN-DOUBT halt, not a second order); reconciliation before
any decision.

## 5. Risk policy and rungs

Three rungs, one strategy family, the vol target as the knob. Measured on
2018-01-01 → 2025-06-30 with tier-0 taker fees and Kalshi funding
(`research/kalshi_perps/rungs.json`); the holdout row is the one opening.

| rung | book | vol target / caps | CAGR | realized vol | max DD | worst day | positive months | losing years |
|---|---|---|---:|---:|---:|---:|---:|---|
| conservative | trend gate, long-only | 8% / gross ≤1.0, asset ≤0.5 | 9.1% | 5.8% | −6.2% | −2.6% | 72% | none (2022 +1.9%, 2023 +3.0%) |
| **balanced** (paper incumbent) | trend gate, long-only | 12% / gross ≤1.5, asset ≤0.75 | 10.7% | 7.9% | −9.4% | −4.1% | 68% | none (2022 +2.2%) |
| growth | trend gate, long-only | 18% / gross ≤2.0, asset ≤1.0 | 13.9% | 11.2% | −12.5% | −6.0% | 61% | none (2018 +0.5%) |
| beta 8% (no gate) | vol-targeted long | 8% | 13.4% | 9.1% | −14.8% | −4.1% | 64% | 2018 −4.2%, 2022 −4.3% |
| beta 12% (no gate) | vol-targeted long | 12% | 15.4% | 12.7% | −21.1% | −6.5% | 62% | 2018 −12.0%, 2022 −4.8% |
| beta 18% (no gate) | vol-targeted long | 18% | 20.0% | 18.9% | −31.7% | −7.8% | 62% | 2018 −21.3%, 2022 −13.8% |

Read the table as a menu of drawdowns you are choosing, not returns you are
buying: the beta rows depend entirely on BTC (+5x) and gold (+2.5x) having
gone up over the window, and the gated rows give up return to cut the left
tail. Realized vol runs below the target because the gate is often partly
out. Interest on idle collateral (about 3% a year at these exposures) is
included. Fees are 0.4–0.8% a year. No configuration was ever liquidated in
the simulation, including under the worst-intraday-point rule.

Policy limits by rung (`risk.PROFILES`):

| limit | conservative | balanced | growth |
|---|---|---|---|
| target vol | 8% | 12% | 18% |
| gross leverage | 1.0x | 1.5x | 2.0x |
| single asset | 0.5x | 0.75x | 1.0x |
| liquidation distance floor | 35% | 35% | 30% |
| daily / weekly loss stop | 2% / 6% | 3% / 6% | 4% / 8% |
| drawdown halve / kill | −6% / −12% | −8% / −15% | −10% / −20% |

Everything else is common: max order $1,000 notional, ±0.5% price collar,
12 orders per tick, 30-hour data age, margin ratio ≤ 0.5. All of it is
config, changed only by a reviewed commit.

## 6. Economics at your size (starting at $250)

Whole-contract simulation, 2018-01 → 2025-06, tier-0 taker, Kalshi funding
(`research/kalshi_perps/granularity.json`; "fractional" is the idealised
sizing every other table in this document uses):

| book | $250 | $500 | $1,000 | $2,500 | fractional |
|---|---|---|---|---|---|
| trend gate 12% (balanced): Sharpe / CAGR / max DD | 0.86 / 10.2% / −9.4% | 0.86 / 10.2% / −9.4% | 0.86 / 10.2% / −9.4% | 0.91 / 10.7% / −9.4% | 0.91 / 10.7% / −9.4% |
| trend gate 18% (growth) | 0.89 / 13.3% / −12.4% | 0.89 / 13.4% / −12.4% | 0.90 / 13.6% / −12.4% | 0.94 / 14.0% / −12.5% | 0.93 / 13.9% / −12.5% |
| beta 12% (no gate) | 0.91 / 14.9% / −22.0% | 0.96 / 15.9% / −22.0% | 0.94 / 15.6% / −22.2% | 0.95 / 15.6% / −21.1% | 0.94 / 15.4% / −21.1% |
| beta 8% (no gate) | 1.08 / 13.3% / −14.5% | 1.07 / 13.2% / −14.7% | 1.06 / 13.2% / −14.7% | 1.07 / 13.4% / −14.7% | 1.07 / 13.4% / −14.8% |

Granularity is not the constraint at $250. What $250 does mean:

| bankroll | balanced rung, expected/yr | typical drawdown | contracts held | note |
|---|---|---|---|---|
| $250 | ~$25 | −$23 | 2–10 | BTC rounds to 1–3 contracts; ETH/gold/silver are fine |
| $1,000 | ~$100 | −$94 | 8–40 | |
| $2,500 | ~$255 | −$235 | 20–100 | fees ~$14/yr |
| $10,000 | ~$1,020 | −$940 | 80–400 | still inside the $5k default per-market limit |

Expected = the $250-row CAGR from the table above; drawdown = its max
drawdown. Both are backtests on proxies. A 12 bps taker book trading four
times a year per asset spends about half a percent of equity on fees;
funding is zero most days; the 3.25% on idle collateral is the floor if the
gate is fully out (third parties report a $250 minimum average balance for
that interest, so a $250 account may earn none of it while positions are
open). The kalshi_prime fee table for retail was not published; tier 0 is
assumed. One BTC contract is ~3% of a $250 book, so at this size the
5% weight step in `vol_target` and the 3% rebalance band are the effective
granularity, and the engine will sometimes hold zero BTC when the target is
one contract's worth.

## 7. Promotion gate (PAPER → CANARY → PRODUCTION)

The desk is at PAPER. Real money requires all of the following, in order,
and the owner's explicit go at each step.

1. **Shadow, ≥ 6 weeks (≥ 6 weekly rebalances).** Fills booked at the far
   touch against the live book. Pass if: realized turnover ≤ 1.5× the
   backtest's, average slippage vs mark ≤ 2.5 bps, zero data-age or
   reconciliation incidents, P&L within the backtest's 5th–95th percentile
   path for the period. Owner tasks in parallel: perps application, a
   dedicated trade-only API key, a host for the daemon, an external monitor.
2. **Demo, 2 weeks.** Same engine with `--adapter demo` on `KX…PERP1`
   tickers: real IOC fills, reduce-only exits, bracket triggers,
   reconciliation, a rehearsed kill (touch the file, watch the flatten),
   a rehearsed restart with open positions. Demo prices are synthetic; this
   step tests plumbing, not economics.
3. **Canary, 4 weeks.** Conservative rung, 25% of the intended bankroll
   (minimum $250), `config/perps.json live: true`, `KALSHI_LIVE=1`, no kill
   switch. Pass if the ladder never trips and attribution matches shadow.
4. **Production.** Chosen rung, full bankroll. Standing rules: re-run the
   tournament quarterly with the registry intact; the Risk desk demotes a
   rung after any kill trip; retire the strategy if the trailing 12-month
   OOS Sharpe is below 0.3 or the ladder trips twice in a year; no rung
   above growth exists.

**Scaling ladder (owner starts at $250).** Capital is added only in steps,
only after a clean period, never into a drawdown, and the rung does not
change with the size:

| step | bankroll | condition to move up |
|---|---|---|
| canary | $250 | steps 1–3 above passed |
| 2 | $1,000 | 8 clean weeks at $250: no ladder trip, no reconciliation or data incident, attribution within the backtest's 5th–95th percentile band |
| 3 | $2,500 | 8 clean weeks at $1,000 and equity above its 8-week-ago level |
| 4 | $5,000+ | 12 clean weeks at $2,500; check `GET /margin/notional_risk_limit` before exceeding $5k notional in any market |

Each step is at most 4× the previous one; a step is skipped, not repeated,
if the drawdown ladder is past its soft line; removing capital is always
allowed. Volume tiers help on the way up: $100k of 30-day notional (about
$3.3k a day) drops taker fees from 12 to 10 bps, and the 15-minute desk's
prediction volume counts toward the same tier.

A profitable shadow month is not a go-live. The gauntlet's verdict on alpha
stands until a candidate passes all seven gates; funding the gated-beta
posture is the owner's risk decision, made against §5's numbers.

## 8. How to run it

```bash
pip install -r requirements.txt
python -m unittest tests.test_perps -q               # 32 tests, no network
python -m quantfirm.perps.cli markets                 # live contract table (no key)
python -m quantfirm.perps.cli funding --asset btc     # Kalshi funding summary
python -m quantfirm.perps.cli update-data             # refresh data/perps/
python -m quantfirm.perps.cli backtest --strategy trend_long_only --split dev --start 2018-01-01 --yearly --stress
python -m quantfirm.perps.cli walkforward --strategy tsmom --grid '{"lookbacks": [[63,126,252],[126,252]]}'
python -m quantfirm.perps.cli tournament              # the pre-registered run, dev only
python -m quantfirm.perps.cli paper --adapter shadow --minutes 1 --verbose   # one shadow tick
./scripts/perps_loop.sh                               # 24/7 shadow supervisor (hourly ticks)
python -m quantfirm.perps.cli status
```

Kill switch: `touch state/KILL_SWITCH_PERPS` (every tick and every order
checks it; removing it is an owner action by commit). Demo and live need
`KALSHI_PERPS_KEY_ID` + `KALSHI_PERPS_PRIVATE_KEY[_PATH]` in `.env.kalshi`
(see `.env.kalshi.example`); live additionally needs `KALSHI_LIVE=1` and
`live: true` in `config/perps.json`. Keys never enter git.

## 9. What would change the verdict

**2026-09-18, afternoon.** Owner killed the incentive desk and will move the
$257 to perps margin themselves **after** the paper books have a reading.
The earlier "leave it on LIP" call in this section is overridden. The
incentive collector, quoter, and runbook are gone. This desk is
**PAPER/SHADOW** (`live: false`); a transfer is not a go-live. Paper the
three measured books, not a new catalog. Strategy catalog and funding
watch still stand in `research/kalshi_perps/ALLOC_257.md`.
`scripts/perps_alloc_257.py --live` reprints the $257 economics.

* A candidate that beats vol-scaled long-only out of sample with DSR ≥ 0.95
  and PBO ≤ 0.10 under the same cost model. The backlog is now shorter than
  it was, because §3c answered its biggest item: **more coins are not the
  missing diversifier.** All 20 tradable crypto perps together are 2.5 bets,
  so the thing worth waiting for is a perp in an asset class that is not
  crypto — copper, US500 and WTI were on Kalshi's roadmap, and gold and
  silver are already the only genuine diversifiers in the book. What is left:
  a funding-conditional overlay if Kalshi's BTC premium persists above the
  deadband (it has: +15.13%/yr over the last 90 intervals as of 2026-09-18);
  gold-specific carry once the metals funding history is months long rather
  than days.
* Kalshi's own history reaching a year, so the proxies can be replaced.
* A fee tier below 12 bps (≥ $100k of 30-day volume, which the 15-minute
  desk's prediction volume also counts toward).
* A CME v. CFTC outcome that reclassifies perps: re-read this document
  before doing anything.

## 10. Sources

Primary: Kalshi `/margin` endpoints (2026-09-14/15 pulls), docs.kalshi.com
margin reference, Kalshi help-center perps collection (16 articles), CFTC
order and press release of 2026-05-29, CFTC filings for the fee schedule
(2026-06-24), DOTPERP (2026-06-01), GOLDPERP/SILVERPERP (2026-09-08),
COPPERPERP/US500 (2026-08-18). Evidence: see `evidence_review.md` (Bailey &
López de Prado; Bailey, Borwein, López de Prado & Zhu; Harvey & Liu;
Moskowitz–Ooi–Pedersen; Hurst–Ooi–Pedersen; Liu–Tsyvinski; Han–Kang–Ryu;
He–Manela–Ross–von Wachter; Alexander–Deng–Zou; Harvey et al. 2018; Man
Group; BIS WP 1087; Chague et al.; Barber et al.; nof1 Alpha Arena
reporting; arXiv 2603.10092; SEC order on Knight Capital).
