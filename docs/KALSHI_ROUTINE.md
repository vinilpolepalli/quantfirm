# 24/7 Kalshi 15-minute desk — routines

**First-time setup (account, API key, env, live switch):** `docs/KALSHI_15M.md`.

The book is `desk_book`: **gold, silver, copper, WTI, natgas, BTC, ETH**.
Paper bankroll $250.

Commodities **wait the first 3 minutes**, then **8%** / ≥75¢ (no Poly
15m book). BTC waits 3 min, ETH waits 5 min; both **4% of the book
each (~$9–10) / ≥75¢**, sit the last 2 minutes, and sit if Polymarket's
15m favorite disagrees. Independent books — they do **not** have to
agree. Sit out 60–74¢, longshots, and when the quadratic fee eats ≥15%
of the win (99¢ last ticks). Do not raise 75¢ — live 78¢+ is red.
Maker quotes off. `yolo_book` / `nuke_lock` / `longshot` stay
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

Check-in also heals the **paper** Poly sleeve (`state/kalshi_poly_paper.pid`).
That is not a second live agent.

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
Commodities wait 3 min then 8% ≥75¢. BTC wait 3 + last-2-min sit; ETH wait 5 + last-2-min sit; both 4% each (~$9–10) ≥75¢; sit if Polymarket 15m disagrees. Names are independent (BTC YES and ETH NO in the same window is allowed). Sit out 60–74¢. 99c last ticks via fee-eat; crypto also sits last 2 min.

1. If state/KILL_SWITCH_KALSHI exists, stop.
2. python scripts/kalshi_desk_checkin.py
3. python -m quantfirm.kalshi.cli heartbeat
4. Confirm the supervisor pidfile (state/kalshi_paper_loop.pid) is alive.
   Heal with checkin only. Do NOT start a second agent.
5. Keep live on if `.env.kalshi` has KALSHI_LIVE=1. Do not unset it.
   Do not switch commodities back to 4% or to yolo_book.
   Do not last-minute lock crypto. Do not raise the 75¢ bar.
   ETH wait 5 + crypto last-2-min sit + Poly confirm is the live overlay.
   Do not switch the whole book to poly_book.
   A separate paper sleeve (`scripts/kalshi_poly_paper_loop.sh`) still
   shadows Poly vs Kalshi; compare at EOD with `poly-compare`. Do not
   start a second live agent.
6. Reply with: open windows, fills this window, shadow + live cash, realized,
   strategy name, universe, any halt. Owner handles Kalshi → BofA
   withdrawals; do not POST /portfolio/withdrawals.

Do not paper yolo_book, nuke_lock, offhours_lock, or longshot.
Do not buy 99c last ticks (fee-eat / price_max). Crypto also sits last 2 min.
Do not buy 18–50¢ crypto longshots.
```

## 4. GitHub backstop

`.github/workflows/kalshi.yml` at `:05/:20/:35/:50` UTC after merge to
`main` (minute 5 of each window). Same `desk_book` command, `--no-maker`.

Kill switch: `touch state/KILL_SWITCH_KALSHI`
