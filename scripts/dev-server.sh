#!/bin/bash
# dev-server.sh - Dev Server Management
PORT="${1:-3000}"
CMD="${2:-npm run dev}"
log() { echo "[DEV] $*"; }
start() { log "Starting on port $PORT: $CMD"; $CMD &>/tmp/dev-$PORT.log & echo $! > /tmp/dev-$PORT.pid; log "PID: $(cat /tmp/dev-$PORT.pid)"; }
stop() { [ -f /tmp/dev-$PORT.pid ] && kill $(cat /tmp/dev-$PORT.pid) 2>/dev/null && log "Stopped" || log "Not running"; }
status() { [ -f /tmp/dev-$PORT.pid ] && ps -p $(cat /tmp/dev-$PORT.pid) &>/dev/null && log "Running (PID $(cat /tmp/dev-$PORT.pid))" || log "Not running"; }
case "${1:-}" in start) start ;; stop) stop ;; status) status ;; *) echo "Usage: $0 {start|stop|status} [port]" ;; esac
