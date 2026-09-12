# 24/7 Kalshi 15-minute desk — routines

The book is `yolo_book` on **gold, silver, copper, WTI, natgas, BTC, ETH**.
Paper bankroll $250. Mix: last-90s 88–97¢ sprint, else first 88–94¢
favorite (3–11 min left, no spot gate), else opening-impulse follow.
15% stake cap, 40% daily stop. Maker quotes off. `nuke_lock` / `longshot`
stay registered and off this loop.

Real orders stay off until you set the key **and** `KALSHI_LIVE=1`
**and** pass `--live`. This mix is a volatility experiment, not a
2×/week claim (`research/kalshi_yolo.md`).

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
Bankroll $250. Strategy: yolo_book. Universe: gold,silver,copper,wti,natgas,btc,eth.

1. If state/KILL_SWITCH_KALSHI exists, stop.
2. python scripts/kalshi_desk_checkin.py
3. python -m quantfirm.kalshi.cli heartbeat
4. Confirm the supervisor pidfile (state/kalshi_paper_loop.pid) is alive.
   Heal with checkin only. Do NOT start a second agent.
5. Reply with: open windows, fills this window, shadow cash, realized,
   strategy name, universe, any halt.

Do not paper nuke_lock, offhours_lock, or longshot. Do not buy 99c last ticks.
Do not change params. Do not enable live. KALSHI_LIVE must stay unset.
```

## 4. GitHub backstop

`.github/workflows/kalshi.yml` at `:05/:20/:35/:50` UTC after merge to
`main` (minute 5 of each window). Same `yolo_book` command, `--no-maker`.

Kill switch: `touch state/KILL_SWITCH_KALSHI`
