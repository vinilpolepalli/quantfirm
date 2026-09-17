# OSS prediction-market skills — can they make money on Kalshi? (2026-09-17)

**Verdict: do not run any of these bots live. Lift the operating doctrine, not the strategies.**

Reproduce (public data only, no orders):

```bash
python3 -m unittest tests.test_weather_brackets tests.test_kalshi_ladder tests.test_kalshi.TestBankSweep -q
python3 scripts/kalshi_oss_skills_eval.py --offline
python3 scripts/kalshi_oss_skills_eval.py --hist-candles   # public books + morning-candle fade
```

This pass does not touch `desk_book`, does not create `state/INCENTIVE_LIVE`,
and does not lift a kill switch.

## Verdict table

| source | what they sell | on this desk |
|---|---|---|
| [agiprolabs/claude-trading-skills](https://github.com/agiprolabs/claude-trading-skills) `prediction-market-strategy` | maker fade of 5–20¢ longshots; fee-aware θ; phantom-edge catalog | **doctrine is good; the fade is not a raise.** Morning-candle fade on 48 settled city-days: **66** cheap YES legs, hit **7/66 = 10.6%**, taker **−$1.21**, maker print-replay (upper bound) **+$0.56**. Same 12-day ensemble take is **−$12.29**. |
| same repo `prediction-market-live-ops` + [agiprolabs/kalshi-stack](https://github.com/agiprolabs/kalshi-stack) | backtest → paper → micro-probe → ratchet; truthful cancels; print-replay is an upper bound | **lift this.** Written as `skills/kalshi-agent-onboarding/SKILL.md`. `classify_cancel` / `cancel_order_checked` are now in `quantfirm/kalshi/client.py`. |
| same repo `kalshi-weather-markets` | 2°F inclusive brackets, Gaussian +½ continuity correction, ticker date not `close_time`, CLI ≠ METAR, LST ≠ DST | **formulas lifted** to `quantfirm/kalshi/weather_brackets.py`. Mapper + station table already existed. Do not paper weather. |
| same repo `kalshi-crypto-index-markets` | hourly/daily BTC/ETH/SPX/NDX ranges; longshot-sell; they call hourly crypto "too sparse / HFT" | We already measured complete-hour **sum(ask) ~$3** and 0 executable dutch. Their own evidence is ~50 index trades. Not a sleeve. |
| [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills), [atompilot/polymarket-skill](https://github.com/atompilot/polymarket-skill), [mjunaidca/polymarket-skills](https://github.com/mjunaidca/polymarket-skills) | Poly auth/CLOB/fees/paper trader | No Polymarket orders. Paper-first + "don't load the live skill" is the pattern to copy. We already paper Poly as a read-only tape. |
| [joinQuantish/skills](https://github.com/joinQuantish/skills) | Kalshi skill via Solana / DFlow | Wrong rails for this CFTC account. Skip. |
| [machina-sports/sports-skills](https://github.com/machina-sports/sports-skills) | ESPN / xG / Kalshi+Poly prices, no keys | Read-only data is fine. Their own rule: never load the trading skill unless the human asks to trade. Copy that. |
| [suislanchez/polymarket-kalshi-weather-bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot) | 31-member GFS + Kelly, README "$1.8k highest profit" | Same ensemble-vs-book idea we already lost on. **$1.8k is the honest retail-scale number.** It is a counterweight to million-dollar claims, not a target. |

## What we already knew (do not re-chase)

`research/kalshi_oss.md` scored earlier OSS *takers* on the 15m harvest. Hamad wait-7, persist, directional 25–58¢, and candle-maker translations lost or failed the both-names bar. Live stayed `desk_book`.

`research/kalshi_div_nowcast.md` already killed:

- weather ensemble take: 12 city-days, modal hit **2/12 = 17%** (chance among 6 bands), **−$12.29**
- hourly range dutch: complete-hour sum(ask) **$3.14**
- weather dutch: sum(ask) 1.01–1.06, fees eat the 0.99 minute

`quantfirm/kalshi/maker.py` still reports a huge candle P&L and is still an artifact. Do not quote it.

## What this pass recomputed

### Forecast take (unchanged, re-read)

From `research/kalshi_div_weather_hist.json`, scored city-days only (12 of 48 rows have archived members):

| | n | pnl |
|---|---:|---:|
| ensemble take, 5 lots, skip <5¢ and >92¢ | 37 | **−$12.29** |
| modal hit | 2/12 | chance |

A Gaussian with σ=2.5°F on the winning bracket does not rescue it. On the days we can map, `gauss_p(winner)` is 0–0.31. Forecast skill is not an edge. The book already has the NWP.

### Favorite–longshot fade (the skill's surviving claim)

Fade every YES ask in **5–20¢**, hold to venue `result`, one lot. Two samples:

| sample | mode | n | pnl | cheap YES that won |
|---|---|---:|---:|---:|
| 12 mornings the ensemble already quoted | taker (pay 1 − bid) | 14 | **−$0.77** | 2 |
| same | maker at the cheap ask (upper bound) | 14 | **−$0.40** | 2 |
| 48 settled city-days, 12:00 UTC candles | taker | 66 | **−$1.21** | **7** |
| same | maker print-replay (upper bound) | 66 | **+$0.56** | 7 |

Hit rate on the 66-leg tape is **7/66 = 10.6%**. The band is 5–20¢. That is roughly fair, not “a 10¢ contract wins ~2%”. Taker losses on the seven hits are **−$6.31**; the 59 misses make **+$5.10**. Maker upper-bound is **+$0.56 total** (~0.8¢/contract) *before* queue and adverse selection — the skill’s own live-ops note says print-replay of passive fills is an upper bound, not an estimate.

Elephant rows (taker):

- `KXHIGHNY-26SEP10-T85` at 10¢ — Central Park printed the tail vs an 87.4°F grid mean. **−$0.92**
- `KXHIGHNY-26AUG28-B84.5` at 5¢. **−$0.97**
- `KXHIGHCHI-26SEP04-B93.5` at 14¢. **−$0.89**
- `KXHIGHCHI-26SEP03-B92.5` at 13¢. **−$0.92**
- `KXHIGHTBOS-26SEP09-B76.5` at 13¢. **−$0.89**
- `KXHIGHTBOS-26SEP07-B81.5` at 18¢. **−$0.84**
- `KXHIGHTBOS-26AUG30-B86.5` at 16¢. **−$0.88**

n=66 is still not a raise. Do not paper it.

### Live public books (2026-09-17T23:36Z, no orders)

| book | legs | sum(ask) | dutch | 5–20¢ YES asks |
|---|---:|---:|---|---:|
| weather highs (12 open events) | 6-ish each | 1.03–1.08 | **0 tradeable** | 7 real (volume hundreds–5k, size 2–76) |
| `KXBTC-26SEP1720` | 188 | **$4.09** | no (sell: missing_bid) | 18, advertised size 70, **volume 0** |
| `KXETH-26SEP1720` | 300 | **$13.81** | no (sell: missing_bid) | 49, size 70, **volume 0** |
| `KXINX-26SEP18H1600` | 30 | **$2.52** | no | 13, some real volume |

Hourly crypto “cheap asks” are the empty-room wings we already refuse. Weather tails tonight are real quotes and still not a dutch. The skill’s own hourly-crypto row is “too sparse / HFT”. Live agrees.

### Incentive book (recomputed, not inherited)

`scripts/kalshi_incentive_paper.py:verdict` on `state/kalshi_incentive_paper.json` at eval time:

- **STALLED** — last tick 2026-09-17T19:50Z, then >3h silence. The collector is down; nothing below that line is being measured.
- Run length **31.4h** vs the 48h gate. Even with a live collector this is still `INSUFFICIENT`.
- Accrued total **$57.75** on $257 notional is **not a daily rate**. Do not annualise it and do not quote the trailing-24h print while the gate is STALLED.

OSS bots do not change this gate. Arming still takes five conditions in `docs/KALSHI_INCENTIVE.md`.

## What to actually lift

1. **Agent onboarding gate** — `skills/kalshi-agent-onboarding/SKILL.md`. Paper default. Pre-declared kills. Third-party live-executor skills stay unloaded until a human names the desk and the size.
2. **Cancel classification** — a 404 is not a cancel. Use `cancel_order_checked`. Do not swallow and re-post.
3. **Weather bracket math** — inclusive 2°F, continuity correction, ticker date, API `strike_type`. Already the way `ladder.py` / `nowcast.py` think; the Gaussian helper is now importable.
4. **Paper-first module split** (mjunaidca / machina-sports) — scanner and paper may load; the order path does not.

`kalshi-stack` is infrastructure (Rust mirror, shard routing, paper fills off the tape). We already have a signed v2 client, halt files, and a paper engine. Shard-index routing is the one incident in their ledger we have not paid for yet; it matters if we ever rest maker quotes on multiple engines. Not a reason to vendor their bot.

## What not to do

- Do not `pip install` a weather bot and point it at prod.
- Do not paper a KXHIGH sleeve on this tape.
- Do not paper hourly-range dutch.
- Do not promote a maker fade because the literature says makers win. Whelan is a prior; our fill is the test.
- Do not treat $1.8k (weather bot) or any inherited P&L as capacity.
- Do not copy Polymarket CLOB code onto Kalshi. Different contract, different fee, different settlement.

## Capacity, if anything ever works

Retail weather bots that publicly report a number report **low thousands**, not millions. The incentive board still pays **0.62%/day** on resting capital as an accounting identity (`docs/KALSHI_INCENTIVE.md`). A $257 book cannot compound its way out of that. Selection is bounded.

The 15m live path remains `desk_book` behind `state/KILL_SWITCH_KALSHI`. This research does not change it.
