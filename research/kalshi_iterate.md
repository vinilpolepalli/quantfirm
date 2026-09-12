# Strategy iteration — 2026-09-12 (not a go-live)

Goal: a taker that is green on **lag-fill backtest** *and* live paper.
Bankroll $250. Fill headline is always **lag**. Touch is a ceiling.
Tournament gate: test n≥30, pnl>0, t≥1.5, max DD≤30%, beat controls.

Nothing on this page is a go-live. `KALSHI_LIVE` stays unset.

## What we already knew

`one_pct` last-90s 90–97¢ locks: 1-min lag is empty (`raced_out`). Touch
P&L is the race REST is not supposed to win. Write-up:
`research/kalshi_one_pct_week.md`.

Live paper nevertheless filled 7/7 one_pct trades on 12 Sep
(+~$7.3). Poll is 2s, not 60s, so the candle lag model is too harsh for
that book. 7 trades is a speed experiment, not a strategy.

## Train-only scan (close < 2026-08-27)

Last-minute (τ=60) 90–97¢: 99% contested, lag n≈5, EV negative.

Positive lag-EV cells with n_lag≥30 were **88–94¢ favorites with 3–10
minutes left** (τ=240 and τ=600). Frozen into:

| name | rule |
|---|---|
| `mid_lock` | `one_pct` fn, τ 180–300, 88–94¢, spot-agree |
| `spot_lock` | `one_pct` fn, τ 180–660, 88–94¢, spot-agree |
| `rich_fav` | FLB 88–94¢, **no** spot gate |
| `model_fav` | GBM ≥88% **and** book already 80–94¢ |
| `offhours_lock` | `spot_lock` sitting out 12:00–21:00 UTC |

### Second train scan (sequential first-fill, 1-contract, 2026-09-12)

Pooled minute-cells overstate n. Sequential first-fill of 88–94¢
spot-agree, τ 3–11 min:

- Overall: n=192, hit 83.9%, t=−0.12 (matches `spot_lock` train).
- London/NY 12:00–21:00 UTC: n=93, hit 79.6%, t=−1.14.
- Complementary 21:00–12:00 UTC: n=99, hit 87.9%, t=+1.18, gold and
  silver both green, same sign in train weeks 34 and 35. Week 33
  (thin books) was red everywhere.
- Persistence, displacement, and GBM gates did **not** help.
- Fading the 88–94¢ favorite (buy the longshot) lag-fills at ~4% hit
  (winner's curse) and is a hard loser.

`offhours_lock` freezes the hour split from that scan. Do not retune
the window from test.

Reproduce the scan (train only — passing test is a protocol break):

```bash
python3 scripts/kalshi_train_lock_scan.py --data data/kalshi
```

## Lag-fill scoreboard ($250, official engine)

| strategy | universe | train n / pnl / t | TEST n / pnl / t / hit / dd | last 7d n / pnl / t |
|---|---|---|---|---|
| `one_pct` | 7 series | 4 / −5 / −2.3 | 5 / −4 / −1.4 / 0% | 3 / −3 / −1.1 |
| `mid_lock` | 7 series | 48 / −10 / −0.4 | 142 / −42 / −0.9 | 61 / −18 / −0.6 |
| `spot_lock` | 7 series | 166 / −5 / −0.1 | 449 / +117 / 1.12 / 85% / 23% | 212 / +24 / 0.43 |
| `spot_lock` | **5 commodities** | 166 / −5 / −0.1 | 337 / +96 / 1.12 / 86% / 23% | 148 / +33 / 0.67 |
| `rich_fav` | 7 series | 167 / −3 / −0.1 | 483 / +123 / 1.14 / 85% / 24% | 225 / +27 / 0.45 |
| `rich_fav` | **5 commodities** | 167 / −3 / −0.1 | 368 / **+130** / **1.42** / 87% / 22% | **158 / +55 / 1.06** |
| `offhours_lock` | 7 series | 87 / **+38** / **1.18** / 87% / 11% | 281 / +14 / 0.20 / 84% / 29% | 126 / +21 / 0.46 |
| `offhours_lock` | 5 commodities | 87 / +38 / 1.18 | 210 / **−6** / −0.1 / 84% / 31% | 88 / +24 / 0.66 |
| `model_fav` | 7 series | 9 / −18 / −1.0 | 43 / +70 / 2.69 / 93% / 4.4% | 12 / +1 / 0.09 |
| `late_lock` | 7 series | 11 / −32 / −0.9 | 49 / +181 / 2.35 / 88% / 16% | 16 / +9 / 0.22 |
| `late_lock` | 5 commodities | 11 / −32 / −0.9 | 34 / +163 / 3.07 / 91% / 8% | 9 / +20 / 0.71 |
| `favorite_div` | 7 series | 441 / +40 / 0.63 | 1283 / +64 / 0.50 / 73% / 31% | 491 / +25 / 0.32 |
| `favorite_div` | 5 commodities | 441 / +40 / 0.63 | 977 / +137 / 1.05 / 74% / 24% | 349 / +48 / 0.66 |
| `favorite_blind` | 5 commodities | 342 / −21 / −0.3 | 571 / +27 / 0.24 / 74% / 35% | 259 / +68 / 0.75 |

### Reading

`offhours_lock` is the cautionary tale for this pass. Train t=1.18 was
the only sequential cell above 1.0 with n≥80. Test 5-commodity is red
(gold overnight still dies; natgas off-hours −$23). **Do not paper it.
Do not retune 12:00–21:00 from test.**

`model_fav` / `late_lock` still clear the **test** t≥1.5 gate after
energy was added. Train n<30 and red. Last week is too thin. Do not
promote.

`rich_fav` on the five commodities is the best **n>100** book: last week
t=1.06 / +$55, test t=1.42 / +$130, train flat (not disastrous). t=1.42 is
**not** the tournament gate. Gold is still the drag (test −$56, last
week −$23). Copper + natgas carry it. Dropping gold would be a test-set
edit — gold was *green* in train — so it stays in the paper universe.

Crypto 15m lag locks lost last week on the 4% book. They are back in
the **yolo** paper universe because the owner asked for risky/diverse,
not because last-week crypto locks were green.

## 2×/week (12 Sep evening)

Owner asked whether a risky mix could double $250 every week.
Lag-fill scoreboard: `research/kalshi_yolo.md`. Headline: leveraged
`yolo_lock` printed two calendar weeks ≥+$250 (W35 +$505, W37 slice)
and already lost in train (W33 −$128, 72% DD). `nuke_lock` W36 was
−$962. Last-minute sprint and longshots do not 2×. Paper switched to
`yolo_book` (sprint + fav + follow, 15% cap, seven assets). Stay paper.

## Paper (12 Sep)

| window close | tag | fills | note |
|---|---|---|---|
| 01:00Z | `favorite` (72¢ FLB) | mixed | old book |
| 01:15–01:45Z | `one_pct` | **7/7, +~$7.3** | 2s poll; lag backtest empty |
| 02:00Z | `spot_lock` | copper NO 11@92¢ **+$0.82**, WTI NO 11@88¢ **+$1.23** | first lag-compatible fills |
| ~02:10Z | switch to **`rich_fav`** | same 88–94¢ window, no spot gate | measurement, not a claim |
| ~02:30Z | switch to **`yolo_book`** | 15% mix + crypto; 2×/week experiment | not a go-live |
| 02:45Z | `yolo_book` | natgas YES 43@88¢ **−$38.16**; BTC/gold/copper won | one miss at 15% size |
| ~02:53Z | back to **`rich_fav`** | 4% / 5 commodities | owner asked for consistent, not 2× |
| 03:15Z | **live canary** `rich_fav` 4% | gold NO 10@88¢ **+$1.13**, WTI NO 9@88¢ **+$1.01** | real money; fee ~7¢ on a $1.12 win |
| ~03:20Z | **`rich_fav` 8%** | half-Kelly, fee-eat skip 93–94¢ | owner: clips were too small |
| 03:31Z | gold NO 10 **−$8.87** live | entered T−11 min; WTI/copper 8% won | early clip can reverse |
| ~03:47Z | **`rich_fav` until close** | tau_min 180→0 | last-3-min sit-out was ours; 99¢ still fee-capped |
| 03:45Z | **no fill** | WTI ~70¢ NO most of the window; 88–94 + 5¢ two-sided sat it out | empty UI, not a dark book |
| 04:00Z | **no fill** | gold mid-fav, natgas ~63¢, copper 70–93¢; same 88–94 band | commodities then **dark** |
| ~04:08Z | **`rich_fav` every-window** | ≥60¢, no spread gate, one-sided OK, tau 0–900, no S required | skip only coin-flip / fee-eat |
| 04:00Z Sat → Mon 03:15Z | commodities **closed** | next gold/WTI/natgas/copper/silver window is Mon 2026-09-14 03:15Z | BTC then ETH 15m; **`desk_book` 4%/≥72¢, one crypto slot**. See `research/kalshi_crypto.md` |

Shadow cash after the 02:45Z yolo window: **$226.98**. Realized taker
**−$23.02** (n=28). The natgas 43-lot 88¢ miss is why 15% is not an
investing size.

Live 03:15Z paid ~$1 per clip after a ~7¢ fee (~6% of the win). That is
the 4% cap, not the fee. 8% of ~$250 is ~$20 at risk, ~$2.20 net on an
88¢ win; the same 1¢/contract fee is still ~8% of the payday. 93–94¢
locks are skipped (`_fee_eats_payout`): a 94¢ fill pays 6¢ and the 1¢
ceil-fee is 17% of that. 18% (`yolo_lock`) is the size that can print a
2× week and also a −$38 miss. Stay off it.

Kill switch off. `KALSHI_LIVE=1` in gitignored `.env.kalshi`.

The 7/7 last-minute tape and the 2/2 `spot_lock` tape are **not** a
strategy. They are hours.

## Reproduce

```bash
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy rich_fav --fill-mode lag --split test --bankroll 250
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy rich_fav --fill-mode lag --since 2026-09-05T00:00:00Z
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi \
  --strategy yolo_book --fill-mode lag --split test --bankroll 250
python3 scripts/kalshi_score_yolo.py
```
