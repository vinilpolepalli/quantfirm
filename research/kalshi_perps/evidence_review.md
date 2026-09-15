# What the evidence says about trading perps with a small account and agents

Condensed from the research passes of 2026-09-15 (academic papers, exchange
research, live track records, agent trading competitions). Grades: A =
several independent studies with costs and live corroboration; B = solid
evidence with cost or sample caveats; C = thin or mixed; D = vendor/anecdote
or evidence points the other way.

## 1. LLMs in the order path — D

* nof1 Alpha Arena Season 1 (Oct–Nov 2025, real money, Hyperliquid perps):
  four of six frontier models lost 31–63% in 17 days; the winner paid ~6% of
  capital in fees in two weeks (https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/).
  Season 1.5: about a third of $320k lost, 6 of 32 accounts profitable, one
  model placed 1,418 trades in a round (https://www.zerohedge.com/markets/wall-street-keeps-testing-ai-traders-most-are-still-underperforming).
  nof1's founder: "Handing money directly to an LLM and letting it trade on
  its own — that path doesn't work yet."
* Replay study on Binance perps: an ungated LLM agent's max drawdown 46% vs
  3% with deterministic gating (https://arxiv.org/html/2603.10092v1).
  StockBench: most agents fail to beat equal-weight buy-and-hold
  (https://arxiv.org/abs/2510.02209). Agent Market Arena: architecture
  explains more variance than model choice (https://arxiv.org/html/2510.11695).
* Anthropic's Project Vend: profitability came from mandatory procedures and
  tooling, not from the agent's judgement; agents stayed persuadable
  (https://www.anthropic.com/research/project-vend-2).
* Consequence: the LLM does research, review and supervision; code decides
  and executes; limits change only by reviewed commit. This firm already
  runs that way (docs/FIRM.md) and the perps desk keeps it.

## 2. Trend / time-series momentum — B for existence, C for net size

* Cross-asset: Moskowitz–Ooi–Pedersen (58 futures, 1985–2009) and Hurst–
  Ooi–Pedersen (1903–2012, Sharpe ~1.0 net of 2/20; authors' forward
  assumption 0.4). Crypto: Liu–Tsyvinski (1–4 week momentum), Borri et al.
  2025; Han–Kang–Ryu: with realistic costs and intra-period moves "many
  momentum portfolios are liquidated", time-series momentum survives,
  cross-sectional does not (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565).
* Live analog: Bitwise Trendwise ETFs (10/20-day EMA, since Dec 2024) lost
  11–15% over the last year while BTC lost 32% — drawdown mitigation, not
  monthly consistency.
* Realistic expectation for a small account: Sharpe 0.4–0.8 net, 8–15%/yr at
  a 20–25% vol target, 15–25% drawdowns, 4–15 trades a year per asset.

## 3. Volatility targeting — B

Moreira–Muir; Harvey et al. 2018 (60 assets to 1926: cuts tails everywhere,
raises Sharpe for risk assets); Man Group: scaling BTC to a 30% target added
~0.4 Sharpe 2012–2024 (https://www.man.com/insights/crypto-too-hot-to-handle).
This is the account's risk engine, not a return source.

## 4. Funding carry — dead on Kalshi, compressed everywhere

* Existence is well documented (BIS WP 1087: average >10%/yr historically,
  up to 60%; high carry predicts crashes). Borri et al.: carry Sharpe 6.45
  gross 2020–25, falling to 4.06 from 2024 and negative in 2025. 2026: basis
  below 2-year Treasuries Feb–Jul (Glassnode week 30). He–Manela–Ross–von
  Wachter with retail fees: Sharpe 1.8, 6.4%/yr, active 20% of the time,
  0.3–1.1%/yr in 2022–23 (https://arxiv.org/abs/2212.06888).
* On Kalshi the 0.01%-per-interval deadband zeroes 55–97% of intervals and
  the collateral already earns 3.25%: there is nothing to harvest. The
  cross-venue version needs an offshore short, which a US retail account
  cannot hold.

## 5. Market making, fast mean reversion, cross-venue arb — D at this size

No rebates below ~0.5% of venue maker volume; adverse selection is the whole
game (Multicoin, Barone–Lillo on Hyperliquid); cross-sectional 8-hour
screens net Sharpe −2.9 to −3.2 (SSRN 6701738); cross-venue funding arb has
forced exits in 95% of opportunities (MDPI 2026) and a practical floor of
tens of thousands per leg. Kalshi-specific memos reached the same conclusion
("stale-quote, basis-fade, lead-lag and funding-carry unprofitable after
fees", https://github.com/michaelcortese/hedge/blob/main/docs/PERP_STRATEGY.md;
"zero confirmed tradeable strategies as of 2026-08-10",
https://github.com/lingxiaoxu/someopark-test/blob/main/crypto_trading/README.md).

## 6. Leverage and liquidation — A that most lose, B on the numbers

* Bybit BTC perps 2020–21 (Alexander, Deng & Zou): a 5x long was liquidated
  within 30 days 14% of the time; 20x 57%. Monte Carlo at 50% vol: ≤2x keeps
  the 90-day liquidation probability under ~1%; 3x ≈ 13%; 5x ≈ 40%.
* Retail: 97% of persistent Brazilian day traders lost (Chague et al.);
  Taiwan day traders net negative every year for 15 years (Barber et al.);
  median Hyperliquid wallet −$67 over 30 days, 1 in 4 lost >85%.
* Consequence: gross leverage ≤ 1.5–2x, sized by vol, with a drawdown
  ladder; the venue's 6x is irrelevant.

## 7. Metals perps — C, pending data

Gold's long-run real return is ~0 (Erb–Harvey) but gold and silver carry
positive 12-month trend in the century-long samples. On Hyperliquid's gold
perp longs paid funding ~97% of hours (≈9%/yr); on Kalshi the deadband makes
fair carry (≈4%/yr ≈ 0.011%/day) print zero most days, so a long gold perp
is roughly a free-carry position — untested, four funding prints exist.
Gold–silver ratio mean reversion: no verifiable evidence (grade D).

## 8. Operating an agent desk — what the incidents teach

* Knight Capital 2012: no automated capital threshold, 97 unread alert
  emails, no second reviewer on deploy (SEC order 34-70694). Translation:
  a pre-trade gate in code, deploy by PR, alerts that page.
* Lobstar Wilde 2026: an agent lost conversational state, mis-modelled its
  balance and sent away ~5% of a token's supply in three days. Translation:
  reconcile against venue truth before every action; halt on mismatch.
* 10 Oct 2025: $19B liquidated in a day, depth fell >90%, cross-margin
  contagion. Translation: liquidation distance ≥ 30%, majors only, isolated
  or tightly capped portfolio margin, no hedged-position leverage.
* Schedulers: GitHub Actions cron can be delayed hours or dropped; Claude
  Routines have a 1-hour floor. Fine for research and a paper heartbeat;
  a live leveraged book needs a daemon on a host you control plus an
  external dead-man's switch (Healthchecks.io style).
* Kalshi gives server-side exit triggers, price banding, `reduce_only`,
  `cancel_order_on_pause`, per-account notional limits and a clearinghouse —
  more venue-side backstops than any offshore perp venue.

## 9. Validation

Deflated Sharpe (Bailey & López de Prado), CSCV probability of backtest
overfitting (Bailey, Borwein, López de Prado, Zhu; customary reject > 0.05–
0.10), Harvey–Liu multiple-testing haircuts, Arnott–Harvey–Markowitz
protocol ("the only true out of sample is the live trading experience").
Small shops that survive keep an append-only trial ledger, freeze the
hypothesis before the first run, and incubate live without money for 3–12
months (Kevin Davey's process). This desk's tournament implements the first
three and its rollout implements the last.
