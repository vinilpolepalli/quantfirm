# 24/7 Kalshi 15-minute desk — routines

The book is `rich_fav` on **gold, silver, copper, WTI, natgas**.
Paper bankroll $250. Sit out 50/50 books; take the first 88–94¢ favorite
(no spot-agree gate), 3–11 minutes before close. **8% stake cap**
(half-Kelly). Skip 93–94¢ when the quadratic fee eats ≥15% of the win.
Maker quotes off. BTC/ETH are harvested for research but not in this paper
book. `yolo_book` / `nuke_lock` / `longshot` stay registered and off this
loop.

Live canary is **on** in this environment (`KALSHI_LIVE=1` in gitignored
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
second agent. The engine itself trades from ~11 minutes left, not only
in the last 90 seconds.

## 3. Claude Routine (no VPS)

| Field | Value |
|---|---|
| Cron | `13,28,43,58 * * * *` UTC |
| New session on fire | yes |
| Prompt | below |

```
You are the Kalshi 15-minute desk for quantfirm.
Bankroll $250. Strategy: rich_fav at 8% stake. Universe: gold,silver,copper,wti,natgas.

1. If state/KILL_SWITCH_KALSHI exists, stop.
2. python scripts/kalshi_desk_checkin.py
3. python -m quantfirm.kalshi.cli heartbeat
4. Confirm the supervisor pidfile (state/kalshi_paper_loop.pid) is alive.
   Heal with checkin only. Do NOT start a second agent.
5. Keep live on if `.env.kalshi` has KALSHI_LIVE=1. Do not unset it.
   Do not switch back to 4% or to yolo_book.
6. Reply with: open windows, fills this window, shadow + live cash, realized,
   strategy name, universe, any halt.

Do not paper yolo_book, nuke_lock, offhours_lock, or longshot.
Do not buy 99c last ticks.
```

## 4. GitHub backstop

`.github/workflows/kalshi.yml` at `:05/:20/:35/:50` UTC after merge to
`main` (minute 5 of each window). Same `rich_fav` command, `--no-maker`.

Kill switch: `touch state/KILL_SWITCH_KALSHI`
