# KALSHI 15M METALS DESK — research charter & venue dossier

Status: **PAPER** (shadow vs prod book + demo-env plumbing). No real money.
Built 2026-09-10 on branch `claude/kalshi-commodity-strategy-sr27jr`.

## 1. The instrument

`KXGOLD15M / KXSILVER15M / KXCOPPER15M`: one $1 binary per 15-minute window —
"will the Pyth metals index close this window at or above its open print?"
(`strike_type: greater_or_equal`, tie → YES). Strike = Pyth 1-min candle close
at window open (public immediately); settlement = the 1-min close at window
close; both 2dp-rounded. Settlement sources: Pyth `Metal.Index.GOLD/USD`
(USD/t.oz), `Metal.Index.SILVER/USD`, `Commodities.Index.CU/USD` (USD/lb).

Hours (empirical, from the full print history): windows every :00/:15/:30/:45,
~96/weekday; dark Sat 04:00Z → Sun 22:00Z and Thu 07:00–09:00Z (exchange
maintenance). Series live since 2026-07-31 (gold/silver) and 2026-08-27
(copper). Liquidity (prod, Sep 2026): gold ≈ 190k contracts/window, 1¢
spreads near the money, deci-cent ticks in the wings; silver ≈ 50k; copper ≈ 19k.

Fees (verified per-series): `fee_type quadratic, multiplier 1` → taker
`ceil(0.07·C·P·(1−P))` (≤ 1.75¢/contract at P=0.50), **maker $0, no
settlement fee**. A taker entry held to settlement pays exactly one fee.

## 2. Venue mechanics that matter

* Public market data (markets, orderbook, candlesticks, trades) needs **no
  credentials** on prod AND demo. All prices are decimal STRINGS
  (`*_dollars`/`*_fp`); legacy integer-cent fields are null.
* Order writes: V2 only — `POST /portfolio/events/orders` (`side: bid|ask` in
  YES-price terms, fixed-point strings, `time_in_force` required, no market
  orders — use aggressive limit + IOC). Legacy `/portfolio/orders` → HTTP 410.
* Auth: per-request RSA-PSS(SHA-256) over `ts_ms + METHOD + path` (no query),
  headers `KALSHI-ACCESS-KEY/-SIGNATURE/-TIMESTAMP`.
* Demo env (`demo-api.kalshi.co`) mirrors prod tickers/strikes for metals but
  its books are empty/fake: **demo validates order plumbing only; economics
  are measured against prod public data.**
* Rate limits: token bucket, ~20 reads/s + 10 writes/s at Basic; free
  self-serve upgrade to Advanced via `POST /account/api_usage_level/upgrade`.

## 3. Strategy (pre-registered; quantfirm/kalshi/strategy.py is the spec)

**Oracle repricer (S1)** with flow-fade tagging (S3) and macro gates (S4):
fair value `P = N(ln(S/K)/(σ₁ₘ√τ))` with a causal EWMA 1-min vol ×
hour-of-week diurnal multiplier; S from a real-time settlement proxy
(Swissquote XAU/XAG, measured ~1 bp from the Pyth print; copper has no
keyless realtime feed and is DISABLED for live entries). Enter taker-only
when the executable price diverges from fair by ≥ θ net of fee, inside the
τ/price/spread/liquidity gates; hold to settlement (no exit fee). Sizing:
quarter-Kelly capped at 5% of bankroll/trade; ≤ 2 concurrent positions;
gold+silver same-direction share one slot; −10%/day stop halts entries.

Why it can earn: the strike is public, a ~1 bp settlement proxy exists, much
of the flow is slower/retail, and near expiry small spot moves imply large
fair-value moves. Whelan's 313k-obs Kalshi study: makers/favorites earn,
longshot takers lose >60% — our gates put us on the right side of that.

Evidence base for the S1/S3 archetype: Turbine Research's 4,904-variant sweep
on KXBTC15M (the crypto analog) — regime-conditioned fades of contract-price
spikes were the ONLY surviving family (93/96 variants profitable); naive
mean-reversion went 0-for-432. Our own calibration measurement (gold, ~3,880
windows): longshots overpriced ~2.3¢ at τ=10min (mild FLB, fee-scale — bias
harvesting alone is NOT enough, divergence-taking is required).

## 4. Backtest protocol & honesty constraints

Data: full settled-market history + per-market 1-min contract candles
(yes_bid/yes_ask OHLC) from the public API; underlying = GC=F/SI=F/HG=F
1-min bars (Yahoo), re-anchored to the settlement print at every window open
(`S_t = F_t · K/F_open`), so basis error is intra-window drift only (~1-2 bp).

* Strictly causal: vol state sees only past bars; decisions use the candle
  closing at T; fills require the NEXT candle's side-price open to be at or
  inside our limit (book gaps away → no fill).
* Fees: conservative cent-ceiling per order. Fill-only-at-limit and
  slippage stress variants (`--slippage-extra`).
* Train/test: split fixed BEFORE sweeping at 2026-08-27T00:00Z; parameter
  selection on train only; the chosen config evaluated ONCE on test.
* Known optimism that a 1-min grid cannot remove: sub-minute sniping
  competition is invisible; treat backtest results as an upper bound and
  gate go-live on live SHADOW results (prod-book fills, recorded live).

Findings that shaped the gates (train-split autopsy, gold): entries in the
first ~3 minutes of a window and longshot buys (price < 0.30) are reliably
negative (model-vol error and FLB, respectively); the τ 5–9 min mid-window
band carried the edge in both regimes. August (weeks 33–34) was net negative
at loose gates: the 15M books matured through August — early-sample results
underweight today's liquidity.

## 5. Results

See `research/kalshi_backtest.md` (generated) for the current numbers:
train sweep table, chosen config, single test-split evaluation, stress
variants, and live shadow-session results. Numbers in this file are not
repeated to avoid staleness.

## 6. Running it

```bash
# data refresh (public API, ~30-40 min cold, resume-safe)
python scripts/kalshi_harvest.py --gzip

# venue/feed health, credential check
python -m quantfirm.kalshi.cli status

# backtest / sweep / calibration
python -m quantfirm.kalshi.cli backtest --data data/kalshi --split test
python -m quantfirm.kalshi.cli sweep --data data/kalshi
python -m quantfirm.kalshi.cli calibrate --data data/kalshi

# live paper session (shadow vs prod book; demo orders too if creds present)
python -m quantfirm.kalshi.cli paper --minutes 60 --log-decisions
```

## 7. Demo-env credentials (the one manual step)

The first demo API key cannot be created programmatically (web UI only,
behind WAF + device fingerprinting — automating that is out of bounds).
One-time setup:
1. Sign up at https://demo.kalshi.co/sign-up (mock info is allowed on demo).
2. Deposit mock funds (test card `4000 0566 5566 5556`, any future expiry).
3. Profile settings → API keys → create; download the private key PEM once.
4. `export KALSHI_DEMO_KEY_ID=...` and
   `KALSHI_DEMO_PRIVATE_KEY_PATH=/path/to/key.pem` (or put the PEM in
   `KALSHI_DEMO_PRIVATE_KEY`). `.gitignore` already excludes `*.pem`.
Then `python -m quantfirm.kalshi.cli paper` places real IOC orders on demo
alongside the shadow record. Until then the engine runs shadow-only.

## 8. Risk & promotion

This desk follows the firm ladder: PAPER (now) → CANARY → PRODUCTION only
via referee sign-off (docs/FIRM.md). Go-live additionally requires: ≥ 2 weeks
of live shadow P&L consistent with backtest at matched gates, demo plumbing
green (orders, cancels, settlement accounting), and the Pyth/`pyth_value`
WS latency question answered. Real-money Kalshi needs KYC + ACH funding and
is explicitly out of scope for this branch.
