# one_pct last-week backtest (2026-09-12)

Bankroll **$250**. Live universe: gold, silver, copper, WTI, natgas, **BTC,
ETH**. Decision grid is 1-minute candles. `one_pct` only fires at
**T = close − 60s** (`tau` 8–90s).

**Verdict: not good. Do not send real orders.** Keep paper. Do not set
`KALSHI_LIVE=1`. An API key does not change this score.

The compounding pitch (`1.01^96 ≈ 2.6×/day`) is not on this sample.

## Headline (7 series, last 7 days from 2026-09-05Z)

| model | n | pnl | ret | hit | t | DD |
|---|---:|---:|---:|---:|---:|---:|
| `one_pct` **lag** (honest REST floor) | 3 | **−$3.11** | −1.2% | **0%** | −1.07 | 1.2% |
| `one_pct` **touch** (zero-latency ceiling) | 249 | **−$78.79** | −31.5% | 93.2% | −1.27 | 41% |

Lag skipped **390** last-minute locks as `raced_out`. The 3 fills that
survived the whole minute uncontested all lost — winner’s curse, same
pattern as `research/kalshi_review.md`.

Touch last week by fill subset:

| subset | n | pnl | hit |
|---|---:|---:|---:|
| contested (the race a REST loop loses) | 247 | −$53.47 | 93.9% |
| uncontested (certain REST fill) | 2 | −$25.32 | **0%** |

Even the optimistic model is underwater once BTC/ETH are in the book.
BTC last week: 54 fills, **−$55.46**, hit 88.9%. ETH: 42 fills, −$17.01,
hit 92.9%. A 94¢ favorite needs ~95%+ after fees to break even; crypto
locks in this window did not.

14-day `touch` is worse: **−$134.88 / −54% / DD 64% / t = −1.59**.

Promotion bar (`docs/HANDOFF.md` §5, `docs/KALSHI.md` §8) is unchanged:
none of the boxes are met.

## Why 1% per window is not available

`1.01^96` assumes a win in almost every 15-minute window. Count of
spot-agree 90–97¢ quotes at T−60s, **before** any fill model:

| | 7d (5 commodities) | 7d (7 series, +crypto) | 14d (7 series) |
|---|---:|---:|---:|
| windows | 2505 | 3846 | 7654 |
| no underlying 1m bar | 1265 | 945 | 1379 |
| no lock in 90–97¢ + spot agree | 1011 | 2475 | 5395 |
| candidate locks | 229 | **426** | 874 |
| lock hit rate | 95.6% | **93.7%** | 92.8% |
| EV / contract before fee | +1.15¢ | **−0.69¢** | −1.54¢ |
| uncontested locks | 2, hit 0% | 3, hit 0% | 8, hit 0% |

426 locks in 7 days is ~61/day across *seven* books, not 96/day on one
book. Most windows never lock inside 90–97¢ with spot already on that
side.

Sizing: a 95¢ lock pays 5¢ on a win. 1% of $250 is $2.50 → 50 contracts
≈ $47.50 (19% of bankroll). Live cap is **8%** so a win is ~$0.60–$2,
not 1%. Touch-week average P&L was **−$0.32 per fill**.

## Strategy table ($250)

```bash
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy one_pct --fill-mode lag --since 2026-09-05T00:00:00Z --bankroll 250
```

### Live universe (gold/silver/copper/wti/natgas/btc/eth)

| strategy | fill | window | n | pnl | ret | hit | t | DD | note |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `one_pct` | lag | 7d | 3 | −3.11 | −1.2% | 0% | −1.07 | 1.2% | 390 `raced_out` |
| `one_pct` | lag | 14d | 5 | −3.76 | −1.5% | 0% | −1.35 | 1.5% | 757 `raced_out` |
| `one_pct` | touch | 7d | 249 | **−78.79** | −31.5% | 93.2% | −1.27 | 41.1% | BTC −$55 |
| `one_pct` | touch | 14d | 531 | **−134.88** | −54.0% | 93.2% | −1.59 | 64.1% | daily_stop 1602 |

`one_pct` touch, last 7d, by asset (still the optimistic fill):

| asset | n | pnl | hit |
|---|---:|---:|---:|
| gold | 41 | +16.89 | 97.6% |
| wti | 38 | +12.93 | 97.4% |
| natgas | 31 | +20.86 | 100% |
| eth | 42 | −17.01 | 92.9% |
| copper | 33 | −35.68 | 87.9% |
| silver | 10 | −21.32 | 80.0% |
| btc | 54 | −55.46 | 88.9% |

Two misses at ~94¢ wipe a stack of 5¢ wins. Crypto last-minute “locks”
were the worst of the book.

### Commodities only (no crypto) — for comparison

A first pass without BTC/ETH, and with staler Yahoo coverage, made
`touch` last week look green. That number is **not** the live book.

| strategy | fill | window | n | pnl | ret | hit | t | DD |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `one_pct` | lag | 7d | 2 | −0.14 | −0.1% | 0% | −1.78 | 0.1% |
| `one_pct` | touch | 7d | 154 | +52.97 | +21.2% | 96.8% | 1.12 | 15.2% |
| `one_pct` | touch | 14d | 345 | −16.22 | −6.5% | 94.8% | −0.22 | 32.7% |
| `favorite_div` | lag | 7d | 363 | +81.39 | +32.6% | 74.4% | 1.12 | 20.4% |
| `favorite_div` | lag | 14d | 843 | +130.68 | +52.3% | 75.0% | 1.17 | 20.9% |
| `favorite_div` | touch | 7d | 738 | +117.54 | +47.0% | 83.3% | 1.68 | 14.7% |
| `favorite_div` | touch | 14d | 1084 | −42.97 | −17.2% | 81.2% | −0.67 | 49.7% |

Commodities `touch` 7d still split **+$94 contested / −$41 uncontested**.
The +$53 is the same zero-latency artifact as the original oracle taker.
`favorite_div` lag last week is the 72¢ favorite book that already lost the
first live paper window (−$2.90). t stays below 1.5.

JSON: `research/one_pct_week/`.

## Skip reasons (`one_pct` lag, 7d, live)

| reason | count | meaning |
|---|---:|---|
| `no_underlying` | 945 | Yahoo 1m missing (mostly commodity nights/halts; crypto is dense) |
| `raced_out` | 390 | last minute traded *through* our 90–97¢ limit |
| fills | 3 | only uncontested survivors; all lost |

`touch` 7d also hit `daily_stop` 930 times (the −10% day halt) and
`gapped_away` 21.

## What an API key would and would not do

If a Kalshi API key shows up:

* Wire `KALSHI_PROD_KEY_ID` + `KALSHI_PROD_PRIVATE_KEY` (or `_PATH`).
* Leave **`KALSHI_LIVE` unset** and do **not** pass `--live`.
* Paper/shadow already reads public books with no key.
* Demo key (`KALSHI_DEMO_*`) is the right next credential if we want real
  resting-order plumbing with fake money (`docs/KALSHI.md` §7).

Go-live still needs: ≥2 weeks of *live shadow* fills after an adverse
haircut, a per-print fill model, null control weaker than the strategy,
demo green, `docs/FIRM.md` §2. This backtest does not clear any of that.

## Reproduce

```bash
python3 -m unittest tests.test_kalshi -v
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy one_pct --fill-mode lag --since 2026-09-05T00:00:00Z
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy one_pct --fill-mode touch --since 2026-09-05T00:00:00Z
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy favorite_div --fill-mode lag --since 2026-09-05T00:00:00Z
```

Harvest used for this pass (public API, no creds):

```bash
python3 scripts/kalshi_harvest.py --series KXGOLD15M KXSILVER15M KXCOPPER15M \
  KXWTI15M KXNATGAS15M --skip-yf
python3 scripts/kalshi_harvest.py --series KXBTC15M KXETH15M \
  --min-close 2026-08-29T00:00:00Z --skip-yf
```

Commodity markets on disk close through **2026-09-12T01:15Z**. BTC/ETH
harvest is last ~14 days only (`--min-close 2026-08-29`).
