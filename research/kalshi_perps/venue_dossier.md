# Kalshi perpetual futures — venue dossier (as of 2026-09-15)

Condensed from three research passes (public API pulls, docs.kalshi.com, the
Kalshi help center, CFTC filings, press) on 2026-09-14/15. Live numbers were
read from the unauthenticated `/margin` endpoints and will drift; the rules
come from filings and are stable until refiled. Anything not from a primary
source is marked [secondary].

## Product

* "Perps", "margin" and "perpetual futures" are one product; the API says
  *margin*. Listed by KalshiEX LLC (CFTC DCM), cleared by Kalshi Klear LLC
  (DCO, amended order 2026-04-15), retail intermediated by the FCM Kalshi
  Prime (NFA registrant Kinetic Markets LLC, 2026-03-24) [secondary on the
  naming]. CFTC approved BTCPERP under Reg 40.3 on 2026-05-29
  (https://www.cftc.gov/PressRoom/PressReleases/9240-26); BTC live 2026-06-03;
  altcoins self-certified 2026-06-01 (https://www.cftc.gov/filings/ptc/ptc0601264824.pdf);
  gold and silver self-certified 2026-09-08 and live 2026-09-10
  (https://www.cftc.gov/filings/ptc/ptc09082624176.pdf, .../ptc09082624183.pdf).
* 20 active contracts (18 crypto + gold + silver); DOT/HBAR/XLM listed but
  inactive. Filed and pending: copper (Pyth XCU/USD, Sun 18:00–Fri 17:00 ET),
  US500 (MerQube index), WTI; ~60 single-stock perps announced 2026-09-11.
  Live list: https://external-api.kalshi.com/trade-api/v2/margin/markets
* Contract sizes: BTC 0.0001 BTC (~$7.8), ETH 0.001, SOL 0.1, XRP 1, gold
  0.001 troy oz (~$4.3), silver 0.1 oz (~$6.3). Tick $0.0001 on every
  market; whole contracts only (`fractional_trading_enabled=false`).
* Litigation risk: CME Group v. CFTC (D.D.C. 1:26-cv-02157, filed
  2026-06-18) argues perps are swaps; CFTC moved to dismiss 2026-09-02. If
  CME wins, the product could change or stop.

## Margin and liquidation

* `GET /margin/risk_parameters` (public): initial margin = maintenance × 1.3
  on every market; liquidation when margin ratio (maintenance / equity)
  reaches 1.0; liquidation queue at 0.91.
* Maintenance rates are published as `leverage_estimates` (1/rate) by
  notional size. At $1k notional on 2026-09-14: BTC 6.05x (16.5%), ETH 4.66x
  (21.5%), SOL 3.02x, XRP 2.79x, gold 15.26x (6.6%), silver 7.79x (12.8%).
  Leverage falls with size (BTC 5.89x at $1M). Max leverage at ENTRY is
  therefore 1/(1.3 × maintenance): BTC 4.65x, ETH 3.6x, gold 11.7x.
* Isolated margin in the apps; portfolio (cross within asset class) margin
  for API accounts (`is_portfolio`). Kalshi Klear liquidates with market
  orders; leftover margin returned; deficits absorbed by the default-fund
  waterfall; disclosures say a gap can leave a negative balance [secondary].
  No liquidation fee is published anywhere.
* Variation margin settles twice daily (~12:00 and 16:00 ET); unsettled P&L
  is not withdrawable until the next cycle.
* Idle margin earns ~3.25% APY "subject to market conditions"
  (https://help.kalshi.com/en/articles/15357608-your-perpetuals-margin-account);
  third parties add daily accrual, monthly payment, $250 minimum average
  balance [secondary].
* Default per-market notional risk limit for new accounts ≈ $5,000
  (`GET /margin/notional_risk_limit`).

## Funding

* Crypto: three intervals a day ending 00:00 / 08:00 / 16:00 ET (04/12/20
  UTC in EDT). Rate = premium of the perp vs the CF Benchmarks real-time
  index, recency-weighted per second over the interval (the filed T&C say
  "this is not a TWAP"; the help center says TWAP of 1-minute premiums).
  Deadband: |rate| < 0.01% → 0. Cap ±2% per interval. No interest-rate term.
  Longs pay when positive. Paid on positions open at the timestamp.
* Metals: once a day at 10:00 ET (14:00 UTC), weekdays (weekend rows print
  zero); per-minute premiums equal-weighted; deadband 0.002%; cap ±2%;
  reference Pyth XAU/USD and XAG/USD.
* Realized since launch (4,036 intervals to 2026-09-14): BTC mean +0.72 bp
  per 8h (+7.9%/yr) with 55% of intervals exactly zero and 44.5% positive;
  ETH −0.16 bp (−1.8%/yr, 87% zero); SOL ≈ 0; XRP +1.9%/yr; most small alts
  slightly negative. The ±2% cap has bound once (VVV's first print). BTC by
  month: Jun +5.7%, Jul +2.7%, Aug +11.8%, Sep +14.8% annualized. Gold and
  silver have four prints each.
* Cross-venue (same months): Hyperliquid ETH paid +8.6–9.6%/yr while Kalshi
  ETH paid ≈ 0 to −2%; Kalshi BTC was below offshore in July and above in
  Aug/Sep. Exploiting this needs an offshore leg a US retail account cannot
  hold, and the spread is smaller than two taker fees at tier 0.
* Consequence for a small book: funding is not a return source here and is
  a near-zero holding cost. The backtests run both Kalshi's own history and
  Binance's funding history passed through Kalshi's deadband as a stress.

## Fees (CFTC filing 2026-06-24, https://www.cftc.gov/filings/orgrules/rules0624267243.pdf)

| tier | 30-day perps + prediction volume | taker | maker |
|---|---|---|---|
| 0 | $0 | 12.0 bps | 5.0 bps |
| 1 | ≥ $100k | 10.0 | 4.0 |
| 2 | ≥ $300k | 8.0 | 3.2 |
| 3 | ≥ $1M | 6.0 | 2.4 |
| 4 | ≥ $3M | 5.0 | 2.0 |
| 5–10 | ≥ $10M … ≥ $3B | 4.0 → 2.6 | 1.6 → 0.6 |

Charged on notional at trade time, on open and on close. A round trip at
tier 0 is 24 bps of notional (1.44% of margin at 6x). Maker fee is positive
at every tier (no rebates). The launch zero-fee promotion has ended
[secondary]. `GET /margin/fee_tiers` (auth) returns the account's effective
rates.

## Market quality (2026-09-15, quiet US-night hour)

| contract | spread | depth within ±5 bp | depth within ±50 bp | 24h notional | OI |
|---|---|---|---|---|---|
| BTC | 0.26–0.5 bps | ~$1.2M/side | ~$13M/side | $565M | $9.7M |
| ETH | 0.4 bps (1 tick) | ~$0.4M/side | ~$12M/side | $546M | $3.4M |
| gold | 0.5 bps | ~$0.2–0.3M/side | ~$1.3M/side | $18M | $2.3M |
| silver | 1.6–4 bps | ~$0.2M/side | ~$1.3M/side | $19M | $0.8M |
| XRP / SOL | 3–4 bps | ~$10–40k/side | ~$2M/side | $35M / $15M | $1.5M / $1.0M |

Platform 24h notional ≈ $1.2B (BTC+ETH ≈ 90%), OI $25–30M (ATH $30.4M on
2026-09-13), volume/OI ≈ 25–50× a day. GSR is a disclosed liquidity provider
(https://www.gsr.io/insights/gsr-provides-liquidity-to-kalshis-perpetual-futures-markets).
Spreads were widest in July (BTC median 1.6 bps) when volume troughed.
Metals tape is retail-sized (median trade ≈ $50). For a book under
$5k the realistic slippage is the half-spread: 0.2–2 bps, well inside the
2.5 bps the cost model assumes.

## Hours and maintenance

24/7 for every listed perp, including gold and silver (weekend gold volume
$1.6–3.2M/day). Exchange maintenance Thursday 03:00–05:00 ET: no new or
amended orders, cancels allowed, marks frozen, liquidation monitoring
paused, funding due in the window processed at reopen. Orders can carry
`cancel_order_on_pause`.

## API (write code against this)

* REST prod `https://external-api.kalshi.com/trade-api/v2/margin/…`, demo
  `https://external-api.demo.kalshi.co/…` (demo tickers end in `1`, e.g.
  `KXBTCPERP1`; demo books are synthetic). WS
  `wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin` (signed
  handshake even for public channels; `ticker` carries `funding_rate` and
  `next_funding_time_ms`).
* Auth: RSA-PSS SHA-256 over `ts_ms + METHOD + path` (full path, no query),
  headers `KALSHI-ACCESS-KEY / -SIGNATURE / -TIMESTAMP`. Kalshi recommends a
  dedicated perps key; scopes exist (`write::trade` without transfers).
* Public, keyless: markets, market, orderbook, candlesticks (1/60/1440 min
  with bid/ask/price OHLC, notional volume, OI; history back to launch),
  trades, funding history/estimate, risk parameters, exchange status.
* Orders: `POST /margin/orders` — limit only; `side` bid|ask; `count` and
  `price` fixed-point strings; `time_in_force` fill_or_kill |
  good_till_canceled | immediate_or_cancel; `post_only`; `reduce_only` (IOC/
  FOK only); `client_order_id` required; `self_trade_prevention_type`
  required. No market orders: use an aggressive IOC limit inside the price
  band (bids ≥ min(80% of best bid, best bid − 1000 ticks); asks ≤ max(120%
  of best ask, best ask + 1000 ticks)). No batch orders on margin.
* Exit triggers (server-side stop-loss / take-profit / trailing, fire
  reduce-only orders on the liquidation mark): `PUT /margin/{isolated|cross}/
  positions/{ticker}/exit_trigger`. API accounts are portfolio-margined →
  `cross`.
* Account: `/margin/balance` (5 tokens; 50 with available balance),
  `/margin/positions`, `/margin/risk` (per-position `estimated_liquidation_price`),
  `/margin/fee_tiers`, `/margin/funding_history`, `/account/limits/perps`.
* Rate limits: token buckets, 10 tokens per request, Basic tier 200 read /
  100 write tokens per second, perps in their own buckets; cancels cost 1
  token; 429 with no Retry-After.
* Liquidations and trigger fills arrive as fills with `order_source=system`.

## Eligibility

US residents, KYC, a separate margin-account application (questionnaire +
mandatory tutorial, can be declined), separate margin balance funded by
ACH/wire or transfer from the predictions balance in the app. The API
transfer endpoint is documented as not yet available.
