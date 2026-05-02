#!/bin/bash
# watch.sh - Real-time Dashboard Watch Mode
set -euo pipefail
INTERVAL="${1:-10}"
log() { echo "[WATCH] $*"; }
log "Starting watch mode (interval: ${INTERVAL}s, Ctrl+C to stop)"
while true; do
  clear
  ./autodev-harness/scripts/dashboard.sh
  ./autodev-harness/scripts/metrics-collector.sh all 2>/dev/null
  echo ""
  echo "Next update in ${INTERVAL}s... (Ctrl+C to stop)"
  sleep "$INTERVAL"
done
