# Research-swarm findings (2026-07-31)

Six parallel researcher agents; full transcripts in the session workflow logs.
What follows is what changed our design.

## 1. How real quant firms actually operate

- Strategy lifecycle is a **gated pipeline designed to kill ideas cheaply**:
  idea → hypothesis-vetted research → cost-aware backtest → independent
  review/sign-off → shadow trading → canary at ~5% size (~2 weeks) → scaled
  production → live-vs-research monitoring → capital cut/deprecation.
- Ideas need a **causal mechanism** (behavioral, structural, flow); pure
  data-mined signals get rejected at review because they fail live.
- **Separation of duties**: researcher proposes, reviewer approves, risk sets
  limits, execution trades, ops reconciles — nobody approves their own work.
  Regulation (MiFID II RTS 6, SEC 15c3-5) forces exactly this shape.
- Risk desks hold **unilateral, automatic, non-appealable** authority with
  three kill layers: per-order pre-trade checks, per-strategy auto-disable,
  and a global kill switch — plus periodic *tests* of the kill switch.
- Maintain a **strategy registry** (inventory, versions, limits, approvals) —
  the Knight Capital lesson: what is deployed must provably match it.

→ Mapped onto our agent desks in `FIRM.md`; the lifecycle states live in
`config/live.json` + PRs; every seat that approves is a different agent than
the one that proposed.

## 2. Robinhood Crypto microstructure (decisive numbers)

- **Limit orders exist on API v1**: `type ∈ {limit, market, stop_limit,
  stop_loss}`; `limit_order_config = {asset_quantity | quote_amount,
  limit_price}`. A limit order **caps your price** — Robinhood fills at your
  limit or better — so resting at/inside mid can recover much of the spread.
- Measured embedded spread (market orders): **0.927% per side**. Correct
  break-even mid-move for a round trip: `(1+s)/(1-s)−1 ≈ 1.87%`.
- **API v2 (exchange routing, Bitstamp/EDX)** charges 0.95% taker / 0.50%
  maker below $10K 30-day volume — *worse* than v1's spread at our size.
  Stay on v1; revisit above $10K/30d volume.
- Per-symbol precision/minimums are served by `GET /trading_pairs/`
  (BTC: min 0.000001, increment 1e-8) — engine fetches them before every
  order (never hardcoded).
- At ~2% BTC daily vol, the 1.87% break-even ≈ one daily sigma → **intraday
  and daily-rebalance strategies are structurally dead** on this venue.

## 3. Strategy evidence (net of ~1.9% round trips)

- **Slow trend-following is the only family with robust surviving evidence.**
  Liu & Tsyvinski (RFS 2021): BTC time-series momentum pays at 1–4 week
  horizons. Slow MA crossovers / Donchian flip 2–10×/yr → cost drag 4–18%/yr
  vs historical gross trend legs of 20–100%+.
- **Vol targeting** reliably improves risk-adjusted returns and tail behavior
  (regime study: Sharpe 0.89 vs 0.61 B&H, maxDD −21% vs −53%); modest alpha,
  big drawdown reduction — ideal overlay.
- **Short-term mean reversion: dead at these costs** (gross edge/trade
  0.3–1.5% < one round trip). Cross-sectional coin momentum: weak once
  realistic costs/universes imposed. Intraday breakout: categorically dead.
- Classic crypto backtest traps: 2020–21 bull-regime luck, lookahead,
  same-bar fills, ignoring spread. Standards: walk-forward (IS:OOS ~4:1),
  purge/embargo, WFE ≥ 0.5, and multiple-testing penalties.

## 4. Risk numbers for a $250 self-funded book

- **Full Kelly is ruinous by construction**: P(ever hitting x of peak) =
  x^(2/f−1); half-Kelly cuts P(50% DD) from 50% → 12.5%. Practitioner ceiling
  0.25–0.5× Kelly, especially with noisy crypto edge estimates.
- Vol targeting ≈ Kelly in disguise: target vol ≈ SR × 100% at full Kelly →
  25–35% annualized target vol is the sane band for an assumed SR ~0.5–0.7.
- Prop-firm analogs: 4–5% daily loss limit, 8–10% lifetime max drawdown,
  automated enforcement. Our config (high-risk mandate accepted): soft
  regime — vol targeting sizes down in chaos; hard kill at **−40% from peak**
  (user-approved risk appetite; risk desk recommended −25%, noted for the
  record), stale-data refusal, per-order caps, venue-side duplicate
  rejection.

## 5. The eval (anti-overfitting core)

- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014): penalizes the
  expected max Sharpe of N trials of noise; the tournament counts EVERY trial
  toward N. Paper's example: SR 2.5 found after 100 trials → rejected at 95%.
- **PBO/CSCV** (2017) and Harvey-Liu t≥3.0 as future gates for the research
  desk once trial history accumulates.
- Walk-forward OOS net Sharpe (5 folds) + one-shot referee-only holdout
  (2025-07→2026-06) + ±25% parameter perturbation + adversarial refutation =
  this round's approval gauntlet (see `PROCESS.md` §"The eval").

## 6. Deployment ops (GitHub Actions)

- Cron is best-effort: 3–15 min drift routine, worse at minute 0 / 00:00 UTC;
  <5 min intervals silently never fire. **Hourly at an off-peak minute** is
  the sweet spot → `'7 * * * *'`.
- `concurrency: {group, cancel-in-progress: false}` = overlapping runs queue,
  never killed mid-order. Engine must assume ticks arrive late or not at all
  (idempotent per bar; missed tick = safe).
- Authoritative state as a committed JSON file (pull-rebase + push-retry);
  actions/cache and artifacts are both unfit for authoritative books.
- Secrets: libsodium-sealed, log-masked (masking defeated by transforms —
  never print/transform them), absent in fork-triggered runs. Keep the repo
  private (free minutes + state privacy).
