# Favorite bar + wait sweep (2026-09-12)

Live `desk_book` waits 3 min then clips the favorite. Owner: win on
**both** BTC and ETH even if they **differ**. 1¢ × wait grid on the
mixed 7-name book (lag-fill, $250).

We do **not** have months of 15m crypto. Harvest is 2026-08-28 →
2026-09-12 (~2 weeks). Yahoo 1m underlying does not go further.

```bash
python3 scripts/kalshi_param_sweep.py
python3 scripts/kalshi_bar_durability.py
```

Grid: wait ∈ {0, 60, 120, 180, 240, 300, 420}s × bar 60–80¢ step 1¢
(147 mixed-book runs).

## Mixed book — wait 3 min (the live wait)

| bar | BTC | ETH | last 7d BTC/ETH | both+7d |
|---|---:|---:|---|---|
| 60¢ | −$100 | −$62 | red / red | no |
| 68¢ | +$23 | +$8 | +$29 / +$46 | yes |
| 70¢ | +$52 | +$4 | mixed | yes (ETH thin) |
| 72¢ | +$94 | **−$40** | | no (dumps ETH) |
| 74¢ | +$107 | **−$10** | | no |
| **75¢** | **+$80** | **+$20** | **+$32 / +$57** | **yes** |
| 76¢ | +$20 | +$27 | BTC last-7d red | no |

75¢ is the wait-3 peak that stays green on **both** names on ALL and
last 7d. 74¢ is a hole. 72¢ dumps ETH.

## Other waits (same tape)

| cfg | BTC | ETH | notes |
|---|---:|---:|---|
| no wait / 1 min + **79¢** | +$66 | +$32 | identical; W37 BTC −$54 |
| wait 2 min + 75¢ | +$70 | +$14 | |
| wait 4 min + 68¢ | +$72 | +$15 | |
| wait 4 min + 74¢ | +$79 | +$26 | best sum with a wait |
| wait 5 min + 68¢ | +$68 | +$18 | |

No config is green **every** week on both names. Weekend ETH is red at
every bar we tried (68 −$34, 75 −$47, 79 −$48).

## Crypto-only (weekend, commodities dark)

| cfg | BTC | ETH | both |
|---|---:|---:|---|
| wait3 + 68¢ | −$2 | −$9 | no |
| wait3 + 75¢ | +$120 | −$7 | no |
| wait3 + 72¢ | +$171 | −$108 | no |

75¢ still does not make ETH on a crypto-only tape. Live weekdays mix
commodities into the same book; that is why mixed-book 75¢ prints both.

## BTC longer waits

Sitting BTC 5–12 min (leave ETH at wait-3 + 75¢) **loses** vs live.
3 min is the BTC peak; 10–12 min have no green bar. Numbers:
`research/kalshi_btc_wait.md`. Sweep:
`python3 scripts/kalshi_btc_wait_sweep.py`.

ETH same grid: isolated wait-3 + 75¢ is red ALL, last-7d green.
Longer ETH sits (6–8 min) can look green isolated; mixed overlay does
not beat live enough to bounce. `research/kalshi_eth_wait.md`.
`python3 scripts/kalshi_eth_wait_sweep.py`.

## What went live

`desk_book` favorite bar **60¢ → 68¢ → 75¢**. Same 3 min wait, same
8% / 4% size, names independent. Do not bounce the running agent.

This is a 2-week local peak on a 147-point search, not a months-proven
edge. Next tape should re-score 68 vs 75 vs wait-4 74¢.
