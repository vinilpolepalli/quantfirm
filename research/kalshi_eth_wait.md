# ETH wait × bar (longer sits) — 2026-09-12

Live `desk_book` is unchanged: whole book wait 3 min + **≥75¢**.
Lag-fill research on **ETH only**, then mixed overlay (BTC +
commodities stay wait-3 + 75¢). Same grid as BTC.

ETH markets on disk: **1335**. Tape ~2 weeks, not months.
Reproduce: `python3 scripts/kalshi_eth_wait_sweep.py`.

## ETH-only tape vs live

| cfg | n | ETH | hit | last 7d | weekend |
|---|---:|---:|---:|---:|---:|
| wait3 + 60¢ (old) | 356 | -51 | 0.601 | -42 | +35 |
| **wait3 + 75¢ (live)** | 229 | **-25** | 0.707 | **+56** | -12 |

## Best bar at each wait (ETH-only, green ALL)

| wait | bar | n | ETH | last 7d | weekend | weeks green |
|---|---:|---:|---:|---:|---:|---:|
| 0 min (0s) | 61¢ | 409 | +44 | -115 | +39 | 2 |
| 4 min (240s) | 78¢ | 206 | +19 | +50 | +15 | 1 |
| 6 min (360s) | 68¢ | 240 | +29 | +2 | -13 | 3 |
| 7 min (420s) | 74¢ | 157 | +36 | +58 | -4 | 1 |
| 8 min (480s) | 62¢ | 184 | +27 | +47 | -3 | 2 |
| 12 min (720s) | 71¢ | 26 | +5 | +14 | -1 | 1 |

## Strictly better than wait3+75 (ETH ALL and last 7d)

| cfg | n | ETH | last 7d | weekend |
|---|---:|---:|---:|---:|---:|
| wait 7 min + 74¢ | 157 | +36 | +58 | -4 |
| wait 8 min + 74¢ | 121 | +22 | +60 | +1 |

## Mixed 7-name overlay (BTC + cmdty stay wait-3 + 75¢)

| ETH cfg | BTC | ETH | cmdty | both names |
|---|---:|---:|---:|---|
| wait 3 min + 75¢ | +79 | +20 | -24 | yes |
| wait 3 min + 68¢ | +7 | +35 | -30 | yes |
| wait 3 min + 60¢ | -9 | +16 | -18 | no |
| wait 7 min + 70¢ | +78 | +15 | -23 | yes |
| wait 7 min + 71¢ | +81 | -5 | -24 | no |
| wait 7 min + 69¢ | +67 | +9 | -45 | yes |
| wait 6 min + 68¢ | +66 | -9 | -42 | no |
| wait 8 min + 62¢ | +9 | +3 | -31 | yes |
| wait 6 min + 75¢ | +80 | +7 | -23 | yes |
| wait 6 min + 79¢ | +59 | +24 | +43 | yes |
| wait 6 min + 78¢ | +82 | -3 | -18 | no |
| wait 8 min + 74¢ | +61 | +47 | -5 | yes |
| wait 7 min + 74¢ | +79 | +26 | -24 | yes |
| wait 0 min + 61¢ | -71 | +75 | +95 | no |
| wait 4 min + 78¢ | +85 | +26 | -31 | yes |
| wait 12 min + 71¢ | +50 | -16 | +55 | no |

## Verdict

ETH is **not** like BTC here.

Isolated ETH wait-3 + 75¢ is **red on ALL (−$25)** and green last 7d
(+$55). Weekend is red. Mixed live (BTC sharing the book) still prints
ETH **+$20**. Use the mixed overlay, not the isolated red baseline.

| ETH wait | isolated ETH | mixed ETH (BTC stays wait3+75) | mixed BTC | both? |
|---|---:|---:|---:|---|
| **3 min + 75¢ (live)** | −$25 | **+$20** | **+$80** | **yes** |
| 4 min + 78¢ | +$19 | +$26 | +$85 | yes |
| 6 min + 79¢ | +$26 | +$24 | +$59 | yes |
| 7 min + 74¢ | +$36 | +$26 | +$79 | yes |
| 8 min + 74¢ | +$22 | +$47 | +$61 | yes |
| 10–12 min | mostly dead / n tiny | no | | |

Sitting ETH 6–8 min can look green isolated because it skips the
week-35/weekend clips that sink wait-3. On the mixed book it does
**not** beat live by enough to bounce: wait-7 + 74¢ is ETH +$26 vs
+$20 with BTC still +$79 — 2 weeks, and W35/W36 on that spec are still
red. Weekend ETH stays red at almost every longer wait.

**Do not bounce.** Live stays wait 3 + 75¢ on both names. BTC longer
waits already lost (`research/kalshi_btc_wait.md`). ETH longer waits
are a maybe on last-7d, not a law.


