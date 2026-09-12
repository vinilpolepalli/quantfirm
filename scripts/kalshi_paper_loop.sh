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
METALS="${METALS:-gold,silver}"
LOG="${LOG:-state/kalshi_paper_loop.log}"
PIDFILE="${PIDFILE:-state/kalshi_paper_loop.pid}"
DECISIONS="state/kalshi_paper_decisions.jsonl"
STALE_S="${STALE_S:-300}"   # engine must log a decision at least this often

echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
log "supervisor start (pid $$): ${SESSION_MIN}min sessions, metals=${METALS}"

while true; do
  # `grep -c` prints "0" AND exits 1 when there are no matches, so a
  # `|| echo 0` fallback appends a SECOND zero -> "0\n0" -> the integer test
  # below errors and the guard fails OPEN. That spun up a full engine session
  # into a closed weekend market every ~5 min (watchdog kill, rc=137, restart)
  # for the whole of 2026-09-12. Assign on failure instead of piping a second
  # value in, then strip anything non-numeric.
  open_count=$(timeout 60 python3 -m quantfirm.kalshi.cli status 2>/dev/null \
      | grep -cE 'KX(GOLD|SILVER)15M-.*book=[0-9]') || open_count=0
  open_count=${open_count//[^0-9]/}
  : "${open_count:=0}"
  if [ "$open_count" -eq 0 ]; then
    log "no open metals market; sleeping 10m"
    sleep 600
    continue
  fi

  log "starting ${SESSION_MIN}min session"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.kalshi.cli paper \
      --minutes "$SESSION_MIN" --no-demo --log-decisions --metals "$METALS" \
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
      # `kill -9` on the `timeout` wrapper does NOT reach its python child:
      # SIGKILL cannot be forwarded. Every watchdog kill therefore ORPHANED a
      # live engine -- 70 accumulated on 2026-09-12, each still polling the API
      # and writing the same state files. They did no harm only because the
      # market was shut; mid-session that is concurrent writers to
      # state/kalshi_paper_{state.json,trades.csv}. Kill the engine by name,
      # not just the wrapper. The supervisor is the sole launcher of these, and
      # pkill never matches itself.
      log "WATCHDOG: no decision for ${age}s -> killing engine $engine_pid + strays"
      kill -TERM "$engine_pid" 2>/dev/null
      pkill -TERM -f 'quantfirm[.]kalshi[.]cli paper' 2>/dev/null
      sleep 3
      kill -KILL "$engine_pid" 2>/dev/null
      pkill -KILL -f 'quantfirm[.]kalshi[.]cli paper' 2>/dev/null
      break
    fi
  done
  wait "$engine_pid" 2>/dev/null
  rc=$?
  # Belt and braces: an engine that outlived the watchdog would silently
  # double-write state, so sweep for strays before starting the next session.
  strays=$(pgrep -cf 'quantfirm[.]kalshi[.]cli paper' || true)
  if [ "${strays:-0}" -gt 0 ]; then
    log "WARNING: $strays stray engine(s) after session end -> killing"
    pkill -9 -f 'quantfirm[.]kalshi[.]cli paper' 2>/dev/null
  fi
  log "session ended (rc=$rc)"
  sleep 20
done
