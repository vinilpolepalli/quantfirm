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

ETH FLB is red across weeks as a *standalone* book. It is still a
useful **fallback** when BTC is a coin-flip: same 4% / ≥72¢ overlay,
and **one crypto slot** so we never sit in both.

SOL/DOGE/XRP 15m were open on 2026-09-12. No harvested tape. Stay off.

## What went live

`desk_book` on **gold, silver, copper, WTI, natgas, btc, eth**:

- commodities: existing `rich_fav` (8%, ≥60¢, until close, fee-eat)
- **BTC then ETH: 4%, ≥72¢, skip last 2 minutes, fee-eat, no longshots**
- **one crypto slot** — tick order is BTC first; `EXCLUSIVE_GROUPS` blocks ETH if BTC is on, any side
- no `one_pct` / last-90s locks, no yolo 15–18%

A 36¢ weekend BTC book sits out. That is the caution, not a clock.

```bash
python3 scripts/kalshi_score_crypto.py
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy crypto_fav --fill-mode lag --bankroll 250
```
