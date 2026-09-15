# KALSHI PERPS DESK — plan, evidence, verdict, and how the agents run it

**Status: RESEARCH + SHADOW. Nothing trades real money.** Built 2026-09-15 on
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
   Funding is almost always exactly zero (rates under 0.01% per interval
   round to zero; 55–97% of all intervals since June have been zero), idle
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
3. **The firm's own gauntlet returned NO-GO for alpha.** Thirteen
   pre-registered trend/momentum configurations on BTC/ETH/gold/silver,
   2016–2025, honest walk-forward with in-sample parameter selection: the
   best candidate (a long-only trend gate) scored out-of-sample Sharpe
   0.80 against 1.13 for the control it had to beat (vol-scaled long-only).
   Probability of backtest overfitting across the trial set 0.30 (bar 0.10);
   deflated Sharpe 0.66 (bar 0.95). Long/short trend scored 0.4–0.5. The
   gold–silver ratio idea is negative. The coin-flip control loses money.
4. **What does work is beta, sized by volatility, with a trend gate as
   drawdown insurance.** That is not alpha; it is a bet that BTC/ETH/gold/
   silver keep drifting up, made cheaply. Measured 2018–2025 with tier-0
   taker fees: vol-targeted long-only earned 13–20% a year with 15–32%
   drawdowns and lost money in 2018 and 2022; the same book behind a trend
   gate earned 9–14% a year with 6–12% drawdowns and no losing year, at the
   cost of ~4 points of return. On the sealed holdout (2025-07-01 → today,
   opened once), the gated book made +23.7% at a −4.9% drawdown versus
   +27.1% at −11.6% for the ungated one.
5. **"Consistent" means 61–72% positive months and about 77% positive
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

## 2. What the evidence rules out, and why

| Idea | Verdict | Reason (details and citations in `evidence_review.md`) |
|---|---|---|
| LLM decides entries, sizes, leverage | **out** | Alpha Arena S1: 4/6 lost 31–63%; S1.5: a third of $320k lost, 1,418 trades in a round; gated vs ungated agent drawdown 3% vs 46%; nof1: "that path doesn't work yet" |
| Funding carry | **out on Kalshi** | deadband zeroes most intervals; collateral already earns 3.25%; 2026 basis below T-bills Feb–Jul everywhere |
| Cross-venue funding/basis arb | **out** | needs an offshore short a US retail account cannot hold; 95% forced exits in the one large-sample study; two taker fees exceed the spread |
| Market making / fast mean reversion | **out** | no rebates below 0.5% of venue maker volume; adverse selection; GSR quotes these books |
| Intraday / multi-hour signals, grid bots | **out** | 20 round trips a month at 12 bps and 2x is a 115%/yr fee hurdle |
| Long-tail alt perps | **out** | 6–19 bps spreads, thin books, negative funding drift, rule changes mid-position |
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

* A candidate that beats vol-scaled long-only out of sample with DSR ≥ 0.95
  and PBO ≤ 0.10 under the same cost model. The research desk's backlog:
  cross-asset trend with more diversifiers once copper, US500 and WTI perps
  list (a four-asset book with 0.9 BTC–ETH correlation is two bets, not
  four); a funding-conditional overlay if Kalshi's BTC premium (+14.8%/yr in
  September) persists above the deadband; gold-specific carry once the
  metals funding history is months long, not days.
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
