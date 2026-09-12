#!/usr/bin/env bash
# Paper-only Polymarket vs Kalshi 15m sleeve (BTC/ETH).
#
# Poly picks the side (≥60¢ Up=YES / Down=NO). The engine *simulates*
# that side on Kalshi if Kalshi also has it ≥60¢. Never sends Kalshi
# orders. Never sends Polymarket orders. Different state files from the
# live desk (prefix kalshi_poly_paper) so this cannot corrupt the live
# book. Compare to live crypto fills at EOD before promoting; do not
# auto-switch PAPER_STRATEGY.
#
# Same supervisor shape as kalshi_paper_loop.sh (110-min sessions,
# watchdog, 90s sleep when every series is dark) but:
#   * STRATEGY is always poly_book
#   * metals are always btc,eth
#   * KALSHI_LIVE is forced to 0 even if .env.kalshi sets it to 1
#   * the python command never gets the live flag
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SESSION_MIN="${SESSION_MIN:-110}"
BANKROLL="${BANKROLL:-250}"
LOG="${LOG:-state/kalshi_poly_paper_loop.log}"
PIDFILE="${PIDFILE:-state/kalshi_poly_paper.pid}"
DECISIONS="state/kalshi_poly_paper_decisions.jsonl"
STALE_S="${STALE_S:-300}"
DARK_SLEEP_S="${DARK_SLEEP_S:-90}"

# Credentials for Kalshi *quotes* only. Force the live switch off after
# sourcing so a KALSHI_LIVE=1 file cannot arm this sleeve.
if [ -f .env.kalshi ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.kalshi
  set +a
fi
KALSHI_LIVE=0
STRATEGY=poly_book
METALS=btc,eth

mkdir -p state
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
log "poly paper supervisor start (pid $$): ${SESSION_MIN}min sessions, metals=${METALS} live=0"

open_count() {
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
    log "no open paper-book window; sleeping ${DARK_SLEEP_S}s"
    sleep "$DARK_SLEEP_S"
    continue
  else
    log "open windows=$n"
  fi

  log "starting ${SESSION_MIN}min poly_book paper session (no live)"
  timeout $(( SESSION_MIN * 60 + 300 )) \
    python3 -m quantfirm.kalshi.cli agent \
      --minutes "$SESSION_MIN" --no-demo --no-maker --log-decisions \
      --metals "$METALS" --strategy "$STRATEGY" --bankroll "$BANKROLL" \
      --state-prefix kalshi_poly_paper \
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
