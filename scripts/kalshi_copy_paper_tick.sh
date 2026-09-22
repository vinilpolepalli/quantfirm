#!/usr/bin/env bash
# One paper tick of the Polymarket-leader → Kalshi copy book.
# Never sends a Kalshi order. Never sends a Polymarket order.
# KALSHI_LIVE is forced off even if a local env file sets it.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

if [ -f .env.kalshi ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.kalshi
  set +a
fi
KALSHI_LIVE=0
export KALSHI_LIVE

exec python3 -m quantfirm.kalshi.copybacktest paper-tick
