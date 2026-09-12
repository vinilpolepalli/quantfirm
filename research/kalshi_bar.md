# Favorite bar: 68¢ vs 60¢ (2026-09-12)

Live `desk_book` waits 3 min then clips the favorite. The live bar was
60¢. Owner: win on **both** BTC and ETH predictions even if they
**differ** (BTC YES + ETH NO is allowed). `same_side_book` was the
wrong reading and stays off.

We do **not** have months of 15m crypto. Harvest:

| series | markets | tape |
|---|---:|---|
| BTC / ETH | 1334 / 1335 | 2026-08-28 → 2026-09-12 (~2 weeks) |
| gold / silver / WTI | ~2966 | 2026-07-31 → 2026-09-12 |
| Yahoo 1m underlying | | ~30 days max; crypto from 2026-08-15 |

Reproduce:

```bash
python3 scripts/kalshi_bar_durability.py
```

## Mixed book (what live actually runs)

7 names, lag-fill, $250, wait 3 min. Crypto fills only:

| bar | BTC n | BTC | ETH n | ETH | both |
|---|---:|---:|---:|---:|---|
| 60¢ | 216 | **−$100** | 206 | **−$62** | no |
| **68¢** | 233 | **+$23** | 222 | **+$8** | **yes** |

Week-by-week at 68¢ (still not durable):

| week | BTC | ETH |
|---|---:|---:|
| 2026-W35 | +$38 | −$2 |
| 2026-W36 | −$21 | −$36 |
| 2026-W37 | +$6 | +$46 |

60¢ is red on both names in W36 and W37. 68¢ is **better** (less
flicker) but W36 still loses both. Weekend ETH at 68¢ is still red
(−$34). This is not a months-long edge.

## Crypto-only (weekend, commodities dark)

When gold/WTI are closed, live *is* BTC+ETH alone:

| bar | BTC | ETH | both |
|---|---:|---:|---|
| wait3 + 60¢ | −$114 | −$56 | no (every week red) |
| wait3 + 68¢ | −$2 | −$9 | no (close) |
| wait3 + 72¢ | **+$171** | **−$108** | no (one name) |

72¢ is the cartoon of “win on BTC, lose on ETH”. 68¢ is the least-bad
bar that does not dump ETH.

## Commodities (test, post 2026-08-27)

68¢ is less red than 60¢ (−$46 vs −$72). Gold stays the hole.

## What went live

`desk_book` favorite bar **60¢ → 68¢**. Same 3 min wait, same 8% / 4%
size, names independent, Poly disagree still sits crypto. Do not
bounce the running agent.

Keep researching other overlays (`research/kalshi_oss.md`). Do not
treat 68¢ as a months-proven edge.
