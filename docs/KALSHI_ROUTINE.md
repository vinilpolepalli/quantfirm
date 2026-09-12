# 24/7 Kalshi 15-minute desk — routines

The book is `desk_book`: **gold, silver, copper, WTI, natgas, BTC, ETH**.
Paper bankroll $250.

Commodities: first **≥60¢** favorite from window open **until close**,
**8% stake** (half-Kelly). Crypto: **4% of the book each (~$9–10) /
≥60¢ / until close** — clip every interval that has a real favorite;
sit coin-flips. BTC and ETH are independent, not a split budget. BTC and
ETH can both be on. Sit out 50/50 books, longshots, and when the quadratic
fee eats ≥15% of the win (that is what keeps 99¢ last ticks out — not a
time gate). Maker quotes off. `yolo_book` / `nuke_lock` / `longshot` stay
registered and off this loop.

Live canary is **on** 24/7 in this environment (`KALSHI_LIVE=1` in gitignored
`.env.kalshi`). Real orders go out. Stop with `touch state/KILL_SWITCH_KALSHI`.
Do not revert to paper-only on a stale timer prompt.

## 1. Persistent supervisor (primary)

```bash
cd /path/to/quantfirm
./scripts/kalshi_paper_loop.sh
```

110-minute LangGraph sessions, 90s sleep when every series is dark,
watchdog if no decision for 5 minutes. Heal with:

```bash
python scripts/kalshi_desk_checkin.py
```

## 2. Cursor Cloud timer

Fires at `:13/:28/:43/:58` UTC (supervisor heal). Does not start a
second agent. Commodities and crypto can fill until close. Do not start a second agent.

## 3. Claude Routine (no VPS)

| Field | Value |
|---|---|
| Cron | `13,28,43,58 * * * *` UTC |
| New session on fire | yes |
| Prompt | below |

```
You are the Kalshi 15-minute desk for quantfirm.
Bankroll $250. Strategy: desk_book.
Commodities (gold,silver,copper,wti,natgas): rich_fav 8% ≥60¢ until close.
BTC and ETH: 4% of the book each (~$9–10) ≥60¢ until close so every real-favorite interval can clip. Both can be on; do not split one 4% budget. Sit out 50/50 and 99c last ticks via fee-eat.

1. If state/KILL_SWITCH_KALSHI exists, stop.
2. python scripts/kalshi_desk_checkin.py
3. python -m quantfirm.kalshi.cli heartbeat
4. Confirm the supervisor pidfile (state/kalshi_paper_loop.pid) is alive.
   Heal with checkin only. Do NOT start a second agent.
5. Keep live on if `.env.kalshi` has KALSHI_LIVE=1. Do not unset it.
   Do not switch commodities back to 4% or to yolo_book.
   Do not last-minute lock crypto. Do not re-add a last-2-min sit-out.
6. Reply with: open windows, fills this window, shadow + live cash, realized,
   strategy name, universe, any halt.

Do not paper yolo_book, nuke_lock, offhours_lock, or longshot.
Do not buy 99c last ticks (fee-eat / price_max, not a time gate).
Do not buy 18–50¢ crypto longshots.
```

## 4. GitHub backstop

`.github/workflows/kalshi.yml` at `:05/:20/:35/:50` UTC after merge to
`main` (minute 5 of each window). Same `desk_book` command, `--no-maker`.

Kill switch: `touch state/KILL_SWITCH_KALSHI`
