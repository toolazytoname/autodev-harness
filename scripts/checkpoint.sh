#!/bin/bash
# checkpoint.sh - Context Management
set -euo pipefail
HARNESS_DIR="./autodev-harness"
CHECKPOINT_DIR="${HARNESS_DIR}/state/checkpoints"
mkdir -p "$CHECKPOINT_DIR"
log() { echo "[CHECKPOINT] $*"; }
save_checkpoint() { local id="cp-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$CHECKPOINT_DIR/$id"; cp autodev-harness/SPEC.md "$CHECKPOINT_DIR/$id/" 2>/dev/null; cp autodev-harness/state/task-queue.json "$CHECKPOINT_DIR/$id/" 2>/dev/null; echo "$id" > "$CHECKPOINT_DIR/current"; log "Saved: $id"; }
case "${1:-}" in save) save_checkpoint ;; list) ls -1t "$CHECKPOINT_DIR" 2>/dev/null | head -5 ;; *) echo "Usage: checkpoint.sh {save|list}" ;; esac
