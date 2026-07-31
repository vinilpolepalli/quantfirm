# FIRM DESIGN BRIEF — Autonomous Agent-Run Quant Trading Firm
**Bankroll: $250 (Robinhood Crypto, spot, long-only, no leverage) | Universe: BTC-USD, ETH-USD (SOL optional) | Data: hourly bars 2019-01-01 → 2026-06-30 in `/home/user/2-3-24VEX/data/` | Engine: `/home/user/2-3-24VEX/quantfirm/`**

Prime directive, in strict order: (1) never breach the risk gate, (2) survive, (3) compound.

---

## 1. Org Chart — Agent Desks

Every strategy is a state machine: `IDEA → RESEARCH → REVIEW → PAPER → CANARY → PRODUCTION → WATCH → DEPRECATED`, with capital ceilings of $0 (IDEA–PAPER), 5% of target size (CANARY, ~2 weeks), full size (PRODUCTION only). Only the Referee Desk may promote; only the Risk Desk may demote. No agent approves its own work (RTS 6 / FCA multi-disciplinary sign-off analog).

| Desk (agent) | Real-firm role | Cadence | Single metric |
|---|---|---|---|
| **Research Desk** (proposer swarm) | Quantitative Researcher | Weekly batch + on-demand; hypothesis registered *before* first backtest | Eval **Score** (Section 2); count of gate-passing survivors (target 1–3, not a leaderboard) |
| **Referee Desk** | Model validation / peer review committee | Weekly promotion/demotion review; vault run exactly once per go-live candidate | 100% of promotions with DSR ≥ 0.95, PBO ≤ 0.10, checklist signed; unauthorized promotions = 0 |
| **Risk Desk** | Independent central risk (pod-platform style; unilateral, non-appealable) | Pre-trade gate on **every** order; intraday check each hourly tick; overnight batch VaR/ES | Limit breaches = 0; distance to drawdown ladder (Section 5); portfolio realized vol vs 25–35% target |
| **Execution Desk** | Quantitative Trader / execution | Hourly tick (`7 * * * *` UTC); timeout-then-reprice loop on resting limits | Implementation shortfall: realized cost/side ≤ modeled 0.93%; slippage log fed back to `costs.py` |
| **Ops Desk** | Middle office / reconciliation | Start of **every** tick (broker state is truth, reconcile before any decision) + post-close daily booking | Reconciliation breaks = 0; IN-DOUBT orders resolved before any new order |
| **Attribution Desk** | Performance attribution | Daily (evening job) | Live-vs-backtest divergence; alert on rolling 60d Sharpe < 0.8× research profile or feature drift > 2σ |
| **Platform Desk** | Quant Developer / Core Engineering | Per-deploy + nightly registry checksum verification | Deployed code hash == strategy-registry hash (the Knight check); dead code in prod = 0 |
| **Capital Allocation Desk** | CIO / platform capital committee | Monthly | Reallocate: scale live-consistent winners, cut divergers; per-strategy live Sharpe vs research Sharpe |
| **PostMortem/Compliance Desk** | Compliance + SRE incident review | Within 48h of any incident (limit breach, kill trip, recon break, deploy fault); weekly action-item chase; **quarterly kill-switch fire drill**; annual self-audit | Blameless post-mortem filed ≤ 48h; open action items = 0 at weekly review; drill pass/fail |

**Daily operational loop (UTC, mirrors real desk cadence):** overnight batch ~05:07 (recon, VaR/ES, registry verification); pre-market check ~07:37 (did overnight jobs run, stale orders, positions/P&L, event calendar); hourly intraday monitor at :07; post-close ~21:07 (booking, per-strategy P&L); evening attribution ~23:07.

---

## 2. The Eval — Metric, Procedure, Anti-Overfitting Gates

**The scalar the swarm maximizes:**

```
Score = S_wf × 1{DSR ≥ 0.95} × 1{PBO ≤ 0.10} × 1{all hard constraints pass}
```

`S_wf` = **median** across 8 walk-forward folds of annualized **net** OOS Sharpe (daily-aggregated returns; never hourly — autocorrelation inflates hourly SR). Any failed gate returns exactly **0** — no gradient for gamed submissions.

**Procedure (exact):**
1. **Vault:** final 12 months (2025-07-01 →) are inaccessible to proposers — enforced in `quantfirm/data.py` (refuses bars past cutoff without a referee-only key), not by policy. Referee runs the surviving candidate on the vault **exactly once** pre-deployment; any revision after seeing vault results burns that vault permanently.
2. **Walk-forward:** dev window 2019-01 → 2025-06, K=8 rolling folds: 24-month IS / 6-month OOS / 6-month step (Pardo 4:1), **7-day purge/embargo** between IS end and OOS start.
3. **Per fold:** parameters fit on IS only; OOS fills at **next-bar open** (never signal-bar close); costs 0.93%/side (Section 3); returns aggregated to daily.
4. **Trial registry (swarm-safe core):** append-only; every backtest invocation logs family ID, code hash, parameter vector, full daily P&L. The instrumented runner is the *only* path to a score. N = registry count per family, deduplicated by clustering return streams at correlation > 0.7. DSR computed with SR0 = √V[{SRₙ}] · ((1−0.5772)·Z⁻¹(1−1/N) + 0.5772·Z⁻¹(1−1/(N·e))) and the skew/kurtosis-corrected PSR denominator. Every grid point increments N — brute force is self-defeating.
5. **PBO:** referee runs CSCV with S=16 (12,870 splits) on the T×N matrix of all registered trials; require PBO ≤ 0.10 plus non-negative OOS-vs-IS degradation slope.

**Hard constraints (any failure → Score = 0):**
- **Sample size:** ≥ 40 round trips across the universe over the dev window; ≥ 3 OOS round trips per fold (no zero-activity folds counted as wins).
- **Cost hurdle:** mean gross profit per round trip ≥ 3.75% (2× the 1.87% break-even); turnover ≤ 12 RT/asset/year.
- **Risk:** max drawdown of concatenated net OOS equity ≤ 30%.
- **Consistency:** positive net OOS return in ≥ 5 of 8 folds; Walk-Forward Efficiency (median OOS SR / median IS SR) ≥ 0.5.
- **Benchmark:** vol-scaled buy-and-hold of the traded universe inserted as trial N+1 in every fold and in the CSCV matrix — candidate must beat it OOS, or the swarm's optimum is trivially HODL.
- **Realism:** long/flat only, ≥ 1-bar execution lag, universe declared before running (changing it afterward = new registered trial).

**Anti-gaming rules:** proposers receive only aggregate fold stats (SR, trade count, DD, per-fold sign) — never bar-level OOS P&L; eval code (backtester, `costs.py`, `data.py`, metric) is hash-pinned, CI rejects swarm PRs touching anything outside `quantfirm/strategies/`; one-paragraph economic rationale registered before a family's first trial; ties break toward fewer parameters and fewer trades. Any net Sharpe > 2.5 on daily crypto is presumptively overfit — audit before believing. Harvey-Liu floor: t-stat ≥ 3.0.

**Go-live gate:** vault pass, then ≥ 4 weeks paper trading with realized slippage within the modeled 1.85% RT and cumulative P&L above the backtest's 5th-percentile path; then CANARY at 5% size for 2 weeks; then scale.

---

## 3. Cost Model — Hard-Coded Numbers (`quantfirm/costs.py`)

| Parameter | Value | Source |
|---|---|---|
| Measured v1 spread (BTC-USD, 2026-07-31) | **0.926681%/side** (buy = sell) | `GET /marketdata/best_bid_ask/` |
| `RH_MARKET` (APPROVAL_COST — every strategy must pass this) | 0.93%/side, 1.85% RT | costs.py |
| `RH_LIMIT_AGGRESSIVE` (marketable limit, ~2/3 spread) | 0.62%/side | costs.py |
| `RH_LIMIT_PATIENT` (rest near mid, ~1/3 spread; fill risk) | 0.31%/side | costs.py |
| Slippage haircut on top of spread | +0.10%/side | execution realism |
| **Exact break-even mid move** | **(1+s)/(1−s)−1 = 1.871%** (use this, not 2s) | arithmetic |
| Cost stress test | 1.5× = 1.39%/side; must stay net-positive | anti-fee-fantasy |
| API v2 (exchange routing) at < $10K 30-day volume | 0.95%/side taker (taker-rate-only until maker/taker rollout completes) — **worse than v1; do not use** | RHC fee schedule 20260622 |

**Frequency drag at 1.85% RT:** 1 RT/day = 679%/yr; 1 RT/week = 97%/yr; 2 RT/month = 45%/yr; 1 RT/month = 22%/yr; 1 RT/quarter = 7.4%/yr. Viable operating point: 1–4+ week holds, ≤ 1–2 RT/month.

**Execution rules:** v1 **limit orders only** (`limit_order_config = {asset_quantity, limit_price}`), never market; `client_order_id` UUID for idempotency; cancel-and-reprice loop via `POST /orders/{id}/cancel/`; `gtc` TIF (no IOC/FOK exists — track `open`/`partially_filled` states and reconcile `filled_asset_quantity` before the opposite leg). Fetch `GET /trading_pairs/` at startup and pre-order — do not hardcode: BTC min 0.000001 / increment 1e-8, ETH min 0.0001 / increment 1e-6, quantize with `Decimal`, require `status == "tradable"`. Client-side token bucket ≤ 80 req/min (limit 100 sustained / 300 burst), batch symbols in one `best_bid_ask` call, exponential backoff on 429. Call `estimated_price` at actual order size pre-trade and log effective spread to recalibrate `costs.py`.

---

## 4. Strategy Shortlist — Ranked by Survival Probability at 1.85% RT

Pre-filters (reject before any backtest): expected gross edge/trade < 3× RT (< 5.6%), or > 12 RT/asset/yr, or average winner < 7.4% (costs would exceed 25% of avg win; requires ~6–14 days of drift at 2–3% daily vol).

| Rank | Strategy | Parameter search ranges | Expected turnover | Why it survives |
|---|---|---|---|---|
| **1** | **Slow MA-crossover trend, long-flat, BTC/ETH daily bars** | fast 20–50d × slow 100–300d (canonical 20/100, 50/200); whipsaw filter: 2–3 daily-close persistence OR close beyond MA by 1× ATR(20) | 2–6 RT/yr/asset (drag 3.7–11%) | Strongest crypto evidence (Liu-Tsyvinski 1–4wk TSMOM: +3.16–3.66%/wk per 1σ; Grayscale 20/100 Sharpe ~1.7 gross; Reading: TS momentum is the *only* factor behind all profitable BTC technicals); trend legs of 20–100% dwarf 1.85% RT |
| **2** | **Trend-gated vol-targeted long BTC** | gate: price > 100–200d MA; vol target 20–40% ann; estimator: 20–30d realized vol; rebalance **band 20–25% weight deviation**, weekly check (never daily — daily rebalance = 5–15× turnover = 4.5–13.5%/yr drag) | 2–4× book/yr (drag 1.9–3.7% at 0.93%/side) | Vol persistence + Moreira-Muir; Sharpe 0.89 vs 0.61 B&H, max DD −21% vs −46% in regime studies; band rebalancing is the cost fix |
| **3** | **Slow Donchian/ATR breakout (Turtle-style)** | entry 40–100d high (canonical 55d); exit 20–50d low OR 2–2.5× ATR(20) trailing stop; ATR-based sizing | 3–8 trades/yr | Same family as trend; positive through 2018 and 2022 bears at 30–40% win rate, 3–5× win/loss |
| **4 (marginal)** | **Weekly TSMOM sign, 1–4wk horizon, BTC+ETH** | 3–12-month lookback sign; hysteresis band tuned so flips < 10/yr | ≤ 10 RT/yr | Direct Liu-Tsyvinski horizon; viable only with strict flip suppression |

**Banned (mathematically dead at 1.85% RT):** short-term mean reversion (gross edge 0.3–1.5%/trade < one round trip; Reading OOS Sharpe collapsed 0.66 → 0.06); cross-sectional alt momentum (50–200%/wk turnover = 50–100%+/yr drag, needs shorting, survivorship-biased); intraday/opening-range breakout (100–250 trades/yr = 180–450%/yr drag); any daily-rebalance or intraday strategy (break-even 1.87% ≈ 1 daily σ of BTC).

**Calibrated expectations:** net Sharpe 0.7–1.2, 2–8 trades/yr/asset, long flat periods, 30–50% drawdowns in bad regimes. 2012-anchored backtests (Sharpe 1.7+) are hypergrowth-inflated; validate on 2018/2022 bears and 2019/2025 chop, reported per-regime.

---

## 5. Risk Policy — $250, High Risk Tolerance, No Ruin

**Ruin is defined in code:** equity < **$125** (50% of initial — below ~$100–125, spread + minimum-size effects exceed any plausible edge; the account is economically dead before $0).

| Control | Limit | Enforcement |
|---|---|---|
| Per-trade risk | min(0.25–0.5× Kelly of *estimated* edge, **2% of current equity** = $5); absolute ceiling 3% ($7.50) | % of current equity only (anti-martingale). At 2%: RoR ≈ 0.004%, P(20% DD) ≈ 13%. At 5%: 45% chance of tripping the kill switch — never |
| Portfolio vol target | **25–35% annualized** (≈ half-Kelly for SR 0.5–0.7); EWMA daily-return vol, 25–36d span; notional = (target/asset vol) × equity | Recomputed each tick; BTC at ~50% vol ⇒ ~50–60% of equity max notional |
| Drawdown ladder (from persistent HWM) | **−15%**: halve all sizing (soft brake). **−25%** ($62.50 from peak): flatten everything, cancel all orders, write persistent `DISABLED` flag; resume only by explicit human commit — never auto-resume | Automatic, non-appealable, code-executed |
| Per-strategy (pod-style) | −5% of allocated capital → halve; −7.5% → terminate strategy | RiskAgent, no appeal |
| Daily loss limit | 5% of start-of-day equity (~$12.50) = 3× per-trade risk → cancel opens, block new entries until next UTC day (exits/stops stay live) | Automated lockout |
| Weekly loss limit | 10% (~$25) → block entries until Monday | Automated |
| Consecutive losses | 4 straight → 24h entry pause | Automated |
| Exposure caps | Single asset: 50% equity (BTC/ETH), 25% any other; all crypto = one correlated bloc (BTC/ETH/SOL corr 0.7–0.9) governed by the vol target; **hard 10% minimum cash buffer**; whitelist BTC, ETH + ≤ 1–2 liquid alts | Pre-trade gate |
| Pre-trade risk gate (15c3-5 analog — separate module, strategy proposes, gate approves; limits in version-controlled config, changeable only by human-reviewed commit) | max order notional $150; max daily traded notional 2× equity ($500); price collar ±2% from last trusted mid; duplicate-intent check; whitelist check; cash-buffer check; HALT/DISABLED-flag check; reject orders where spread + min-size effects > 25% of the trade's risk budget | Every order, logged reasons |
| Data circuit breakers | quote age > 2× polling interval → skip cycle; stale > 15 min → halt entries + alert; > 10% move in 5 min or > 6σ → freeze asset until next-cycle confirmation; 3 consecutive API errors → exponential backoff; ~15 min continuous failure → halt entries, keep managing exits | Deterministic gating layer |
| Execution integrity | UUID idempotency key persisted (write-ahead) *before* API call; ambiguous response → `IN-DOUBT`, all new orders blocked until reconciled against broker records; fills deduped by broker order ID; broker state reconciled at every startup/tick before any decision — unexplained mismatch → immediate halt, no "corrective" trading | Knight lesson: stop first, debug second |
| Orphan protection | Every position carries a resting `stop_limit` order or max-holding-period exit, so a dead bot leaves bounded risk | Checked each tick |

---

## 6. Deployment Architecture — GitHub Actions + State + Kill Switch + Oversight

**Repo:** private (2,000 free Linux min/month; avoids the 60-day public-repo cron auto-disable). Default branch = production: protected, scheduled workflows run only its latest commit, all config changes land via PR + CI backtest smoke test.

**Trading workflow (`trade.yml`):**
```yaml
on:
  schedule: [{cron: "7 * * * *"}]   # hourly, off-peak minute — never minute 0
  workflow_dispatch: {}
concurrency: {group: trading-engine, cancel-in-progress: false}  # queue, never kill mid-order
jobs:
  tick:
    timeout-minutes: 10
    permissions: {contents: write}
```
Engine must be schedule-independent and idempotent: GH cron drifts 3–15 min routinely (60+ min under load, occasionally skipped) — a missed tick must be safe, which is exactly why only swing/position strategies (Section 4) are deployable here. Budget: keep the job ≤ 2 billed minutes (shallow checkout, pip cache) → ~1,450 min/month, leaving ~500 for oversight + CI.

**State:** authoritative `state/state.json` **committed to the repo** every run (positions, cash, HWM, last-run timestamp, idempotency keys, IN-DOUBT ledger, consecutive-failure counter, P&L snapshots) via `git pull --rebase` + push-retry; git history = free audit trail. Artifacts for verbose per-run logs only; never `actions/cache` for state (7-day eviction).

**Secrets:** Robinhood Ed25519 key in environment-scoped Actions secrets with protection rules, **trade-only permissions (no withdrawal)**; never echo/transform secrets; all third-party actions pinned to commit SHAs.

**Kill switch — three layers + drill:**
1. **`HALT` file at repo root** — engine checks at startup AND immediately before every order submission; one-line commit by human or oversight agent; git blame shows who halted and why.
2. **`gh workflow disable trade.yml`** (or REST `PUT .../workflows/{id}/disable`) — out-of-band hard stop, independent of layer 1.
3. **Self-halt** — engine writes `HALT` itself on: 3 consecutive run failures, daily/weekly loss breach, −25% drawdown trip, or reconciliation mismatch.
4. **Quarterly fire drill** — scheduled job that actually exercises the kill path (post-Knight requirement: kill switches must be designed *and tested*).

**Agent oversight session (separate scheduled Claude session / `claude-code-action`, every 6h):** interacts with the system **only through git** — reads `state.json` + recent logs; on risk breach or stale heartbeat (last-run timestamp > 2h old) commits `HALT` directly (effective next tick) and alerts the human; proposes parameter/strategy changes **only via PR against config files**, never direct commits to trading logic — merge to default branch is the human go/no-go gate. Permissions: `contents: write` + `pull-requests: write`; **no access to broker secrets, ever.** Optional backstop: external scheduler (Cloudflare cron) fires `workflow_dispatch` if a tick is overdue.

**Supporting scheduled jobs:** overnight batch 05:07 UTC (reconciliation, VaR/ES, registry-vs-deployed checksum verification — the Knight check); pre-market check 07:37; evening attribution 23:07; weekly Referee promotion review; monthly capital reallocation; 48h post-mortem trigger on any incident.

**Deployment discipline:** one code path, no dead strategy code importable, no reused config flags; every deploy followed by a dry-run smoke tick; documented single-command flatten-and-disable procedure in the RUNBOOK; every alert triaged, never accumulated (Knight's 97 unread emails).

---

**Bottom line:** the firm is a slow-trend shop by arithmetic necessity — 0.93%/side makes everything faster than ~1 round trip/month unwinnable at $250. The Eval's job is to say "no" almost always: with DSR/PBO gates, an untouchable 12-month vault, a benchmark that must be beaten, and a trial registry that taxes the swarm's own search, most proposals scoring 0 is the system working. Target: 1–3 genuine survivors trading BTC/ETH a handful of times per year, sized at $5 risk per trade, under a 25% hard-stop drawdown ladder, on an hourly GitHub Actions tick that any human or agent can halt with a one-line commit.
