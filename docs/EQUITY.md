# QUANTFIRM — EQUITY FIRM DESIGN BRIEF
**Venue:** Robinhood Agentic MCP (segregated agentic account `534796784`) · **Capital:** $250, cash account, high risk tolerance · **Date:** 2026-07-31
**Synthesized from:** rh-equity-microstructure, xsec-momentum, etf-rotation, news-events, survivorship-eval, risk-smallacct, deployment-mcp

---

## 1. Cost Model for the Backtester (bps per side)

Robinhood is the measured worst-execution mainstream PFOF broker (~26.8% price improvement vs 36–47% at peers; 31.4 bps round-trip on small orders over a broad universe — Schwarz et al., JoF 2025). Do **not** model midpoint fills; model fills at NBBO ± 65–75% of half-spread.

| Asset class | Base (bps/side) | Conservative (bps/side) |
|---|---|---|
| Major ETFs (SPY, QQQ, VOO, IVV, IWM, DIA) | **1.0** | 2.0 |
| Other liquid rotation ETFs (EFA, EEM, VNQ, IEF, TLT, GLD, PDBC, TIP, BIL) — interpolated tier | **2.0** | 4.0 |
| Mega caps (top ~20 by ADV: AAPL/MSFT/NVDA class) | **2.0** | 3.0 |
| Remaining top-200 large caps | **4.0** | 8.0 |
| Blended flat (single-number model) | **5.0** | — |
| Stress test (mandatory, every config) | — | **15.0** |

**Fixed fees (matter at $250 scale):**
- **+$0.01 per SELL** (SEC §31 fee $27.80/$1M, rounded UP to the penny). This does not shrink with order size: 0.4 bps on a $250 sell, 2 bps on a $50 sell, **8 bps on a $12.50 sell**. Model buys at $0 fixed. FINRA TAF = $0 (not passed through on sells ≤50 shares).
- **Time-of-day multiplier** on spread cost: ×1.5–2.0 for 9:30–9:45, ×1.25 for 9:45–10:00, ×1.0 for 10:00–15:30, ×1.1 for 15:30–16:00. SPY-class ETFs: ×1.0 all day.

**Turnover drag budget:** monthly-rebalance stock momentum ≈ 0.3–0.6%/yr; weekly turnover ≈ 0.5–0.7%/yr; daily full turnover ≈ 2.5–3.5%/yr base, ~7.5%/yr at stress. **Hard hurdle: any strategy whose gross alpha per trade is under ~15 bps round-trip is untradeable at this scale.** Reject any tournament variant whose edge disappears at 10 bps/side.

---

## 2. Account/Venue Constraints That Shape Everything

**Cash account, PDT-exempt.** Cash accounts are fully exempt from the Pattern Day Trader rule (PDT is margin-only). Moreover, FINRA Rule 4210 amendments (SEC-approved 2026-04-14, effective 2026-06-04, broker implementation to 2027-10-20) eliminate PDT entirely. Zero PDT logic needed.

**T+1 settlement (since 2024-05-28) and GFV — the binding constraint.**
- GFV = selling a position that was bought with unsettled funds before those funds settle. Buying with unsettled proceeds is legal if the new position is held until the funding sale settles (next morning).
- **3 GFVs in 12 months → 90-day settled-funds-only restriction = bot death.** Fail-safe at 2.
- Sustainable ceiling: **one full round trip of the entire account per trading day** (~$500 total notional/day, 100% daily turnover, forever, zero violation risk). Our monthly-cadence strategies sit far below this ceiling.
- Hard rule encoded in the order layer: never sell a lot on the same day its purchase was funded by an unsettled sale; the bot maintains its own T+1 settled-cash ledger, independent of venue buying power.

**Fractional order rules (Robinhood):**
- $1 minimum; dollar-based orders are **market orders, regular hours only (9:30–16:00 ET)**; unexecuted fractional orders auto-cancel after ~5 minutes; no stop/limit protection on fractions.
- Extended hours = limit-only; 24 Hour Market = whole-share limit only. A $250 book **cannot** rely on either. Orders placed while closed are queued to next open (stale-signal execution) — never place them.
- Consequence: price protection is implemented agent-side — pre-order quote check via `get_equity_quotes`; skip if quoted spread > 10 bps or price moved > threshold from signal.

**MCP execution flow:** `review_equity_order` (simulate + warnings) → `place_equity_order`; no documented `client_order_id`; response schemas undocumented → schema-validate the fields used (fill qty, avg price, order state) and abort-with-state-note on mismatch. Reconciliation surface: `get_equity_positions`, `get_equity_orders`, `get_accounts`, `get_equity_quotes`, `get_equity_tradability`, `cancel_equity_order`. Blast radius is capped by the venue: MCP only touches the segregated $250 agentic account.

---

## 3. Strategy Tracks and Tournament Grids

**Universe bias status:** Track A instruments are survivorship-free (ETFs; the fitted parameter is the *menu*, justified by economic role only). Track B universe = today's top-200 liquid US large caps — **documented membership/survivorship bias**: current-constituent momentum backtests overstate CAGR massively (S&P 100 top-10 ROC: 26% → 12.2% point-in-time; Nasdaq-100: 46% → 16.4%, max DD 41% → 83%). All Track B results take Section 5 haircuts.

### Ranked by evidence quality net of costs

| Rank | Config family | Evidence grade | Honest net expectation |
|---|---|---|---|
| 1 | **B1: Long-only 12-1 large-cap momentum, band rebalance** | Tier 1 — JT 1993; Israel-Moskowitz long-side; FIM live-cost data (~6 bps/rebalance); **survivorship-free live anchors: MTUM +3.0pp/yr vs S&P over decade, SPMO top factor ETF 2015–2026** | +1–3pp/yr over SPY, 6–10%/yr tracking error, multi-quarter lag streaks; cost drag 0.3–0.6%/yr |
| 2 | **A1: HAA-style canary TAA** | Tier 2 — best real-time OOS class on AllocateSmartly; the group that actually protected in 2022; Keller family overfit-prone | 6–10% CAGR, Sharpe 0.5–0.7 (half of published), max DD 12–20% |
| 3 | **A4: Faber 10-month trend overlay** | Tier 1 *as risk tool*, Tier 3 as alpha — halves index max DD; cost = 2–4pp CAGR per bull decade of whipsaw | Insurance, not alpha; always-on gate for Track B |
| 4 | **A2: Robust GEM ensemble** | Tier 3 — OOS 2014–2021: 5.9% ann, −33.7% DD, lagged SPY every window; ensemble + bond-leg fix addresses known failure modes | SPY −0–3pp CAGR, ~half max DD |
| 5 | **A3: Adaptive allocation lite** | Tier 3 — concept replicates, optimized versions don't; live < sim | 60/40 +1–2pp, Sharpe 0.4–0.6, max DD ~−15% |
| — | **Excluded:** XL* sector rotation (long-short negative post-1999, top-1/3 no edge), Accelerating Dual Momentum (worst OOS decay tracked), mean-reversion/loser-buying (bias-dominated: every loser recovered by construction in a survivor universe), PEAD (dead in large caps since ~2006), any short leg, LLM sentiment | | |

### Track A — ETF rotation (~44 configs)

**A1. HAA canary (6 configs):** Canary = TIP, momentum = avg(1,3,6,12m). Positive → offensive: top-N ∈ **{3,4,5}** of {SPY, IWM, EFA, EEM, VNQ, PDBC, IEF, TLT}, equal weight, each asset also requiring positive own-momentum else slot → best-of(IEF, BIL). Negative → all defensive = best-of(IEF, BIL). Momentum ∈ {avg-1/3/6/12 (default), 13612W (one whipsaw-accepting variant)}. Monthly.

**A2. Robust GEM (8 configs):** SPY / VEU / IEF-with-BIL-fallback. Lookback ∈ **{6m, 9m, 12m, avg(6,9,12)}** × tranches ∈ {1, 2 half-month}. **Non-negotiable fix: dual-momentum the defensive leg vs BIL** (the 2022 lesson — never an unfiltered duration bet).

**A3. Adaptive lite (24 configs):** Universe {SPY, QQQ, IWM, EFA, EEM, VNQ, IEF, TLT, GLD, DBC}. top-N ∈ {4,5,6} × lookback ∈ {126d, ensemble 60/120/180d} × weight ∈ {equal, inverse-vol 60d} × per-asset 10m-SMA filter ∈ {on, off}. Monthly.

**A4. Faber overlay (6 configs):** SPY vs SMA ∈ {8,10,12}m × hysteresis ∈ {0, 2%}; risk-off asset = **BIL/SHY only**. Month-end evaluation only.

### Track B — stock cross-sectional (~40 configs, bias-documented)

**B1. Long-only momentum:** formation ∈ **{6-1, 12-1, 12-7}** × N ∈ **{10, 15, 20}** equal-weight × rebalance ∈ **{monthly, quarterly, band (enter top-10%, exit on falling out of top-25%)}** = 27 base; + 12-0 skip-test (1); + risk-adjusted score (ret/vol) on 12-1 × 3 rebalances (3); + overlays on the best base family only: {absolute-momentum-to-cash (Antonacci), vol-scaling to 12% target (Barroso–Santa-Clara), both} (~9). Band variant expected to dominate net (Novy-Marx–Velikov: bands halve turnover at little gross cost).

**Concentration resolution (risk desk vs eval desk):** risk desk's diversification sweet spot is 10 names; eval desk requires ≥20 names so single-survivor lottery tickets can't drive results (the 83%-DD case was top-10). **Ruling: scoreboard eligibility requires the winner to keep its sign and ≥50% of magnitude at N=20; live deployment at N=15–20 (~$12.50–16.70/slice; note the $0.01 sell fee = 6–8 bps at that size, priced into Section 1).** N=10 configs run as diagnostics only.

**Total pre-registered: ~84 configs** (under the ≤200 budget; every config logged counts toward DSR's N whether reported or not).

---

## 4. News Desk Verdict

**News is a RISK FILTER, not a signal. The news desk originates zero trades.**

- **No news/LLM sentiment alpha.** Quant firms' news edge is millisecond latency + thousands-of-names breadth via $10k+/yr machine feeds (RavenPack, Bloomberg EDF) — structurally unavailable to us. LLM-sentiment backtests (Lopez-Lira ~90% hit rate, ~700% cumulative) are lookahead-contaminated (predictive power collapses to ~zero post-training-cutoff); every live record is negative (AIEQ 3-yr −2.4% vs +13.3% SPX; GPT Portfolio 5.8% vs 14%). Inadmissible until someone shows live, audited, net-of-cost outperformance — as of mid-2026, nobody has.
- **No PEAD.** Non-existent in large caps since ~2006 (Martineau); our liquid universe is exactly where it's deadest.
- **The one robust use: the earnings-calendar risk gate** (stock track only). Earnings day is a 3–5× volatility event: mean implied move ~4.7% (near-record, Oct 2025 season) vs 0.5–1.5% normal; realized exceeds implied 25–63% of the time; tails to −26% (META), −35% (NFLX), −26% (INTC). Rules, sized by volatility math not opinion:
  1. **Block new entries in any name reporting within the next 3 trading days** (via `get_earnings_calendar`).
  2. **Halve any position >10% of equity before the print** — cap per-name exposure so a 3σ (~15–20%) earnings gap costs **<2.5% of account equity**.
  3. Monitoring-only scope beyond earnings: flag halts, M&A, delistings, corporate actions on current holdings pre-order. Escalate to the risk gate; never override systematic rules.

---

## 5. Eval Spec

**Data:** 10 years of monthly observations = **120 obs** (the binding constraint; effective cross-sectional breadth is a small multiple, not 200×). At N=200 trials, the expected max **pure-noise** Sharpe ≈ √(2 ln N) scaling ⇒ **~1.0 annualized** — a tournament winner at SR ~1 is exactly what luck predicts. MinTRL (95% conf vs SR*=0): SR 1.0 → ~33 months; SR 0.7 → ~6y; SR 0.5 → ~11y.

**Splits:**
1. **DEV:** months 1–72 (2016-08 → 2022-07). Unrestricted exploration; directional only (max survivorship contamination lives here).
2. **Walk-forward (primary scoreboard):** expanding window, first train-end 2020-07, step 6 months (train → trade 6 months), through 2025-01 ⇒ **~54 concatenated OOS months**. Configs ranked on this, never on DEV.
3. **Holdout:** final **18 months (2025-02 → 2026-07), locked**, touched once by at most the **top 3** configs. **Veto-only gate** (kill on sign flip or DD > 1.5× walk-forward max) — 18 obs can never confirm.
4. **CPCV diagnostic:** 12 blocks choose 2, 1-month embargo, months 1–102, all configs ⇒ **PBO; if PBO > 50% for a family, that family is noise — stop.**

**Survivorship haircut policy:**
- Track B full-period: subtract **2 pp/yr CAGR** (delisting bias, upper end — top-200-today is a momentum-selected universe), then haircut remaining excess-over-SPY by **50%** (membership effect; S&P 100 26%→12.2% evidence). Flag any config whose profit concentrates in buying 3+ month losers as high-bias.
- Track B recent-3y (nearly clean, ~4–5%/yr attrition): haircut excess by **25%** only (Harvey-Liu nonlinear schedule for SR ~1).
- Decision weighting: **70/30** toward (recent-3y + walk-forward OOS) vs full-period.
- Track A: no instrument-level haircut, but **published-strategy Sharpe halves OOS** (McLean-Pontiff confirmed in the TAA class) — apply 50% to published/backtest Sharpe, and require ±1-parameter-step neighborhood robustness (the best OOS predictor in the TAA literature).

**Gates (all must pass):**
- **G1:** Deflated Sharpe Ratio ≥ 0.95 on concatenated WF OOS months, with **N_eff from hierarchical clustering** of config return correlations (expect ~15–50 for ~84 correlated configs; document it).
- **G2:** OOS net-of-cost, post-haircut annualized Sharpe **≥ 1.0** AND beats SPY buy-and-hold on the same months.
- **G3:** t ≥ **3.0** on OOS mean excess (Harvey-Liu-Zhu); report Bonferroni (t=3.66 at N=200) and BH-FDR q=5% verdicts alongside.
- **G4:** Alpha survives regression on Ken French MKT/SMB/HML/MOM/ST-Rev (free, CRSP, survivorship-clean). If the "edge" is just MOM loading — trade MTUM/SPMO at 13–15 bps fee instead.
- **G5:** ETF-track sanity: backtested momentum Sharpe over 2013–2026 must not exceed MTUM/SPMO **live** Sharpe by more than 0.3; excess gap = bias, not skill.
- **G6:** Mega-cap robustness: sign preserved and ≥50% magnitude on cap-weighted top-50 subset (and at N=20 per Section 3).
- **Family-wise final check:** Romano-Wolf stepwise / Hansen SPA vs SPY on any config advanced to holdout.

**Hygiene:** pre-register and freeze the grid before any OOS run; log every config ever evaluated; cap holdout advancement at 3. **Go-live:** all gates + **3–6 month paper/live incubation at minimum size**, pre-committed kill (live Sharpe < 0 over 6m or DD > 1.5× OOS max). Expect realized live ≈ **40–60% of un-haircut backtest excess**. The backtest is a screen, not proof.

---

## 6. Risk Policy JSON ($250, high risk tolerance)

```json
{
  "version": "2.0-equity",
  "account": {"type": "cash", "settlement": "T+1", "equity_usd": 250, "venue_account": "534796784",
    "fractional_shares": true, "leverage": false, "shorting": false},
  "universe": {"scope": "US large-cap equities (top-200 liquid) and major ETFs",
    "min_avg_dollar_volume_usd": 5000000, "min_price_usd": 5, "max_quoted_spread_bps": 10,
    "exclude": ["leveraged_etfs", "otc", "non_fractionable_symbols"]},
  "tracks": {
    "stock_xsec": {"target_positions": 20, "min_positions": 15, "max_positions": 22,
      "target_weight_pct": 5, "max_weight_at_rebalance_pct": 7, "max_weight_drift_pct": 10,
      "max_sector_weight_pct": 30, "min_order_usd": 5,
      "note": "N>=20 per eval lottery-ticket rule; a -26% gap on 5% weight = -1.3% portfolio day"},
    "etf_rotation": {"target_positions": 4, "min_positions": 3, "max_positions": 6,
      "max_weight_at_rebalance_pct": 34, "min_order_usd": 5,
      "note": "single-name caps inapplicable; ETFs internally diversified"}
  },
  "volatility_targeting": {"enabled": true, "target_annual_vol_pct": 25,
    "estimator": "20d_ewma_realized_annualized",
    "exposure_rule": "equity_fraction = min(1.0, target_vol / realized_vol)",
    "floor_exposure_pct": 25, "leverage_cap": 1.0, "note": "downscale-only tail clamp; residual to cash"},
  "regime_filter": {"signal": "SPY_close_vs_200d_SMA", "evaluation": "daily",
    "risk_on": "close > 200dma for 3 consecutive sessions",
    "risk_off": "close < 200dma*0.98 OR close < 200dma for 5 consecutive sessions",
    "risk_off_action": {"max_exposure_pct": 30, "new_buys": false},
    "applies_to": "stock_xsec (ETF track embeds its own trend/canary logic)"},
  "drawdown_kill_switch": {"basis": "daily_close_equity_peak_to_trough",
    "tiers": [
      {"level_pct": -15, "action": "warn; halve vol target to 12.5; tighten regime filter",
       "rationale": "normal correction: SPY -10% every ~1.8y, avg -14%"},
      {"level_pct": -25, "action": "halt new buys; exit weakest 50%; require human ack",
       "rationale": "bear-market depth"},
      {"level_pct": -35, "action": "liquidate all (respect settlement blocks); disable pending manual revalidation",
       "rationale": "average bear trough (-35); beyond = strategy broken"}],
    "relative_tripwire": {"rule": "trailing_90d_return_minus_SPY < -15pp => halt new buys + review",
      "rationale": "separates market-broke from strategy-broke"},
    "single_position_stop": {"exit_if_down_from_entry_pct": -30,
      "note": "gaps uncapped by stops (META -26, NFLX -35, INTC -26 overnight); sizing is the real control"},
    "migration_note": "supersedes flat kill_drawdown 0.30 in config/equity_live.json"},
  "earnings_gap_policy": {"track": "stock_xsec_only",
    "block_new_entry_within_trading_days_of_earnings": 3,
    "trim_rule": "halve any position > 10% of equity before the print",
    "sizing_basis": "earnings-day sigma ~5%, tails 20%+; 3-sigma gap must cost < 2.5% of equity",
    "source": "get_earnings_calendar"},
  "settlement_rules": {"compute_settled_cash_before_buys": true,
    "allow_buys_with_unsettled_proceeds": true,
    "hard_block_sell_of_lots_funded_by_unsettled_cash_until_settled": true,
    "kill_switch_defers_blocked_lots_one_session": true,
    "gfv_failsafe": {"max_gfv_rolling_12m": 2, "action": "settled_cash_only_mode",
      "broker_penalty_at_3": "90d_restriction_bot_death"}},
  "cadence": {"daily": ["mark_equity", "drawdown_check", "regime_check", "vol_check", "stop_check",
      "earnings_calendar_check", "no_trading_unless_triggered"],
    "monthly": {"rebalance_day": "first_trading_day", "min_trade_threshold_usd": 2}},
  "execution": {"order_type": "fractional_dollar_market_regular_hours_only",
    "execution_window_et": "15:30-15:55", "skip_if_quoted_spread_bps_gt": 10,
    "sells_first": true, "max_orders_per_session": "2x max_positions",
    "one_order_per_symbol_side_day": true, "dedupe_key": "trade_date+symbol+side",
    "on_data_failure": "fail_closed_no_trades",
    "on_unparseable_mcp_response": "abort_with_state_note_never_guess"}
}
```

---

## 7. Deployment Architecture — Daily Agent-Session Execution Desk

**Schedule:** `create_trigger` with cron **`30 19 * * 1-5` UTC**, `create_new_session_on_fire=true`, connectors limited to `robinhood-trading` + GitHub. Lands **15:30 EDT / 14:30 EST** — inside the liquid afternoon, past open volatility, matching the backtester's next-bar trade-at-close contract (`quantfirm/equities/backtest.py` lines 5–6), with ≥30 min for sells-then-buys plus 5-minute fractional auto-cancel windows. Accept the DST wobble. Rejected: 10:00 ET (17.5h stale signal + worst spreads) and <15 min pre-close (no retry room). Early closes (2026: Nov 27, Dec 24, 13:00 ET) are skipped by the market-open guard. Daily firing; **most days are monitoring-only** (mark, DD/regime/vol/stop/earnings checks) — trading happens on the monthly rebalance day or on trigger events only.

**Runbook per firing:** (1) fresh clone of main; verify config enabled, state initialized, `state/KILL_SWITCH_EQ` absent (present ⇒ liquidation-only). (2) **Market-open guard:** committed `config/nyse_calendar_2026_2027.json` AND live `get_equity_tradability` / SPY quote fresh ≤2 min; if closed, commit `skipped: market_closed` and exit; `cancel_equity_order` any queued orphan from a crashed run. (3) **Reconcile before planning:** `get_equity_positions` + `get_equity_orders(today)` + `get_accounts`; adopt orphan fills into state via `equity_rebalance.py record`; unexplained settled-cash drift >$1 ⇒ stop, no orders. (4) Refresh panel through yesterday's close (plan refuses stale panels). (5) `equity_rebalance.py plan` — **the printed JSON order list is the contract; the agent places exactly these orders and never improvises.** (6) Write `state/equity_intents.json` and **commit+push before the first placement**. (7) Sells first: dedupe check → `review_equity_order` (any buying-power/tradability warning = hard per-order stop) → `place_equity_order` → poll `get_equity_orders` to terminal (≤5 min) → `record` actual fill → local commit. (8) Push checkpoint; recompute buy budget from **actual** proceeds, clamped to min(plan, venue buying power − $1). (9) Buys via same loop; `mark` with live quotes. (10) Final commit+push with P&L commit message (`eq-rebalance YYYY-MM-DD: equity $X, dd Y%, N orders, skipped M`).

**Idempotency without venue client_order_ids — four layers:**
- **(a) Convergence-by-diff:** every plan is computed against reconciled live positions, so a re-run after partial execution emits only residual deltas — duplicates become structurally impossible once fills are venue-visible.
- **(b) Semantic dedupe key** `(trade_date, symbol, side)`: check intents journal AND `get_equity_orders` for a same-day same-symbol same-side order within ~5% size before placing; hard rule of one order per symbol per side per day (the diff already guarantees one side per symbol).
- **(c) Durable checkpoints:** sessions are fresh clones — anything unpushed dies with the session. Push intents before first order, commit after every fill, push after sells and at end; worst case is fully reconstructible from `get_equity_orders`/`get_equity_positions`.
- **(d) Run-lock:** state showing today complete ⇒ no-op on duplicate fires; git push rejection ⇒ concurrent session ⇒ abort, never force-push.

**Lost-response protocol** (the one place naive retry double-buys): on timeout/unparseable `place_equity_order` response, **never blind-retry**. Poll orders+positions twice ~30s apart; re-place only if provably absent from both; the 5-minute auto-cancel resolves pendings quickly; any shortfall is next session's diff.

**Failure modes → safeguards:** session dies mid-rebalance → next firing reconciles-adopts-replans (worst case one day at intermediate weights, tolerated by design). Undocumented MCP schemas change → validate used fields, abort on mismatch. Buying-power drift → $1 clamp. Drawdown → tiered kill switch (Section 6). Runaway agent → plan-JSON-only orders, per-order dollar caps, 2× max_positions order cap per session, venue-segregated $250 account. GFV → settlement ledger hard blocks (kill-switch liquidations defer unsettled-funded lots one session).

**Implementation delta vs repo:** extend `/home/user/2-3-24VEX/scripts/equity_rebalance.py` with `reconcile` and `intents` subcommands; add `/home/user/2-3-24VEX/config/nyse_calendar_2026_2027.json`; update kill switch in `/home/user/2-3-24VEX/config/equity_live.json` from flat 0.30 to the −15/−25/−35 tiers; encode the runbook verbatim in the trigger's session prompt with standing rules "plan JSON is the only source of orders", "poll-don't-retry", "push before first placement". The crypto desk's `trade.yml` concurrency pattern carries over conceptually, but execution lives in the agent session — only it can call the MCP tools.
