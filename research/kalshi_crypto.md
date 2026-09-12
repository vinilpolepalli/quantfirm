# Kalshi BTC/ETH 15m — cautious 24/7 sleeve (2026-09-12)

Commodities close **Sat 04:00Z → Mon 03:15Z**. BTC/ETH 15m stay open.
Owner asked to look into crypto so the desk can clip around the clock,
a bit more cautiously than the 8% commodity book.

**Do not last-minute lock.** `one_pct` touch last week: BTC 54 fills
**−$55.46** hit 88.9%; ETH 42 fills −$17.01 hit 92.9%
(`research/kalshi_one_pct_week.md`). Lag last-minute on this harvest:
0 fills (raced out). Touch 7d on this pull: 27 fills **−$17.29**.

Crypto candles on disk: 2026-08-29 → 2026-09-12 01:15Z. `SPLIT_TS` is
2026-08-27, so TRAIN is empty. Headline is ALL + last 7d, not a
holdout.

## Lag-fill, $250, BTC+ETH together (ETH is the hole)

| spec | window | n | pnl | t | hit | DD | BTC | ETH |
|---|---|---:|---:|---:|---:|---:|---|---|
| `rich_fav` 8% ≥60¢ until close | ALL | 661 | **−$92** | −0.96 | 59.5% | 52% | +$30 | **−$123** |
| same | 7d | 325 | −$71 | −1.06 | 58.2% | 40% | −$2 | −$69 |
| 4% ≥72¢, skip last 2 min | ALL | 498 | −$37 | −0.61 | 68.5% | 23% | +$29 | −$66 |
| same | 7d | 231 | −$14 | −0.33 | 70.1% | 13% | +$1 | −$16 |
| 4% ≥80¢, skip last 2 min | ALL | 321 | −$20 | −0.33 | 74.5% | 19% | +$18 | −$38 |

Dumping crypto into the 8% commodity book is a weekend wipe. ETH is
why. BTC alone is a different tape.

## BTC only (the 24/7 sleeve)

| spec | window | n | pnl | t | hit | DD | weeks |
|---|---|---:|---:|---:|---:|---:|---|
| 4% ≥72¢, τ 120–780 | ALL | 334 | **+$49** | 0.88 | 71.6% | 13% | W35 +34, W36 +36, W37 −22 |
| same | 7d | 161 | +$9 | 0.24 | 71.4% | 13% | |
| 4% ≥80¢, τ 120–780 | ALL | 176 | +$54 | 1.06 | 77.8% | 11% | W35 +27, W36 +39, W37 −12 |
| 4% ≥72¢ until close | ALL | 341 | +$39 | 0.69 | 70.7% | 14% | last-2-min costs ~$10 |

Weekend vs weekday (BTC 4% ≥72¢, skip last 2 min):

| session | n | pnl | hit |
|---|---:|---:|---:|
| weekday | 237 | −$12 | 68.4% |
| **weekend** | 97 | **+$61** | 79.4% |

That weekend print is why this is on the live loop. t=0.88 is **not**
the tournament gate. W37 already gave back $22. Size stays 4%.

## ETH only — stay off

| spec | ALL pnl | 7d pnl |
|---|---:|---:|
| 4% ≥72¢ skip last 2 min | **−$57** t=−1.22 | +$5 |
| 4% ≥80¢ skip last 2 min | −$22 | +$20 (one week) |
| weekend 72¢ | −$9 | |

ETH FLB is red as a *standalone* book. It is still in the live mix at
4% / ≥60¢ until close, and can sit next to BTC.

## Live overlay moved 72¢ → 60¢ (2026-09-12)

Owner: clip every interval if we can, stay chill. Same 4% size. Bar
matches commodities. Lag-fill until close, harvested tape:

| book | ALL n | ALL pnl | t | DD | BTC | ETH |
|---|---:|---:|---:|---:|---|---|
| 4% ≥72¢ until close, BTC+ETH | 636 | **−$63** | −0.96 | 35% | +$17 | **−$80** |
| **4% ≥60¢ until close, BTC+ETH** | 1085 | **−$27** | −0.34 | 27% | −$10 | −$17 |
| 4% ≥72¢, BTC only | 341 | +$39 | 0.69 | 14% | | |
| 4% ≥60¢, BTC only | 590 | +$4 | 0.08 | 17% | | |
| 4% ≥72¢, ETH only | 325 | −$74 | −1.60 | 33% | | |
| 4% ≥60¢, ETH only | 515 | −$26 | −0.47 | 21% | | |

BTC-only 72¢ is still the greenest sleeve. The **live mix is BTC+ETH**,
and 60¢ is less red there because ETH's 72–92¢ favorites were the hole.
60–71¢ books add fills; they do not make ETH worse. Coin-flips still
sit. A 36¢ YES with a 64¢ NO is a NO favorite — we buy NO, not the
longshot.

SOL/DOGE/XRP 15m were open on 2026-09-12. No harvested tape. Stay off.

## What went live

`desk_book` on **gold, silver, copper, WTI, natgas, btc, eth**:

- commodities: existing `rich_fav` (8%, ≥60¢, until close, fee-eat)
- **BTC and ETH: 4%, ≥60¢, until close, fee-eat, no longshots**
- clip every 15m window that has a real favorite; sit 50–58¢ coin-flips
- both can be on in the same window
- no `one_pct` / last-90s locks, no yolo 15–18%
- last-2-min clock is off; 99¢ last ticks still sit out via fee-eat

A 36¢ or 55¢ weekend BTC book still sits the longshot/coin-flip side.
That is the caution, not a clock.

```bash
python3 scripts/kalshi_score_crypto.py
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy crypto_fav --fill-mode lag --bankroll 250
```
