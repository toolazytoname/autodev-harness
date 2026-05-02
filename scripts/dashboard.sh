#!/bin/bash
# dashboard.sh - CLI Dashboard
set -euo pipefail
HARNESS_DIR="./autodev-harness"
METRICS_DIR="${HARNESS_DIR}/state/metrics"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

draw_bar() {
  local pct=$1
  local width=30
  local filled=$((width * pct / 100))
  printf "["
  for ((i=0; i<width; i++)); do
    if [ $i -lt $filled ]; then printf "${GREEN}█${NC}"; else printf "░"; fi
  done
  printf "] %3d%%\n" $pct
}

show_header() {
  printf "\n${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}\n"
  printf "${CYAN}║${NC}            AutoDevHarness Dashboard          ${CYAN}              ║${NC}\n"
  printf "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}\n"
}

show_tasks() {
  local qfile="${HARNESS_DIR}/state/task-queue.json"
  if [ ! -f "$qfile" ]; then
    printf "${YELLOW}No task data available${NC}\n"
    return
  fi
  local completed=$(jq -r '.progress.completed' "$qfile" 2>/dev/null || echo 0)
  local in_progress=$(jq -r '.progress.inProgress' "$qfile" 2>/dev/null || echo 0)
  local pending=$(jq -r '.progress.pending' "$qfile" 2>/dev/null || echo 0)
  local failed=$(jq -r '.progress.failed' "$qfile" 2>/dev/null || echo 0)
  local total=$(jq -r '.tasks | length' "$qfile" 2>/dev/null || echo 0)
  local pct=0
  [ "$total" -gt 0 ] && pct=$((completed * 100 / total))
  echo -e "\n${CYAN}━━━ Tasks ━━━${NC}"
  [ "$total" -eq 0 ] && echo "  No tasks" && return
  draw_bar $pct
  echo -e "  ${GREEN}✓ Completed${NC}:   $completed"
  echo -e "  ${YELLOW}⟳ In Progress${NC}: $in_progress"
  echo -e "  ${CYAN}○ Pending${NC}:      $pending"
  [ "$failed" -gt 0 ] && echo -e "  ${RED}✗ Failed${NC}:       $failed"
  echo ""
  echo "  Recent Tasks:"
  jq -r '.tasks | sort_by(.priority) | .[0:5] | .[] | "    [\(.status)] \(.id): \(.name)"' "$qfile" 2>/dev/null
}

show_gan() {
  local sfile="${HARNESS_DIR}/feedback/gan/summary.json"
  echo -e "\n${CYAN}━━━ GAN Loop ━━━${NC}"
  if [ ! -f "$sfile" ]; then
    echo "  No GAN data available"
    return
  fi
  local score=$(jq -r '.finalScore' "$sfile" 2>/dev/null || echo 0)
  local passed=$(jq -r '.passed' "$sfile" 2>/dev/null || echo false)
  local iterations=$(jq -r '.iterations' "$sfile" 2>/dev/null || echo 0)
  local threshold=$(jq -r '.passThreshold // 7.0' "${HARNESS_DIR}/config/harness.config.json" 2>/dev/null || echo 7.0)
  echo -e "  Score:       ${score}/10.0 (threshold: $threshold)"
  [ "$passed" = "true" ] && echo -e "  Status:      ${GREEN}PASS${NC}" || echo -e "  Status:      ${YELLOW}IN PROGRESS${NC}"
  echo -e "  Iterations:  $iterations"
  local scores=$(jq -r '.scores[]' "$sfile" 2>/dev/null | tr '\n' ' ' || echo "")
  [ -n "$scores" ] && echo -e "  Score trend: $scores"
}

show_gates() {
  echo -e "\n${CYAN}━━━ Quality Gates ━━━${NC}"
  local gates=(lint build test e2e security)
  for gate in "${gates[@]}"; do
    local latest=$(ls -t "${HARNESS_DIR}/quality/gates/$gate/"*.log 2>/dev/null | head -1)
    if [ -n "$latest" ]; then
      if tail -1 "$latest" 2>/dev/null | grep -qE "PASS|passed|✓"; then
        echo -e "  ${GREEN}✓${NC} $gate"
      else
        echo -e "  ${RED}✗${NC} $gate"
      fi
    else
      echo -e "  ○ $gate (no data)"
    fi
  done
}

show_time() {
  local pfile="${HARNESS_DIR}/config/harness.config.json"
  if [ -f "$pfile" ]; then
    local started=$(jq -r '.startedAt' "$pfile" 2>/dev/null || echo "")
    [ -n "$started" ] && echo -e "\n${CYAN}━━━ Time ━━━${NC}\n  Started: $started"
  fi
}

show_checkpoints() {
  local cpdir="${HARNESS_DIR}/state/checkpoints"
  echo -e "\n${CYAN}━━━ Checkpoints ━━━${NC}"
  if [ -d "$cpdir" ] && [ -n "$(ls -A "$cpdir" 2>/dev/null)" ]; then
    ls -1t "$cpdir" 2>/dev/null | head -3 | while read cp; do
      echo "  • $cp"
    done
  else
    echo "  No checkpoints"
  fi
}

# Main
show_header
show_tasks
show_gan
show_gates
show_time
show_checkpoints
echo ""
