# 24/7 Kalshi 15-minute desk — routines

The book is `favorite_div` on **gold, silver, copper, WTI, natgas**.
Paper bankroll $250. Real orders stay off until you set the key **and**
`KALSHI_LIVE=1` **and** pass `--live`.

GitHub Actions cannot poll a 15-minute market honestly on the free minute
budget. Two loops cover the clock:

## 1. Persistent supervisor (best)

On any always-on host (this cloud box, a VPS, your laptop):

```bash
cd /path/to/quantfirm
# key, when you have it:
# export KALSHI_PROD_KEY_ID=...
# export KALSHI_PROD_PRIVATE_KEY_PATH=$HOME/kalshi.pem
# export KALSHI_LIVE=1          # omit this to stay paper-only
./scripts/kalshi_paper_loop.sh &
```

The loop:
- sleeps 10 minutes when no commodity window is open
- otherwise runs a 110-minute LangGraph session on all five series
- restarts itself on crash / hang (5-minute decision watchdog)
- writes `state/kalshi_paper_loop.pid`

Hourly, run the check-in so a dead supervisor comes back:

```bash
python scripts/kalshi_desk_checkin.py
```

## 2. Claude Routine (no VPS)

Create a scheduled Claude Routine (same pattern as the equity desk):

| Field | Value |
|---|---|
| Cron | `*/15 * * * *` UTC |
| New session on fire | yes |
| Connectors | GitHub only (plus Kalshi env if the host has it) |
| Prompt | below |

```
You are the Kalshi 15-minute commodities desk for quantfirm.
Repo: this checkout. Bankroll $250. Strategy: favorite_div.
Universe: gold, silver, copper, wti, natgas.

1. If state/KILL_SWITCH_KALSHI exists, stop. Do not trade.
2. python -m quantfirm.kalshi.cli status
3. python -m quantfirm.kalshi.cli agent --minutes 13 --poll 2 --no-demo \
     --log-decisions --strategy favorite_div --bankroll 250 \
     --metals gold,silver,copper,wti,natgas
   Add --live ONLY if KALSHI_LIVE=1 is already in the environment and
   the owner has explicitly enabled live trading. Default is paper.
4. python scripts/kalshi_desk_checkin.py
5. Reply with: open windows, fills this session, cash per book, any halt.

Do not change strategy parameters. Do not buy longshots. One slot per
commodity cluster (gold/silver share a side; wti/natgas share a side;
copper is its own).
```

## 3. GitHub backstop

`.github/workflows/kalshi.yml` fires at :03/:18/:33/:48 UTC, runs a
2-minute tick, commits state. Add repo secrets when the key lands:

- `KALSHI_PROD_KEY_ID`
- `KALSHI_PROD_PRIVATE_KEY` (PEM body)
- `KALSHI_LIVE` = `1` only when you want real orders from Actions

## Kill switch

```bash
touch state/KILL_SWITCH_KALSHI
```

Entries halt on the next tick. Nothing in the graph re-enables trading.
