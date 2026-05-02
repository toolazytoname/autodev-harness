#!/bin/bash
# metrics-collector.sh - Metrics Collection
set -euo pipefail
HARNESS_DIR="./autodev-harness"
METRICS_DIR="${HARNESS_DIR}/state/metrics"
mkdir -p "$METRICS_DIR"
log() { echo "[METRICS] $*"; }

collect_task_metrics() {
  local ts=$(date +%Y%m%d-%H%M%S)
  local qfile="${HARNESS_DIR}/state/task-queue.json"
  [ ! -f "$qfile" ] && return 1
  local completed=$(jq '.progress.completed' "$qfile" 2>/dev/null || echo 0)
  local in_progress=$(jq '.progress.inProgress' "$qfile" 2>/dev/null || echo 0)
  local pending=$(jq '.progress.pending' "$qfile" 2>/dev/null || echo 0)
  local failed=$(jq '.progress.failed' "$qfile" 2>/dev/null || echo 0)
  local total=$(jq '.tasks | length' "$qfile" 2>/dev/null || echo 0)
  local pct=0
  [ "$total" -gt 0 ] && pct=$((completed * 100 / total))
  cat >> "${METRICS_DIR}/task-metrics.jsonl" << EOF
{"ts":"$ts","completed":$completed,"inProgress":$in_progress,"pending":$pending,"failed":$failed,"total":$total,"pct":$pct}
EOF
  log "Task: $completed/$total ($pct%)"
}

collect_gan_metrics() {
  local ts=$(date +%Y%m%d-%H%M%S)
  local sfile="${HARNESS_DIR}/feedback/gan/summary.json"
  [ ! -f "$sfile" ] && return 1
  local score=$(jq -r '.finalScore' "$sfile" 2>/dev/null || echo 0)
  local passed=$(jq -r '.passed' "$sfile" 2>/dev/null || echo false)
  local iterations=$(jq -r '.iterations' "$sfile" 2>/dev/null || echo 0)
  cat >> "${METRICS_DIR}/gan-metrics.jsonl" << EOF
{"ts":"$ts","score":$score,"passed":$passed,"iterations":$iterations}
EOF
  log "GAN: score=$score passed=$passed"
}

collect_gate_metrics() {
  local ts=$(date +%Y%m%d-%H%M%S)
  local gates=(lint build test e2e security)
  local results="{}"
  for gate in "${gates[@]}"; do
    local latest=$(ls -t "${HARNESS_DIR}/quality/gates/$gate/"*.log 2>/dev/null | head -1)
    if [ -n "$latest" ]; then
      local status=$(tail -1 "$latest" | grep -q "PASS\|passed" && echo "pass" || echo "fail")
      results=$(echo "$results" | jq --arg g "$gate" --arg s "$status" '.[$g]=$s')
    fi
  done
  cat >> "${METRICS_DIR}/gate-metrics.jsonl" << EOF
{"ts":"$ts","gates":$results}
EOF
  log "Gates: $(echo "$results" | jq -r '.')"
}

case "${1:-all}" in
  task) collect_task_metrics ;;
  gan) collect_gan_metrics ;;
  gate) collect_gate_metrics ;;
  all)
    collect_task_metrics
    collect_gan_metrics
    collect_gate_metrics
    log "All metrics collected"
    ;;
  *) echo "Usage: $0 {task|gan|gate|all}" ;;
esac
