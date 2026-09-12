# OSS / overlay iteration — win on **both** BTC and ETH (2026-09-12)

Live stays `desk_book`. This page is lag-fill research. Bankroll $250.
Bar the owner asked for: **BTC and ETH both green**, not a net that
hides one name behind the other.

Reproduce:

```bash
python3 scripts/kalshi_oss_iterate.py
```

## Why “both”

Live 15m crypto often prints one winner and one loser in the same
window. `desk_book` lag-fill is red on **both** names:

| spec | split | n | pnl | BTC | ETH | cmdty | both names |
|---|---|---:|---:|---:|---:|---:|---|
| `desk_book` | test | 1099 | **−$167** | −$62 | −$35 | −$70 | no |
| `desk_book` | last 7d | 434 | **−$152** | −$44 | −$53 | −$55 | no |

Sitting ETH (`no_eth_book`) does not fix BTC. Same-side (only clip when
BTC and ETH share a ≥60¢ favorite) is barely green on last-7d ETH
(+$0.15) and red on test.

## OSS sources (not copied live)

| source | idea we scored | 15m translation |
|---|---|---|
| Whelan / Bürgi / Deng 2025 | takers: favorites ≥50¢ small +, longshots lose; makers beat takers | richer FLB bar; do not buy 8–22¢ YES |
| [DanMcInerney/kalshi-strategy-executor](https://github.com/DanMcInerney/kalshi-strategy-executor) `longshot.yaml` | maker NO when YES is 2–19¢ (sports) | taker: if YES is 2–19¢, buy NO (81–98¢ fav) |
| [hamad-khawaja/kalshi-trading-bot](https://github.com/hamad-khawaja/kalshi-trading-bot) | sit 0–7 min; settlement ride last 5; directional **25–58¢** (block >60); exits / 16-signal model | wait 7; settle_ride ≥70¢ last 5 min; `dir_zone` as a control |
| clodesnow dump-and-hedge / Poly Up+Down arb | buy dump then hedge when sum ≤95¢ | not a Kalshi taker (one contract, not two tokens) |
| agiprolabs prediction-market-strategy | maker NO on 5–20¢ brackets | candle maker fills are an artifact here — not scored as taker P&L |

Hamad’s directional zone **blocks** trades above 60¢. That is the
opposite of Whelan / our live book. It is in the table as a control.

## Scoreboard (lag, $250, 7 series)

`both` = BTC n>0, ETH n>0, both P&Ls > 0.

| spec | split | n | pnl | t | BTC | ETH | cmdty | both |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `desk_book` | test | 1099 | −167 | −0.91 | −62 | −35 | −70 | no |
| `wait7_book` | test | 797 | −97 | −0.64 | −88 | +1 | −10 | no |
| `persist_book` | test | 568 | −89 | −0.72 | −75 | +21 | −35 | no |
| `tight_book` | test | 881 | −184 | −1.30 | −51 | −35 | −97 | no |
| `dir_zone` | test | 1265 | +88 | 0.35 | **+212** | **−111** | −12 | **no** (one name) |
| `same_side_book` | test | 854 | −147 | −1.18 | −30 | −33 | −84 | no |
| `spot_desk` | test | 899 | −163 | −0.94 | −134 | −32 | +4 | no |
| **`richer_wait` (68¢)** | test | 1020 | −53 | −0.33 | **+14** | **+9** | −75 | **yes** |
| **`richer_wait`** | last7d | 509 | **+84** | 0.43 | **+36** | **+56** | −8 | **yes** |
| **`longshot_no`** | test | 400 | **+129** | 1.01 | **+21** | **+60** | **+49** | **yes** |
| **`longshot_no`** | last7d | 195 | **+50** | 0.71 | **+5** | **+38** | **+7** | **yes** |

`longshot_no` is the only frozen spec that is green on BTC, ETH, **and**
commodities on both test and last 7d. It is still t<1.5 — not a live
promotion.

`richer_wait` wins **both crypto names** on both splits. Commodities stay
the hole on test (−$75). Raising the bar to 70¢ / 75¢ (sensitivity, not
a new selection) keeps both crypto names green; 72¢ loses ETH on test;
80¢ loses BTC on both splits.

Hamad wait-7, persist, tight spread, last-2-min sit, settlement ride, and
spot-agree did **not** clear the both-names bar. `dir_zone` is the
cartoon of “one or the other”: BTC +$212, ETH −$111.

## What would change the live book

Nothing on this page. `PAPER_STRATEGY` stays `desk_book`. Next
measurement, off-loop:

1. `longshot_no` — only when YES is 2–19¢, take NO. Same 4% crypto cap.
2. `richer_wait` — same wait as live, favorite bar **68¢** not 60¢.

Do not bounce the 24/7 agent for either until a paper sleeve has enough
n on **both** names. Do not turn on Hamad-style cash-out / trailing TP
(already red vs hold on today’s fills).
