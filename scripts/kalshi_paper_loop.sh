#!/usr/bin/env bash
# Supervisor for the Kalshi 15M metals paper desk.
#
# Runs the paper engine back-to-back indefinitely so the desk keeps trading
# without a human restarting it. The engine is deliberately single-shot (it
# persists state per tick and exits); this loop makes it continuous.
#
# Failure modes covered:
#   * session end (~110 min)   -> loop restarts it
#   * engine CRASH             -> loop restarts it
#   * engine HANG              -> watchdog below kills it, loop restarts it.
#     (Learned the hard way: on 2026-09-11 the engine wedged at 17:10Z with
#     the process still alive and burned ~55 min of trading, because the
#     supervisor only reacted to process exit.)
#   * container restart        -> hourly Routine re-launches this script
#
# Writes a PID file so liveness can be checked without pgrep self-matching.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SESSION_MIN="${SESSION_MIN:-110}"
METALS="${METALS:-gold,silver,copper,wti,natgas}"
STRATEGY="${STRATEGY:-favorite_div}"
BANKROLL="${BANKROLL:-250}"
LOG="${LOG:-state/kalshi_paper_loop.log}"
PIDFILE="${PIDFILE:-state/kalshi_paper_loop.pid}"
DECISIONS="state/kalshi_paper_decisions.jsonl"
STALE_S="${STALE_S:-300}"   # engine must log a decision at least this often

echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
log "supervisor start (pid $$): ${SESSION_MIN}min sessions, metals=${METALS}"

while true; do
  open_count=$(timeout 60 python3 -m quantfirm.kalshi.cli status 2>/dev/null \
      | grep -cE 'KX(GOLD|SILVER|WTI|COPPER|NATGAS)15M-.*book=' || echo 0)
  if [ "${open_count:-0}" -eq 0 ]; then
    log "no open metals market; sleeping 10m"
    sleep 600
    continue
  fi

  log "starting ${SESSION_MIN}min session"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.kalshi.cli agent \
      --minutes "$SESSION_MIN" --no-demo --log-decisions \
      --metals "$METALS" --strategy "$STRATEGY" --bankroll "$BANKROLL" \
    >> "$LOG" 2>&1 &
  engine_pid=$!

  # ---- watchdog: kill the engine if it stops making decisions
  while kill -0 "$engine_pid" 2>/dev/null; do
    sleep 30
    [ -f "$DECISIONS" ] || continue
    now=$(date +%s)
    mtime=$(stat -c %Y "$DECISIONS" 2>/dev/null || echo "$now")
    age=$(( now - mtime ))
    if [ "$age" -gt "$STALE_S" ]; then
      log "WATCHDOG: no decision for ${age}s -> killing engine pid $engine_pid"
      kill -9 "$engine_pid" 2>/dev/null
      break
    fi
  done
  wait "$engine_pid" 2>/dev/null
  log "session ended (rc=$?)"
  sleep 20
done
