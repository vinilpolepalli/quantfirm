# Kalshi diversification — weather, ladders, extra crypto, nowcasts

Researched 2026-09-13. Live `desk_book` is **unchanged** (commodities 8% /
≥75¢, BTC+ETH 4% / ≥75¢, wait 3 min, Poly sit-if-disagree on BTC/ETH).
Nothing here sends live orders except the existing canary.

Reproduce:

```
python3 scripts/kalshi_div_nowcast.py --phase catalog,snapshot,weather,macro,weather-hist,macro-hist,ladder
python3 scripts/kalshi_div_nowcast.py --phase harvest,score,harvest-scout,score-scout --skip-harvest
python3 -m unittest tests.test_kalshi_ladder tests.test_kalshi
```

## What was actually on the venue

14,013 series. Climate and Weather 390, Crypto 273, Economics 780.

Liquid enough to care (open volume at the snapshot):

| book | n_open | volume | structure |
|---|---:|---:|---|
| BTC 15m | 1 | 248k | binary up/down |
| ETH 15m | 1 | 12k | binary |
| XRP 15m | 1 | 6.2k | binary |
| SOL 15m | 1 | 4.0k | binary |
| DOGE 15m | 1 | 2.1k | binary |
| HYPE 15m | 1 | 1.7k | binary |
| BNB 15m | 1 | 681 | binary |
| NEAR 15m | 1 | 447 | binary |
| ZEC 15m | 1 | 425 | binary |
| BTC hourly **range** | 318 | 48k | exclusive, 80–188 legs |
| DOGE hourly range | 128 | 12k | exclusive |
| NYC daily high | 12 | 95k | exclusive integer °F bands |
| Chicago high | 12 | 77k | exclusive bands |
| Boston high | 12 | 20k | exclusive bands |
| CPI Sep/Oct/Nov | 25 | 132k | nested "rise more than X%" |
| GDP (Q3 2026+) | 36 | 295k | nested "real GDP > X%" |
| Payrolls | 39 | 50k | nested |
| Core CPI | 33 | 52k | nested |
| Claims | `KXJOBLESSCLAIMS` | 2k | nested ≥k |

ADA/BCH/TON 15m were dark. SOL hourly range had **0** open. Hurricane landfall
series were dark (seasonal). NYC daily rain was dark. Claims ticker is
`KXJOBLESSCLAIMS`, not `KXJOBLESS`.

Daily highs are **not** nested CPI-style. They are mutually exclusive
integer bands plus `<T` / `>T` tails, mutex=true, six legs. Settlement is
the NWS Daily Climate Report for the named station (NYC = Central Park
**KNYC**, not LGA/JFK). Hourly temp markets settle on The Weather Company.

## Ladder consistency — no executable dutch

This is the most agent-native thing on the platform and it **does not
currently pay** after fees and size.

Exclusive YES payouts must sum to $1. Nested "above X" must be monotone
in k. A 1¢ ask on a zero-volume wing is **not** an arb: the dutch book is
incomplete unless every outcome has a real ask **and** at least one
contract of depth. Fees are quadratic `ceil(0.07·C·P·(1-P))` on **each**
leg.

Live mutex books (payload sizes, not a mid-sum fantasy):

| event | legs | mid_sum | sum(ask) | buy | sell |
|---|---:|---:|---:|---|---|
| `KXBTC-26SEP1222` | 188 | 2.54 | **4.12** | no_edge | missing_bid |
| `KXBTC-26SEP1317` | 80 | 1.43 | 1.99 | no_edge | missing_bid |
| `KXETH-26SEP1222` | 300 | 6.21 | **11.50** | no_edge | missing_bid |
| NYC / BOS / CHI highs | 6 | ~1.00–1.02 | 1.01–1.06 | no_edge | missing_bid |

BTC hourly: ~164 of 188 legs are 1¢ asks with huge advertised size and
**zero volume**. Buying the whole ladder costs ~$4.12 + fees to receive
$1. Selling all YES is incomplete because the wings have no bid. The
quoted-mid sum of 2.54 is a diagnostic of empty 1¢ wings, not a trade.

Nested CPI/GDP/payrolls are **not** exclusive. Summing their bids and
calling it a dutch is a bug (fixed in this pass). Mid inversions exist
(CPI Sep `T0.1` mid 90¢ vs `T0.2` mid 92¢) but `bid(inner) > ask(outer)`
never cleared after fees. **0 locked nested arbs.**

Settled last-price sums: BTC median 1.08, NYC/CHI highs 1.04, and
exactly one YES per weather event. Last price is not a quote.

Candle replay (was empty: weather has 6 legs so `n_traded>=8` skipped
it, hourly crypto has 80–300 legs so `n<=20` skipped it):

| event | period | complete-ask minutes | min sum(ask) | sum(ask)<1 | notes |
|---|---|---:|---:|---:|---|
| `KXBTC-26SEP1221` | 60m | 1 / 1 | **3.14** | 0 | one complete hour; buy-all pays $3.14 |
| `KXHIGHNY` Sep 10–11 | 1m | 191 / 2039 | **1.01** | 0 | 125 minutes with sum(bid)>1, not fee-aware |
| `KXHIGHCHI` Sep 10 | 1m | 387 / 1979 | **0.99** | 1 | one minute at 0.99; 6-leg fees ~6¢ eat it |

**Do not paper a ladder sleeve.** Keep the scanner
(`quantfirm/kalshi/ladder.py`) and re-check mutex books; only trade if
`exclusive_dutch` or `nested_monotone` returns `tradeable` with count≥1.

## Extra crypto 15m — paper DOGE+XRP+NEAR, not SOL/HYPE/BNB/ZEC, not live

Same overlay as live crypto: wait 3 min, ≥75¢ favorite, 4% of $250,
lag-fill. Bar: **each name independently** `pnl > 0` and `n ≥ 20`.
Harvest 2026-08-28 → 2026-09-12 (~1,527 settled windows each). TRAIN is
empty (`SPLIT_TS` is 2026-08-27). Headline is ALL + last 7d.

| spec | name | n | pnl | t | hit | dd | weeks |
|---|---|---:|---:|---:|---:|---:|---|
| wait3 ≥75¢ | **sol** ALL | 280 | **−$95** | −1.15 | 64% | 48% | W35 +31, W36 −79, W37 −47 |
| wait3 ≥75¢ | sol 7d | 118 | −$85 | −1.84 | 61% | 34% | |
| wait3 ≥75¢ | **doge** ALL | 295 | **+$78** | 0.80 | 71% | 17% | W35 +29, W36 +26, W37 +23 |
| wait3 ≥75¢ | doge 7d | 148 | +$16 | 0.27 | 69% | 18% | |
| wait3 ≥75¢ | **xrp** ALL | 270 | **+$204** | 2.37 | 75% | 31% | W35 −44, W36 +52, W37 +196 |
| wait3 ≥75¢ | xrp 7d | 125 | +$234 | 3.41 | 81% | 7% | |
| wait3 ≥75¢ | **near** ALL | 423 | **+$61** | 0.62 | 73% | 31% | W35 +5, W36 +35, W37 +21 |
| wait3 ≥75¢ | near 7d | 177 | +$79 | 1.12 | 72% | 31% | |
| wait3 ≥75¢ | **hype** ALL | 255 | **−$73** | −1.44 | 67% | 60% | W35 −57, W36 −72, W37 +56 |
| wait3 ≥75¢ | hype 7d | 153 | +$86 | 1.51 | 75% | 29% | one-week flip |
| wait3 ≥75¢ | **bnb** ALL | 310 | **−$146** | −2.06 | 67% | 62% | all three weeks red |
| wait3 ≥75¢ | bnb 7d | 143 | −$103 | −1.86 | 65% | 52% | |
| wait3 ≥75¢ | **zec** ALL | 377 | **−$86** | −1.05 | 70% | 38% | W35 −67, W36 +5, W37 −24 |
| wait3 ≥75¢ | zec 7d | 157 | −$44 | −0.65 | 68% | 28% | |

SOL is a hole. BNB is a hole. ZEC is a hole. HYPE ALL is red; W37 is a
one-week flip (Yahoo has no `HYPE-USD` 1m; vol path is Binance US
`HYPEUSDT`). DOGE is the durable one (three green weeks, modest t).
NEAR also three green weeks, thinner 15m book (~447 vol). XRP is the
punchy one (almost all of ALL is W37). nowait_75 is greener on
DOGE/XRP/NEAR and still red on SOL/BNB/ZEC — we do **not** drop the
3 min wait (open flicker is why live crypto waits).

Paper sleeve (implemented): `scripts/kalshi_div_paper_loop.sh`,
`--state-prefix kalshi_div_paper`, `KALSHI_LIVE=0`, metals
`doge,xrp,near`, strategy `desk_book`. The 4% overlay now applies to
extra crypto names so they cannot accidentally inherit the 8% commodity
book. `PAPER_ASSETS` / `CRYPTO_LIVE` / the live supervisor are unchanged.
`_refuse_live_sleeve` refuses `--live` on this prefix. Check-in heals
the paper loop the same way it heals poly paper.

SOL, HYPE, BNB, ZEC stay off. NEAR is a thin canary on the paper sleeve,
not a live raise. XRP's ALL pnl is mostly W37 — treat it as a canary,
not a raise.

## Weather — ensemble→brackets works; do not paper a one-day print

Open-Meteo GFS GEFS (30) + ECMWF IFS EPS (50) = 80 members, rounded to
integer °F so they land in Kalshi's inclusive bands (`75-76` means 75
and 76). Unmapped members drop to 0 after rounding. NWS `api.weather.gov`
latest obs is **not** the daily high (it's the current reading).

Sep 13 (today, still open) NYC Central Park:

| band | ensemble p | bid–ask | take |
|---|---:|---|---|
| <78 | 0% | 27–28¢ | **NO** (book is 27¢ on a 0% tail) |
| 78–79 | 11% | 36–38¢ | NO |
| 80–81 | 39% | 26–28¢ | YES |
| 82–83 | 26% | 6–8¢ | YES |
| 84–85 | 15% | 2–3¢ | YES thin |
| >85 | 9% | 0–1¢ | ignore 1¢ |

Ensemble mean 81.9°F. The book has 27¢ on `<78` against 0/80 members.
Chicago `<72` is 3¢ vs 25% of members. LAX `>83` is 3¢ vs 61% of
members — that one is a **basis trap** (KLAX vs grid, marine layer).

Dutch on the six-leg weather ladder: sum(ask) 1.01–1.06, not <1 after
fees. Sep 12 books are already 99¢ on the winning band — do not "trade"
yesterday.

Hurricane landfall: 0 open, 0 settled in the window. NYC rain 0 settled.
Denver month rain `KXRAINDENM-26AUG` has 10 settled legs (not a daily clip).

**Settled tape (correct event date from the ticker, not close_time):**
Open-Meteo's public ensemble archive only fills member columns for the
last ~4 days. 12 city-days (NYC/CHI/BOS × Sep 8–11), 80 members, 1°F
round, decision 12:00 UTC (08:00 ET), skip <5¢ and >92¢:

| | n | modal hit | mean p(winner) | HRRR hit | takes | pnl |
|---|---:|---:|---:|---:|---:|---:|
| NYC | 4 | 0/4 | 0.16 | 0 | 13 | **−$14.52** |
| CHI | 4 | 1/4 | 0.23 | 1 | 13 | −$3.38 |
| BOS | 4 | 1/4 | 0.30 | 1 | 11 | +$5.61 |
| all | 12 | **2/12 = 17%** | 0.23 | 2/12 | 37 | **−$12.29** |

Random among 6 bands is 17%. Modal hit is chance. HRRR (deterministic
hourly max via Open-Meteo historical-forecast) is the same. Sep 10 NYC
CLI printed the `<85` tail (`T85`) while the grid mean was **87.4°F**
— that is the station/park vs grid basis, not a slow book. Taking the
mapped edges at 8am ET lost money. `takeable_edge` exists so 1¢ leftovers
are not fake YES.

**Do not paper weather.** The mapper stays. Re-run when a liquid band
is 15¢+ off a *morning* ensemble and the CLI/grid spread is small.

## Macro — Cleveland Sep CPI 0.37% vs Kalshi T0.4; no Sunday print

Cleveland Fed inflation nowcasting (table, updated 2026-09-11):

| | Sep 2026 mom |
|---|---|
| CPI | **0.37%** |
| Core CPI | **0.20%** |
| CPI yoy | 3.43% |

September CPI has not printed. Mapping August's 0.40% onto September is
not a nowcast. Cleveland **is** the nowcast.

Kalshi `KXCPI-26SEP` (nested greater):

| strike | model P(>k) σ=0.10 | bid–ask | note |
|---|---:|---|---|
| T0.3 | 76% | 76–89¢ | wide, ~2 lots on the ask |
| **T0.4** | **38%** | **58–61¢** | YES rich; **NO at 42¢ vs ~62%** |
| T0.5 | 10% | 35–39¢ | YES rich; thin bid |
| T0.6 | 1% | 15–24¢ | 54k volume, 1-lot book |

The clean mapping is fade `T0.4` YES (buy NO) if you believe Cleveland
±0.10. Ask size on T0.4 is 18. This is a **print-week** trade, not a 15m
clip. Next print is mid-October. Do not run it overnight Sunday. Do not
size it off the live 15m ledger.

Atlanta Fed **GDPNow Q3 2026 = 4.4%** (updated 2026-09-10). Kalshi
`KXGDP-26OCT30-T4.0` is 14–19¢. Using GDPNow RMSE 1.17 pp as σ gives
P(>4%) ≈ 63% vs 19¢ ask. That is the loudest number in this pass and the
one most likely to be a **GDPNow-vs-consensus** trap. Atlanta's own
error is still large weeks before the advance. **Do not paper GDP** on
that gap without a history of GDPNow vs this Kalshi ladder.

Claims: last ICSA 206k (week ending Sep 5). Next print Thu Sep 17
(`KXJOBLESSCLAIMS-26SEP17`). P(≥210k) ≈ 37% at σ=$12k vs 20–21¢. Mild.
Seasonal median 227k is a worse model than last week's 206k. No lock.

Payrolls: no nowcast wired. Nested, not monotone-broken after fees.

**Do not paper a macro sleeve.** Edge is print-speed on a mapped
bracket. There is no print tonight. Settled window: two claims events
(`KXJOBLESSCLAIMS-26SEP10` / `26SEP03`) nested-resolved as expected
(print 206k → every ≥k below 205k YES, none locked). August CPI nested
resolved through T0.3 YES / T0.4 NO, matching the 0.40% print.
Keep `nowcast_to_nested` + Cleveland/GDPNow/ICSA pulls and only clip
when the number is in and the book has not moved.

## Paper / live

| sleeve | status |
|---|---|
| Live `desk_book` | unchanged. 5 commodities + BTC + ETH |
| Paper `kalshi_div_paper` | **on**: DOGE + XRP + NEAR, wait3 / ≥75¢ / 4%, `KALSHI_LIVE=0` |
| SOL / HYPE / BNB / ZEC 15m | off (red or one-week flip) |
| Hourly range dutch | off (complete-hour sum ask $3.14) |
| Weather ensemble | research only (12-day tape −$12) |
| CPI / GDPNow / claims | scan only, no loop |

If DOGE, XRP, or NEAR independently goes red on the paper tape, sit
that name. Do not promote any extra-crypto name to live without weeks of
that tape, same bar as BTC/ETH (each name green, lag-fill, not one lucky
week). XRP's ALL pnl is mostly W37 — treat it as a canary, not a raise.
NEAR's 15m book is thin (~447 vol).
