# BTC wait × bar (longer sits) — 2026-09-12

Live `desk_book` is unchanged: whole book wait 3 min + **≥75¢**.
This page is lag-fill research on **BTC only**, then a mixed-book
overlay confirm (ETH + commodities stay wait-3 + 75¢).

BTC markets on disk: **1334**. Tape ~2 weeks, not months.
Reproduce: `python3 scripts/kalshi_btc_wait_sweep.py`.

## Why

BTC 15m favorites whip in the first minutes. Longer wait = let
the open flicker die, then clip a richer (or same) bar.

## BTC-only tape vs live

| cfg | n | BTC | hit | last 7d | weekend |
|---|---:|---:|---:|---:|---:|
| wait3 + 60¢ (old) | 396 | -63 | 0.616 | -28 | +21 |
| **wait3 + 75¢ (live)** | 261 | **+152** | 0.743 | **+77** | +139 |

## Best bar at each wait (BTC-only, green ALL)

| wait | bar | n | BTC | last 7d | weekend | weeks green |
|---|---:|---:|---:|---:|---:|---:|
| 0 min (0s) | 72¢ | 328 | +154 | +83 | +167 | 2 |
| 2 min (120s) | 74¢ | 292 | +184 | +107 | +137 | 3 |
| 3 min (180s) | 74¢ | 280 | +199 | +112 | +170 | 3 |
| 4 min (240s) | 74¢ | 263 | +112 | +60 | +118 | 2 |
| 5 min (300s) | 79¢ | 161 | +70 | +26 | +69 | 2 |
| 6 min (360s) | 79¢ | 147 | +63 | +20 | +64 | 2 |
| 7 min (420s) | 79¢ | 131 | +49 | +13 | +40 | 2 |
| 8 min (480s) | 79¢ | 107 | +30 | -26 | +48 | 2 |
| 9 min (540s) | 81¢ | 64 | +0 | -36 | +11 | 2 |

## Strictly better than wait3+75 (BTC ALL and last 7d)

| cfg | n | BTC | last 7d | weekend |
|---|---:|---:|---:|---:|---:|
| wait 3 min + 74¢ | 280 | +199 | +112 | +170 |
| wait 2 min + 74¢ | 292 | +184 | +107 | +137 |
| wait 2 min + 72¢ | 323 | +174 | +88 | +167 |
| wait 3 min + 73¢ | 292 | +168 | +93 | +160 |
| wait 0 min + 72¢ | 328 | +154 | +83 | +167 |

## Mixed 7-name overlay (ETH + cmdty stay wait-3 + 75¢)

This is what we would actually run: only BTC's wait/bar moves.

| BTC cfg | BTC | ETH | cmdty | both names |
|---|---:|---:|---:|---|
| wait 3 min + 75¢ | +79 | +20 | -24 | yes |
| wait 3 min + 68¢ | +29 | +12 | +16 | yes |
| wait 3 min + 60¢ | +18 | -8 | +54 | no |
| wait 3 min + 74¢ | +94 | +21 | -17 | yes |
| wait 2 min + 74¢ | +94 | +15 | -21 | yes |
| wait 4 min + 66¢ | +75 | +9 | -36 | yes |
| wait 0 min + 74¢ | +73 | +14 | -8 | yes |
| wait 2 min + 73¢ | +59 | +13 | -5 | yes |
| wait 2 min + 75¢ | +78 | +13 | -21 | yes |
| wait 2 min + 79¢ | +63 | +19 | +37 | yes |
| wait 3 min + 73¢ | +85 | +23 | -15 | yes |
| wait 2 min + 72¢ | +42 | +21 | +3 | yes |
| wait 0 min + 72¢ | +50 | +20 | +12 | yes |
| wait 4 min + 74¢ | +60 | +13 | -24 | yes |
| wait 5 min + 79¢ | +40 | +20 | +38 | yes |
| wait 6 min + 79¢ | +26 | +15 | +31 | yes |
| wait 7 min + 79¢ | +28 | +2 | +24 | yes |
| wait 8 min + 79¢ | +18 | +1 | +35 | yes |
| wait 9 min + 81¢ | -14 | +19 | +22 | no |

## Verdict

**Longer waits lose on BTC.** The 3 min wait is already the peak.
Sitting 5–12 min so the favorite “settles down” gives up the clips
that pay. 10–12 min have **no** green bar.

| wait | best BTC-only | vs live wait3+75 |
|---|---|---|
| 0–2 min | 72–74¢ still green | similar / a bit more n |
| **3 min (live)** | **75¢ +$152** (74¢ +$199 isolated) | baseline |
| 4 min | 74¢ +$112 | worse |
| 5–7 min | 79¢ +$70 → +$49 | worse |
| 8–9 min | last-7d red | no |
| 10–12 min | no green bar | no |

Mixed overlay (ETH + commodities stay wait-3 + 75¢): wait 5 min on
BTC drops BTC from +$80 to +$40. ETH stays green because we did not
touch ETH. That is not a reason to sit BTC longer.

Wait-3 + **74¢ on BTC only** prints a bit more than 75¢ on this tape
(+$94 vs +$80 mixed) while ETH stays at 75¢. Do **not** bounce for
that 1¢ — 74¢ dumps ETH when **both** names use it
(`research/kalshi_bar.md`). Two weeks, not months.

Live stays wait 3 + 75¢ on both names.


