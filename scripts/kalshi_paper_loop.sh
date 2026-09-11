#!/usr/bin/env bash
# Supervisor for the Kalshi 15M metals paper desk.
#
# Runs the paper engine back-to-back indefinitely, so the desk keeps trading
# without a human (or an agent turn) restarting it every session. The engine
# itself is deliberately single-shot — it persists state per tick and exits —
# so this loop is what turns it into a continuous desk.
#
# Two failure modes are covered:
#   * session end (every ~110 min)  -> this loop restarts it
#   * container restart             -> the hourly Routine check-in restarts
#                                      THIS loop (state is on disk, so the
#                                      books carry across cleanly)
#
# Market-dark periods (Sat 04:00Z -> Sun 22:00Z, Thu 07:00-09:00Z maintenance)
# need no special handling: the engine simply finds no open market and idles
# cheaply, but we back off a little to avoid pointless API polling.
#
#   ./scripts/kalshi_paper_loop.sh            # run forever
#   SESSION_MIN=110 ./scripts/kalshi_paper_loop.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SESSION_MIN="${SESSION_MIN:-110}"
METALS="${METALS:-gold,silver}"
LOG="${LOG:-state/kalshi_paper_loop.log}"

echo "[$(date -u +%FT%TZ)] supervisor start: ${SESSION_MIN}min sessions, metals=${METALS}" >> "$LOG"

while true; do
  # Is there an open market right now? If not, idle instead of burning API calls.
  open_count=$(timeout 60 python3 -m quantfirm.kalshi.cli status 2>/dev/null \
      | grep -cE 'KX(GOLD|SILVER)15M-.*book=[0-9]' || echo 0)

  if [ "${open_count:-0}" -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] no open metals market; sleeping 10m" >> "$LOG"
    sleep 600
    continue
  fi

  echo "[$(date -u +%FT%TZ)] starting ${SESSION_MIN}min session" >> "$LOG"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.kalshi.cli paper \
      --minutes "$SESSION_MIN" --no-demo --log-decisions --metals "$METALS" \
    >> "$LOG" 2>&1
  rc=$?
  echo "[$(date -u +%FT%TZ)] session exited rc=$rc" >> "$LOG"

  # brief pause so a crash-looping engine cannot spin the API
  sleep 20
done
