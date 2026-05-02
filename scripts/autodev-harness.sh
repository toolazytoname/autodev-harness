#!/bin/bash
# autodev-harness.sh — AutoDevHarness Main Entry Point
#
# Usage:
#   ./autodev-harness.sh "Build a project management app with Kanban boards"
#   ./autodev-harness.sh "Build a REST API" --type api --no-gan

set -euo pipefail

HARNESS_DIR="./autodev-harness"
CONFIG_FILE="${HARNESS_DIR}/config/harness.config.json"
TASK_QUEUE_FILE="${HARNESS_DIR}/state/task-queue.json"

BRIEF=""
PROJECT_TYPE="fullstack"
PLANNER_MODEL="opus"
GENERATOR_MODEL="opus"
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
      --model) GENERATOR_MODEL="$2"; shift 2 ;;
      --iterations) MAX_ITERATIONS="$2"; shift 2 ;;
      --threshold) PASS_THRESHOLD="$2"; shift 2 ;;
      --skip-planner) SKIP_PLANNER=true; shift ;;
      --skip-gan) SKIP_GAN=true; shift ;;
      --continue) CONTINUE=true; shift ;;
      --help)
        echo "Usage: $0 \"brief\" [options]"
        echo "  --type TYPE        Project type: fullstack, frontend, api, library"
        echo "  --model MODEL      AI model: opus, sonnet (default: opus)"
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
  [ -z "$BRIEF" ] && { fail "Usage: $0 \"brief\""; exit 1; }
}

setup() {
  log "Brief: ${CYAN}${BRIEF}${NC}"
  mkdir -p "${HARNESS_DIR}"/{scripts,agents,state,config,quality/gates,feedback/{gan,reviews},tasks/{pending,in-progress,completed},logs}

  cat > "$CONFIG_FILE" << EOF
{
  "brief": "$BRIEF",
  "projectType": "$PROJECT_TYPE",
  "models": { "planner": "$PLANNER_MODEL", "generator": "$GENERATOR_MODEL" },
  "harness": { "maxIterations": $MAX_ITERATIONS, "passThreshold": $PASS_THRESHOLD },
  "devServer": { "port": $DEV_PORT, "command": "$DEV_CMD" },
  "startedAt": "$(date -Iseconds)"
}
EOF
  "${HARNESS_DIR}/scripts/task-queue-engine.sh" init "$BRIEF"
  ok "Setup complete"
}

run_planner() {
  if [ "$SKIP_PLANNER" = true ] && [ -f "${HARNESS_DIR}/SPEC.md" ]; then
    phase "PLANNING — SKIPPED"
    return 0
  fi
  phase "PHASE 1: Planning"
  log "Launching Planner..."
  claude -p --model "$PLANNER_MODEL" --dangerously-skip-permissions \
    "You are the Planner in AutoDevHarness. Brief: \"$BRIEF\" Project type: $PROJECT_TYPE

Create files:
1. ${HARNESS_DIR}/SPEC.md - Full product spec with features, design, tech stack
2. ${HARNESS_DIR}/config/eval-rubric.md - Evaluation rubric
3. Update ${HARNESS_DIR}/state/task-queue.json with task decomposition

Be ambitious: 12-16 features." \
    2>&1 | tee "${HARNESS_DIR}/logs/planner.log"
  [ -f "${HARNESS_DIR}/SPEC.md" ] && ok "Plan generated" || fail "Planner failed"
}

run_tasks() {
  phase "PHASE 2: Task Execution"
  while true; do
    task_id=$("${HARNESS_DIR}/scripts/task-queue-engine.sh" run 2>/dev/null)
    [ -z "$task_id" ] && break
    log "━━━ Task: $task_id ━━━"
    claude -p --model "$GENERATOR_MODEL" --dangerously-skip-permissions \
      --allowedTools "Read,Write,Edit,Bash,Grep,Glob" \
      "Implement task $task_id. Read ${HARNESS_DIR}/SPEC.md and ${HARNESS_DIR}/state/task-queue.json.
Run quality gates, commit changes." \
      2>&1 | tee "${HARNESS_DIR}/logs/task-${task_id}.log"
    "${HARNESS_DIR}/scripts/task-queue-engine.sh" complete "$task_id"
    if [ "$SKIP_GAN" = false ]; then
      "${HARNESS_DIR}/scripts/gan-loop.sh" || true
    fi
  done
  ok "All tasks completed"
}

finalize() {
  phase "PHASE 3: Finalization"
  "${HARNESS_DIR}/scripts/run-quality-gates.sh" all || warn "Some gates failed"
  cat > "${HARNESS_DIR}/build-report.md" << EOF
# AutoDevHarness Build Report
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
