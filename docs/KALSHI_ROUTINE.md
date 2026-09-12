# 24/7 Kalshi 15-minute desk — routines

The book is `one_pct` on **gold, silver, copper, WTI, natgas, BTC, ETH**.
Paper bankroll $250. Sit out 50/50 books; take only a 90–97¢ lock in the
last ~90 seconds, sized so a win is ~1% of the book. Maker quotes off.
Real orders stay off until you set the key **and** `KALSHI_LIVE=1`
**and** pass `--live`.

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

Fires at `:13/:28/:43/:58` UTC (just before the last minute of each
window). Heals a dead supervisor. Does not start a second agent.

## 3. Claude Routine (no VPS)

| Field | Value |
|---|---|
| Cron | `13,28,43,58 * * * *` UTC |
| New session on fire | yes |
| Prompt | below |

```
You are the Kalshi 15-minute desk for quantfirm.
Bankroll $250. Strategy: one_pct. Universe: gold,silver,copper,wti,natgas,btc,eth.

1. If state/KILL_SWITCH_KALSHI exists, stop.
2. python scripts/kalshi_desk_checkin.py
3. python -m quantfirm.kalshi.cli status
4. If the supervisor is not already running a long session, run:
   python -m quantfirm.kalshi.cli agent --minutes 13 --poll 2 --no-demo --no-maker \
     --log-decisions --strategy one_pct --bankroll 250 \
     --metals gold,silver,copper,wti,natgas,btc,eth
   Add --live ONLY if KALSHI_LIVE=1 is set and the owner enabled live.
5. Reply with: open windows, fills, shadow cash, realized, any halt.

Do not buy 72c favorites. Do not buy 99c last ticks. Do not change params.
```

## 4. GitHub backstop

`.github/workflows/kalshi.yml` at `:13/:28/:43/:58` UTC after merge to
`main`. Same `one_pct` command, `--no-maker`.

Kill switch: `touch state/KILL_SWITCH_KALSHI`
