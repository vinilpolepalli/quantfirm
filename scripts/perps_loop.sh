#!/usr/bin/env bash
# Supervisor for the Kalshi perps desk (shadow by default).
#
# The strategy is daily, so the agent ticks hourly: it accrues funding, keeps
# the server-side stops fresh, checks the drawdown ladder, and on the weekly
# rebalance day trades toward the target. Sessions are bounded so this loop
# can restart them; a hang is caught by the decisions-file watchdog.
#
# Live requires ALL of: config/perps.json live=true, KALSHI_LIVE=1 in the
# environment (or .env.kalshi), a perps API key, and no
# state/KILL_SWITCH_PERPS. Anything else runs shadow.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SESSION_MIN="${SESSION_MIN:-350}"
POLL_S="${POLL_S:-3600}"
ADAPTER="${ADAPTER:-shadow}"
LOG="${LOG:-state/perps_loop.log}"
PIDFILE="${PIDFILE:-state/perps_loop.pid}"
DECISIONS="state/perps_decisions.jsonl"
STALE_S="${STALE_S:-7800}"     # two hourly ticks without a decision → restart

if [ -f .env.kalshi ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.kalshi
  set +a
fi
KALSHI_LIVE="${KALSHI_LIVE:-0}"
if [ "$ADAPTER" = "live" ] && [ "$KALSHI_LIVE" != "1" ]; then
  echo "ADAPTER=live but KALSHI_LIVE!=1; refusing" >&2
  exit 2
fi

mkdir -p state
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT
log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
log "perps supervisor start (pid $$): adapter=$ADAPTER session=${SESSION_MIN}min poll=${POLL_S}s"

while true; do
  if [ -f state/KILL_SWITCH_PERPS ]; then
    log "KILL_SWITCH_PERPS present; sleeping 10m"
    sleep 600
    continue
  fi
  # refresh the daily panel once per session (public data; failures are logged, not fatal)
  timeout 900 python3 -m quantfirm.perps.cli update-data >> "$LOG" 2>&1 || log "update-data failed"
  log "starting ${SESSION_MIN}min session"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.perps.cli agent --adapter "$ADAPTER" --minutes "$SESSION_MIN" --poll "$POLL_S" \
    >> "$LOG" 2>&1 &
  engine_pid=$!
  while kill -0 "$engine_pid" 2>/dev/null; do
    sleep 60
    [ -f "$DECISIONS" ] || continue
    now=$(date +%s); mtime=$(stat -c %Y "$DECISIONS" 2>/dev/null || echo "$now")
    if [ $(( now - mtime )) -gt "$STALE_S" ]; then
      log "WATCHDOG: no decision for $(( now - mtime ))s -> killing engine pid $engine_pid"
      kill -9 "$engine_pid" 2>/dev/null
      break
    fi
  done
  wait "$engine_pid" 2>/dev/null
  log "session ended (rc=$?)"
  sleep 30
done
