# Build log — how this firm was built (by agents, 2026-07-31)

This documents the actual process, as it happened, one session, agent-swarm
driven end to end. Timestamps UTC.

## 1. Credential bootstrap (07:30–07:45)
- Generated Ed25519 keypair (OpenSSL; raw 32-byte keys base64-encoded).
- User registered the public key in the Robinhood credentials portal.
- Verified the credential with a signed `GET /accounts/` (HTTP 200), then
  placed a $1 market BTC-USD test buy via the API (filled; cash 1.01 → 0.01).
- Findings that shaped the design: market orders require `asset_quantity`
  (no dollar-notional market orders via API); measured embedded spread
  ≈ 0.93% per side; orders/holdings read endpoints returned empty for this
  credential (permission scoping) — the engine therefore keeps its own books.

## 2. Environment recon (08:00)
- Egress test: `data.binance.vision` (historical dumps) and `api.kraken.com`
  (live candles) reachable; `api.binance.com` geo-blocked (451).
- Python 3.11 + pandas installed in-session.

## 3. Research swarm (08:00–, 7 agents)
Parallel researchers with web access: quant-firm operating processes
(Jane St/HRT-style), Robinhood cost microstructure, strategy families that
survive ~1.9% round trips, risk standards, agentic-eval design (deflated
Sharpe, PBO), GitHub Actions deployment ops. Synthesised into `FIRM.md`.

## 4. Engineering (08:00–08:15)
- Downloaded 7.5 years of hourly candles (BTC 65,653 bars; ETH; SOL) from
  Binance public dumps.
- Built `quantfirm/`: cost models, metrics (incl. deflated Sharpe), vectorised
  long-only backtester with walk-forward folds and a dev/holdout split
  (holdout = 2025-07 onward, reserved for the judge), strategy registry,
  baseline strategies, JSON CLI for agents, risk policy, signed API client,
  idempotent hourly execution engine, state management, CI workflows.
- Invariant tests: lookahead guard, cost accounting, deterministic order IDs,
  risk blocks — all passing.

## 5. Baseline reality check (08:10)
Walk-forward, BTC dev period, full market costs (0.93%/side):

| strategy | oos Sharpe | maxDD | turnover/yr |
|---|---|---|---|
| buy_and_hold (net, full sample) | 1.12 | −77% | 0 |
| trend_vol_composite | 1.11 | −58% | 19 |
| vol_target_hold | 1.10 | −62% | 6 |
| donchian | 0.72 | −76% | 17 |
| ma_cross | 0.66 | −72% | 30 |
| tsmom (fast) | **−0.75** | −99% | 114 |

Lesson: at this cost level turnover kills; the bar for "alpha" is beating
vol-scaled buy-and-hold, which is genuinely hard.

## 6. Strategy tournament swarm (08:20–, 8 agents)
Five designer agents (slow-trend, vol-regime, breakout-hold, ensemble,
crash-filter desks), each optimizing the same eval: out-of-sample walk-forward
net Sharpe on dev data, trial counts reported for deflated-Sharpe penalties,
holdout untouched. A judge agent then ran the one-shot holdout year
(2025-07→2026-06), cost/fragility/causality audits, and picked the production
strategy; two adversarial agents attempted refutation. Results:
`docs/TOURNAMENT.md`.

## 7. Deployment
GitHub Actions = execution desk (hourly) + research desk (nightly); Claude
Routines = risk committee & research review sessions on schedules; state and
books committed to the repo, kill-switch file honored by every run.

## The eval (the thing that makes the swarm work)
A candidate strategy is approved only if ALL hold:
1. Walk-forward out-of-sample net Sharpe (5 folds, dev) beats baselines under
   `rh_market` costs (0.93%/side),
2. Holdout year (never seen by any designer) Sharpe retains >50% of dev,
3. Survives parameter ±25% perturbation without >50% collapse,
4. Deflated Sharpe probability ≥ 0.95 given the tournament's TOTAL trial
   count,
5. Two adversarial agents fail to refute (lookahead, regime luck, fragility,
   production practicality).
