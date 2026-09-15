# kalshi_micro — Kalshi-native intraday microstructure (EXPLORATORY, not promotable)

**1. Hypothesis, mechanism, evidence.** A three-month-old, retail-heavy venue with 12 bps taker fees might misprice against the deep offshore market for hours (Makarov & Schoar 2020, *JFE*, "Trading and arbitrage in cryptocurrency markets", document persistent cross-exchange gaps), drift into its three daily funding prints, or show timeable hour/day seasonality. An idea matters only if its gross effect beats 2× the round trip: 24 bps fees + quoted spread = 24.5 bps (BTC) / 25.1 (ETH), so ≈49–50 bps. Venue facts from `venue_dossier.md`. With 2,434 BTC/ETH hours and 4.5 days of gold/silver, nothing here can be promoted.

**2. Data, causality.** Kalshi 60-min candles (end-stamped; price = mid of bid/ask closes) for all 20 perps to 2026-09-15 00:00 UTC; Binance USDT-perp 1h bars (open-stamped, relabelled +1h: return correlation 0.9985 at that alignment, ≈0 otherwise) and premium index to 2026-08-31; Kalshi funding history (310 prints each) via `MarginClient.funding_history`. Thursday 07:00–09:00 UTC maintenance candles excluded (frozen quotes gave one 68 bps "basis" artefact). Signals use candle T and execute at T's closing quote (equal to T+1's opening quote in this feed) at the observed bid/ask plus 12 bps per side; a one-hour-later variant is also run. Code: `kalshi_micro_analysis.py`.

**3. Kalshi–Binance hourly basis (bps).**

| | BTC | ETH |
|---|---|---|
| mean (NW se) / std | −2.02 (0.36) / 3.53 | −3.55 (0.36) / 3.59 |
| Jun / Jul / Aug mean | −3.73 / −2.23 / −0.32 | −4.79 / −4.33 / −1.69 |
| AC(1) / AC(24) | 0.938 / 0.800 | 0.942 / 0.794 |
| AR(1) half-life (2se) | 10.8 h (8.2–15.2) | 11.7 h (9.1–15.8) |
| share \|basis\|>5 / >10 | 0.220 / 0.0099 | 0.338 / 0.0373 |

The level is not a Kalshi mispricing: vs Binance spot-implied (basis + premium index) Kalshi sits −6.29 (BTC) / −8.11 (ETH) bps, consistent with a USDT/USD discount. Only deviations are tradeable: std 3.5 bps, half-life 11 h. Rule: enter at |basis|>k hedged on Binance, exit when the basis crosses 0 (max 72 h), both venues' funding accrued; mean per trade (se):

| | trades/mo | hold | mid capture | gross after spread+funding | net after 24 bps |
|---|---|---|---|---|---|
| BTC k=3 | 14.8 | 36 h | +3.52 (0.53) | +2.12 (0.86) | −21.88 (0.86) |
| BTC k=5 | 6.5 | 49 h | +4.05 (1.02) | +1.72 (1.37) | −22.28 (1.37) |
| BTC k=8 | 2.1 | 66 h | +5.11 (2.26) | +0.13 (2.45) | −23.87 (2.45) |
| ETH k=5 | 9.6 | 56 h | +2.86 (0.77) | +3.23 (1.01) | −20.77 (1.01) |
| ETH k=10 | 1.7 | 68 h | +5.03 (2.53) | +8.26 (3.54) | −15.74 (3.54) |

Share of net-positive trades is 0.00 in every cell. Demeaning by a trailing 168-h mean (k=5: BTC gross +3.22, net −20.78; ETH +1.25, −22.75), executing one hour later (BTC k=5 gross +0.99) or using the spot-implied basis (gross ≈0) changes nothing. Unhedged (Kalshi leg only) per-trade se is 40–370 bps. Gross of a few bps against 24 bps of fees.

**4. Funding timestamps (04/12/20 UTC), Kalshi mid return bps (se).** BTC: hour before +2.53 (2.14, n=309), hour after +2.13 (2.42), other hours −0.05 (1.05, n=1,815). ETH: +3.81 (2.54), +1.77 (3.69), +0.72 (1.41). By realised rate, BTC pre-hour +0.95 (3.33) when rate>0 (n=137), +4.05 (2.81) when zero (n=170), n=2 negative; post-hour −1.87 (3.41) / +5.13 (3.40). ETH rates are 87% zero (4 positive). The basis does not compress into the print (BTC −2.09 at F−1h, −2.00 at F) and sign(basis at F−1h) matches the paid rate's sign 28% of the time (BTC, n=106). Causal pre-funding rule, sign = −sign(basis at F−1h), hold into F: BTC +6.82 (2.39, n=267) mid-to-mid, +5.66 after spread and funding, −18.34 net; ETH +6.90 (2.76), +5.54, −18.46. This is the only |t|>2 effect in the study and it fails inspection: the same-signed Binance return is +6.67 (it is the underlying's move, not Kalshi's); by month it is +14.40 (6.22), +4.62 (3.11), +2.43 (2.80) for BTC and +15.23, +5.05, +1.44 for ETH; the same rule in all other hours gives −1.14 (1.16) BTC / +0.03 (1.54) ETH. Post-funding rule (trade the sign of the rate just paid for one hour): BTC −3.32 (3.30, n=107), ETH +4.54 (14.28, n=34).

**5. Seasonality (UTC).** BTC: no hour-of-day mean with |t|>2 (max 1.92 at hour 21, +7.00 bps); ETH 2 of 24 (hour 23 −12.92 (5.20), hour 12 +8.32 (4.04)), the chance count. Largest session: US 14–22 UTC summed +21.47 (12.52) BTC, +38.58 (21.16) ETH per day, under 2× cost even at face value. No day-of-week mean exceeds 1.7 se. Weekends halve realised vol (BTC mean |ret| 16.2 vs 32.0 bps) and volume ($4.3M vs $12.1M/h) with the median spread unchanged (0.52 vs 0.52). Quoted spread peaks in the candle ending 20:00 UTC (BTC 0.90 vs 0.52 median; ETH 1.35 vs 1.13), the 16:00 ET settlement/funding hour. Gold/silver: weekend volume 99k / 46k per hour vs 564k / 521k, median spread 2.41 / 3.10 vs 0.93 / 2.16 bps, |ret| 3.2 / 4.8 vs 22.9 / 30.1; they moved −13.5 / −28.1 bps Fri 21:00 → Sun 22:00 with the reference closed (n=1).

**6. Lead/lag.** corr(Kalshi_t, Binance_t+j): BTC j=−1 −0.037, j=0 0.9996, j=+1 −0.039; ETH −0.008, 0.9998, −0.012; null band ±0.044 (n≈2,105). Neither venue leads at 1 h. Next-hour return on basis_t (BTC): Kalshi +0.12 (0.34), Binance +0.18 (0.34); the 6%/h basis reversion is split across both venues and undetectable in either. Kalshi return AC(1) (−0.040 BTC, −0.010 ETH) equals Binance's (−0.037, −0.011): no Kalshi-specific bounce.

**7. Quoted spread (ask−bid, bps of mid): monthly median; all-period volume-weighted mean; $ volume/day (k).**

| contract | Jun | Jul | Aug | Sep | vw | $vol/day |
|---|---|---|---|---|---|---|
| BTC | 0.32 | 1.54 | 0.50 | 0.39 | 0.81 | 235,017 |
| ETH | 1.27 | 1.59 | 0.83 | 0.41 | 1.08 | 178,377 |
| HYPE | 2.25 | 2.11 | 3.71 | 5.35 | 3.31 | 12,034 |
| GOLD | – | – | – | 1.61 | 1.35 | 8,602 |
| SILVER | – | – | – | 2.64 | 1.71 | 7,402 |
| SOL | 2.82 | 2.79 | 2.72 | 2.76 | 2.99 | 7,266 |
| XRP | 2.82 | 3.65 | 3.72 | 3.67 | 4.46 | 6,961 |
| ZEC | 4.55 | 5.19 | 5.38 | 12.72 | 8.35 | 6,936 |
| SUI | 3.18 | 3.51 | 3.91 | 12.31 | 5.05 | 4,478 |
| NEAR | 4.97 | 7.76 | 8.53 | 14.92 | 10.50 | 4,051 |
| VVV | – | – | 10.66 | 10.18 | 10.77 | 2,665 |
| DOGE | 3.58 | 4.18 | 6.53 | 6.87 | 4.45 | 2,647 |
| BCH | 5.59 | 7.15 | 7.86 | 13.26 | 8.76 | 2,633 |
| ADA | – | – | 15.11 | 9.68 | 11.60 | 2,577 |
| LTC | 3.62 | 4.33 | 4.27 | 4.89 | 4.12 | 2,130 |
| LINK | 4.57 | 6.56 | 7.38 | 15.82 | 7.63 | 1,912 |
| KSHIB | 4.10 | 10.79 | 10.52 | 13.45 | 9.42 | 1,515 |
| WLD | – | – | 13.68 | 13.41 | 12.21 | 1,278 |
| BNB | – | – | 17.35 | 10.50 | 10.21 | 637 |
| AAVE | – | – | 16.44 | 14.68 | 16.25 | 292 |

The desk pays half of these per side: 0.2–0.6 bps on BTC/ETH, 1.5–8 bps on alts, whose September spreads are widening.

**8. Other native predictors.** Next-hour return on own return, %ΔOI, return×volume-z, spread: every |t|<0.9 (BTC) / <0.7 (ETH). Fading |ret|>60 bps hours: BTC +0.64 (4.64), ETH −2.89 (4.47) mid-to-mid.

**9. Verdict.** NO Kalshi-native intraday idea has a gross effect above 2× round-trip cost (≈49–50 bps). Largest gross effects found: +6.82 bps (pre-funding, June-driven, not Kalshi-specific) and +8.26 (3.54) basis capture on 5 ETH trades. Even at maker fees (10 bps round trip, no spread, fill risk) nothing clears. ~30 cells were tested; one t≈2.9 is the expected false-positive count.

**10. Next, not run.** Sub-hourly basis half-life from Kalshi 1-minute candles and maker fill rates from live book snapshots; both need weeks of ≤2 req/s collection and would be new trials, and the venue needs a year of history before any of this can be promoted.
