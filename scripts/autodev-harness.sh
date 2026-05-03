#!/bin/bash
# autodev-harness.sh — AutoDevHarness Main Entry Point
#
# Usage:
#   ./autodev-harness.sh "Build a project management app with Kanban boards"
#   ./autodev-harness.sh "Build a REST API" --type api --no-gan

set -euo pipefail

# HARNESS_DIR is relative to the script's directory, not current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="${HARNESS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
export HARNESS_DIR

# PROJECT_DIR is the project directory (defaults to HARNESS_DIR if not set)
PROJECT_DIR="${PROJECT_DIR:-$HARNESS_DIR}"
export PROJECT_DIR

CONFIG_FILE="${HARNESS_DIR}/config/harness.config.json"
PROJECT_CONFIG="${PROJECT_DIR}/config/harness.config.json"
PROJECT_SPEC="${PROJECT_DIR}/SPEC.md"
PROJECT_STATE="${PROJECT_DIR}/state"
PROJECT_LOGS="${PROJECT_DIR}/logs"

BRIEF=""
PROJECT_TYPE="fullstack"
PLANNER_MODEL="minimax-latest"
GENERATOR_MODEL="minimax-latest"
MAX_ITERATIONS=15
PASS_THRESHOLD=7.0
DEV_PORT=3000
DEV_CMD="npm run dev"
SKIP_PLANNER=false
SKIP_GAN=false
CONTINUE=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log()    { echo -e "${BLUE}[HARNESS]${NC} $*"; }
ok()     { echo -e "${GREEN}[✓]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()   { echo -e "${RED}[✗]${NC} $*"; }
phase()  { echo -e "\n${PURPLE}═══════════════════════════════════════════════${NC}"; echo -e "${PURPLE}  $*${NC}"; echo -e "${PURPLE}═══════════════════════════════════════════════${NC}\n"; }

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --type) PROJECT_TYPE="$2"; shift 2 ;;
      --model) PLANNER_MODEL="$2"; GENERATOR_MODEL="$2"; shift 2 ;;
      --iterations) MAX_ITERATIONS="$2"; shift 2 ;;
      --threshold) PASS_THRESHOLD="$2"; shift 2 ;;
      --skip-planner) SKIP_PLANNER=true; shift ;;
      --skip-gan) SKIP_GAN=true; shift ;;
      --continue) CONTINUE=true; shift ;;
      --help)
        echo "Usage: $0 \"brief\" [options]"
        echo "  --type TYPE        Project type: fullstack, frontend, api, library"
        echo "  --model MODEL      AI model (default: minimax-latest)"
        echo "  --iterations N     Max GAN iterations (default: 15)"
        echo "  --threshold SCORE  Pass threshold 1-10 (default: 7.0)"
        echo "  --skip-planner     Skip planning phase"
        echo "  --skip-gan         Skip GAN feedback loop"
        echo "  --continue         Continue from previous session"
        exit 0 ;;
      -*) fail "Unknown option: $1"; exit 1 ;;
      *)
        [ -z "$BRIEF" ] && BRIEF="$1"
        shift ;;
    esac
  done
  [ -z "$BRIEF" ] && { fail "Usage: $0 \"brief\""; exit 1; } || true
}

setup() {
  log "Brief: ${CYAN}${BRIEF}${NC}"
  mkdir -p "${PROJECT_DIR}"/{state,logs,quality/gates,feedback/{gan,reviews},tasks/{pending,in-progress,completed}}
  mkdir -p "${HARNESS_DIR}"/{scripts,agents,config,logs}

  cat > "$PROJECT_CONFIG" << EOF
{
  "brief": "$BRIEF",
  "projectType": "$PROJECT_TYPE",
  "models": { "planner": "$PLANNER_MODEL", "generator": "$GENERATOR_MODEL" },
  "harness": { "maxIterations": $MAX_ITERATIONS, "passThreshold": $PASS_THRESHOLD },
  "devServer": { "port": $DEV_PORT, "command": "$DEV_CMD" },
  "startedAt": "$(date -Iseconds)"
}
EOF
  "${HARNESS_DIR}/scripts/task-queue-engine.sh" init "$BRIEF" "$PROJECT_DIR"
  ok "Setup complete"
}

run_planner() {
  if [ "$SKIP_PLANNER" = true ] && [ -f "${PROJECT_SPEC}" ]; then
    phase "PLANNING — SKIPPED"
    return 0
  fi
  phase "PHASE 1: Planning"
  log "Launching Planner..."

  effort=high claude -p --model "$PLANNER_MODEL" --dangerously-skip-permissions \
    "You are the Planner in AutoDevHarness. Brief: \"$BRIEF\" Project type: $PROJECT_TYPE

CRITICAL: You MUST write tasks to the JSON file using jq!

Create files:
1. Write to ${PROJECT_SPEC} - Full product spec with features, design, tech stack
2. Write to ${PROJECT_DIR}/config/eval-rubric.md - Evaluation rubric
3. CRITICAL: Add tasks to ${PROJECT_STATE}/task-queue.json using jq:
   bash: jq '.tasks = [...]' -M \${PROJECT_STATE}/task-queue.json > tmp.json && mv tmp.json \${PROJECT_STATE}/task-queue.json
   Each task: {\"id\":\"TASK-001\",\"name\":\"Task Name\",\"status\":\"pending\",\"priority\":\"P0\",\"deps\":[]}

Create 10-14 tasks. Write them to the JSON file!" 2>&1 | tee "${PROJECT_LOGS}/planner.log"

  [ -f "${PROJECT_SPEC}" ] && ok "Plan generated" || fail "Planner failed"

  # Verify tasks were created
  task_count=$(jq '(.tasks // []) | length' "${PROJECT_STATE}/task-queue.json" 2>/dev/null || echo 0)
  if [ "$task_count" -eq 0 ]; then
    warn "No tasks found in task-queue.json, creating default tasks"
    jq '.tasks = [
      {"id":"TASK-001","name":"Project Setup","status":"pending","priority":"P0","deps":[]},
      {"id":"TASK-002","name":"Core Features","status":"pending","priority":"P0","deps":["TASK-001"]},
      {"id":"TASK-003","name":"UI Implementation","status":"pending","priority":"P1","deps":["TASK-001"]},
      {"id":"TASK-004","name":"Testing & Polish","status":"pending","priority":"P1","deps":["TASK-002","TASK-003"]}
    ]' "${PROJECT_STATE}/task-queue.json" > tmp.json && mv tmp.json "${PROJECT_STATE}/task-queue.json"
  fi
}

run_tasks() {
  phase "PHASE 2: Task Execution"
  while true; do
    task_output=$("${HARNESS_DIR}/scripts/task-queue-engine.sh" run "$PROJECT_DIR" 2>/dev/null)
    task_id=$(echo "$task_output" | grep -oE '[A-Z][A-Z0-9]*[-_]?[A-Z0-9]*' | grep -E '^[A-Z]{2,}[-_]?[0-9]+$' | head -1)
    [ -z "$task_id" ] && break
    log "━━━ Task: $task_id ━━━"
    effort=high claude -p --model "$GENERATOR_MODEL" --dangerously-skip-permissions \
      "Implement task $task_id. Read ${PROJECT_SPEC} and ${PROJECT_STATE}/task-queue.json.
Run quality gates, commit changes." \
      2>&1 | tee "${PROJECT_LOGS}/task-${task_id}.log"
    "${HARNESS_DIR}/scripts/task-queue-engine.sh" complete "$task_id" "$PROJECT_DIR"
    if [ "$SKIP_GAN" = false ]; then
      "${HARNESS_DIR}/scripts/gan-loop.sh" || true
    fi
  done
  ok "All tasks completed"
}

finalize() {
  phase "PHASE 3: Finalization"
  "${HARNESS_DIR}/scripts/run-quality-gates.sh" all || warn "Some gates failed"
  cat > "${PROJECT_DIR}/build-report.md" << EOF
# Build Report
**Brief:** $BRIEF
**Completed:** $(date)
EOF
  ok "Build complete!"
}

START_TIME=$(date +%s)
parse_args "$@"
[ "$CONTINUE" = true ] || setup
[ "$SKIP_PLANNER" = false ] && run_planner
run_tasks
finalize
ok "Done!"
