# Kalshi 15-minute commodities desk — this pass

Status: **PAPER**, $250 shadow bankroll, $0 real. Built 2026-09-12 on
`cursor/kalshi-15m-strategies-1c14`, on top of the prior metals desk
(`docs/KALSHI.md`, `docs/HANDOFF.md`).

## What changed

The prior desk proved two things and left one open:

1. A REST-latency **taker** that chases stale quotes **loses** (lag-fill
   −15%, uncontested fills are the winner's-curse subset).
2. A candle **maker** backtest that prints huge P&L is an **artifact**
   (null mid-quoter earns more). Do not quote it.
3. A live **maker** shadow book is the only remaining structural idea,
   and even that P&L is an upper bound (free queue priority).

This pass does not retune `theta` to revive (1). It asks whether any
*other* 15-minute commodity strategy survives an honest $250 / lag-fill
tournament, and it wires the live paper engine to the settlement feed.

## Universe (verified 2026-09-12)

| Series | Asset | Settlement | Typical window volume | Live now |
|---|---|---|---|---|
| `KXGOLD15M` | Gold | Pyth `Metal.Index.GOLD/USD` | ~100k | yes |
| `KXSILVER15M` | Silver | Pyth `Metal.Index.SILVER/USD` | ~50k | yes |
| `KXWTI15M` | WTI | Pyth `Commodities.Index.PYTHOIL/USD` | ~45k | yes |
| `KXCOPPER15M` | Copper | Pyth `Commodities.Index.CU/USD` | ~17k | yes |
| `KXNATGAS15M` | Nat gas | Pyth `Commodities.Index.NATGAS/USD` | ~10k | yes |
| `KXPALLADIUM15M` / `KXPLATINUM15M` | — | Pyth metals | — | listed, dark |
| `KXINX15M` / `KXNDQ15M` | SPX / NDX | Google Finance | — | listed, dark |
| `KXBTC15M` | BTC | CF Benchmarks 60s average | ~1.8M | yes (research only) |

Hours: commodity 15M books were **open on Saturday 2026-09-12** (the prior
note that metals go dark Sat 04:00Z is stale — treat the API as truth).
Fees unchanged: quadratic taker `ceil(0.07·C·P·(1−P))`, maker $0.

Default paper book: **gold, silver, copper, WTI, natgas, BTC, ETH**.
Live strategy: **`one_pct`** — wait until the last ~90 seconds, buy a
90–97¢ favorite whose spot already agrees, size so a win is ~1% of the
$250. Sit out 50/50 books. Maker quotes are off.

1.01^96 ≈ 2.6×/day **only if** almost every window fills. Most windows never
lock; those we skip. A 99¢ last-tick book cannot deliver 1% of bankroll
without putting nearly all of it at risk, so we skip those too.

Correlation slots: gold/silver share a side, WTI/natgas share a side,
BTC/ETH share a side, copper is its own. 24/7 wiring is in
`docs/KALSHI_ROUTINE.md`.

## Live signal

`GET /trade-api/v2/live_data/events/{event_ticker}` returns a 1-second
timeseries whose last print is in the same units as `floor_strike` /
`expiration_value`. That is the settlement-aligned S. Swissquote XAU/XAG
stays as fallback (~7 USD / 16 bp off the gold strike on 2026-09-12 —
too much basis to prefer it). Pyth Hermes `/v2/updates/price/latest`
now returns 401 without an API key.

The paper engine also persists `GET /markets/trades` to
`state/kalshi_paper_tape.jsonl` so maker fills can be replayed.

## Strategies in the tournament

See `quantfirm/kalshi/strategies.py` (parameters frozen) and
`research/kalshi_tournament.md` (the numbers). Families:

| Name | Hypothesis | Why it might survive REST latency |
|---|---|---|
| `ctrl_*` | Drift / fee-drain controls | If these win, we have no edge |
| `oracle_lag` | Prior-desk stale-quote taker | Should lose (replication) |
| `oracle_flow` | Fade uninformed book flow | Taking an overreaction, not chasing a stale ask |
| `favorite_blind` | Whelan FLB on 15M metals | Structural, no race |
| `favorite_confirmed` | FLB + GBM agrees | Same, fewer longshots |
| `late_lock` | Near-certain favorite, last 6 min | Reversal needed is large |
| `open_fade` / `open_follow` | 3-min impulse then fade/follow | Path of S, not book lag |
| `session_favorite` | Favorites in London/NY only | Tighter books, less junk |
| `iv_rich_favorite` | Book IV >> realized → buy favorite | Vol mispricing, not sniping |

Maker remains a **live** experiment. The candle maker backtest is still
invalid; `maker-control` must stay red.

## How to run

```bash
python scripts/kalshi_harvest.py --gzip          # public API; WTI/natgas too
python -m quantfirm.kalshi.cli status
python -m quantfirm.kalshi.cli diagnostics --data data/kalshi --split train
python -m quantfirm.kalshi.cli tournament --data data/kalshi --bankroll 250
python -m quantfirm.kalshi.cli backtest --data data/kalshi --split test \
    --fill-mode lag --bankroll 250
python -m quantfirm.kalshi.cli paper --minutes 60 --no-demo --no-maker \
    --strategy one_pct --bankroll 250 --log-decisions
./scripts/kalshi_paper_loop.sh          # 24/7 supervisor, commodities + BTC/ETH
python scripts/kalshi_desk_checkin.py   # heal + commit heartbeat
```

24/7 wiring is in `docs/KALSHI_ROUTINE.md`. Promotion bar is unchanged
(`docs/KALSHI.md` §8, `docs/HANDOFF.md` §5). A profitable paper hour is
not a go-live.
