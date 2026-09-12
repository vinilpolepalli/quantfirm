#!/usr/bin/env bash
# Supervisor for the Kalshi 15-minute commodity paper desk.
#
# Runs the LangGraph agent back-to-back so the book keeps trading without
# a human restarting it. The engine is single-shot (persist + exit); this
# loop makes it continuous.
#
# Failure modes covered:
#   * session end (~110 min)   -> loop restarts it
#   * engine CRASH             -> loop restarts it
#   * engine HANG              -> watchdog kills it, loop restarts it
#     (2026-09-11: wedged at 17:10Z with the process still alive and burned
#     ~55 min because the supervisor only reacted to process exit.)
#   * open-count flake         -> start the session anyway (do NOT sleep 10m
#     and miss the window). Only sleep when the API says every series is dark.
#   * container restart        -> hourly check-in / 15-min timer re-launches
#
# Writes a PID file so liveness can be checked without pgrep self-matching.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SESSION_MIN="${SESSION_MIN:-110}"
METALS="${METALS:-gold,silver,copper,wti,natgas,btc,eth}"
STRATEGY="${STRATEGY:-one_pct}"
BANKROLL="${BANKROLL:-250}"
LOG="${LOG:-state/kalshi_paper_loop.log}"
PIDFILE="${PIDFILE:-state/kalshi_paper_loop.pid}"
DECISIONS="state/kalshi_paper_decisions.jsonl"
STALE_S="${STALE_S:-300}"   # engine must log a decision at least this often
DARK_SLEEP_S="${DARK_SLEEP_S:-90}"
LOG="${LOG:-state/kalshi_paper_loop.log}"
PIDFILE="${PIDFILE:-state/kalshi_paper_loop.pid}"
DECISIONS="state/kalshi_paper_decisions.jsonl"
STALE_S="${STALE_S:-300}"   # engine must log a decision at least this often
DARK_SLEEP_S="${DARK_SLEEP_S:-90}"

mkdir -p state
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
log "supervisor start (pid $$): ${SESSION_MIN}min sessions, metals=${METALS}"

open_count() {
  # Single integer on stdout. "fail" if the probe itself died.
  local n
  n=$(timeout 45 python3 -m quantfirm.kalshi.cli open-count 2>/dev/null | tail -n 1 | tr -cd '0-9')
  if [ -z "$n" ]; then
    echo fail
  else
    echo "$n"
  fi
}

while true; do
  n=$(open_count)
  if [ "$n" = "fail" ]; then
    log "open-count failed; starting session anyway"
  elif [ "$n" -eq 0 ]; then
    log "no open commodity window; sleeping ${DARK_SLEEP_S}s"
    sleep "$DARK_SLEEP_S"
    continue
  else
    log "open windows=$n"
  fi

  log "starting ${SESSION_MIN}min session strategy=${STRATEGY}"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.kalshi.cli agent \
      --minutes "$SESSION_MIN" --no-demo --no-maker --log-decisions \
      --metals "$METALS" --strategy "$STRATEGY" --bankroll "$BANKROLL" \
    >> "$LOG" 2>&1 &
  engine_pid=$!

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
  python3 -m quantfirm.kalshi.cli heartbeat >/dev/null 2>&1 || true
  sleep 20
done
