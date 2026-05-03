#!/bin/bash
# task-queue-engine.sh — Task Queue Engine with DAG Support
#
# Usage:
#   ./scripts/task-queue-engine.sh run [--task TASK_ID]
#   ./scripts/task-queue-engine.sh status
#   ./scripts/task-queue-engine.sh add '{"name":"New Task","deps":[]}'
#
# Environment Variables:
#   TASK_QUEUE_FILE  — Path to task queue JSON (default: ./autodev-harness/state/task-queue.json)

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="${HARNESS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
export HARNESS_DIR
TASK_QUEUE_FILE="${TASK_QUEUE_FILE:-$HARNESS_DIR/state/task-queue.json}"
PROJECT_DIR="${PROJECT_DIR:-$HARNESS_DIR}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────

log()    { echo -e "${BLUE}[QUEUE]${NC} $*"; }
ok()     { echo -e "${GREEN}[OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()   { echo -e "${RED}[FAIL]${NC} $*"; }
phase()  { echo -e "\n${CYAN}══ $* ══${NC}\n"; }

# ─── Task Queue Operations ────────────────────────────────────────────────────

init_queue() {
  local brief="${1:-}"
  local project_dir="${2:-$PROJECT_DIR}"

  log "Initializing task queue..."

  cat > "$TASK_QUEUE_FILE" << EOF
{
  "version": "1.0",
  "createdAt": "$(date -Iseconds)",
  "projectDir": "$(realpath "$project_dir")",
  "brief": "$brief",
  "tasks": [],
  "dag": { "layers": [] },
  "progress": { "completed": 0, "inProgress": 0, "pending": 0, "failed": 0 }
}
EOF

  ok "Task queue initialized: $TASK_QUEUE_FILE"
}

add_task() {
  local task_json="$1"

  if [ ! -f "$TASK_QUEUE_FILE" ]; then
    init_queue
  fi

  local task_id=$(echo "$task_json" | jq -r '.id // empty')
  if [ -z "$task_id" ]; then
    task_id="task-$(date +%s%3N)"
  fi

  local task=$(jq -n \
    --argjson input "$task_json" \
    --arg id "$task_id" \
    '{
      id: ($id),
      name: ($input.name // "Untitled Task"),
      description: ($input.description // ""),
      status: ($input.status // "pending"),
      priority: ($input.priority // 100),
      deps: ($input.deps // []),
      gates: ($input.gates // ["lint", "build"]),
      agent: ($input.agent // "generator"),
      createdAt: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
      result: null
    } + $input')

  local new_queue=$(jq --argjson task "$task" '.tasks += [$task]' "$TASK_QUEUE_FILE")
  echo "$new_queue" > "$TASK_QUEUE_FILE"
  ok "Added task: $(echo "$task" | jq -r '.name') (id: $task_id)"
  echo "$task_id"
}

update_task() {
  local task_id="$1"
  local updates="$2"

  if [ ! -f "$TASK_QUEUE_FILE" ]; then
    fail "Task queue not initialized"
    return 1
  fi

  local new_queue=$(jq --arg id "$task_id" --argjson updates "$updates" \
    '(.tasks // .taskQueue) as $tasks |
    .tasks = ($tasks | [.[] | if (.id | tostring) == $id then . + $updates else . end])' "$TASK_QUEUE_FILE")
  echo "$new_queue" > "$TASK_QUEUE_FILE"
}

get_task() {
  local task_id="$1"
  jq -r --arg id "$task_id" '(.tasks // .taskQueue)[] | select((.id | tostring) == $id)' "$TASK_QUEUE_FILE"
}

get_next_ready_task() {
  jq -r '
    (.tasks // .taskQueue) |
    # First try in-progress tasks, then pending
    (map(select(.status == "in-progress")) + map(select((.status // "pending") == "pending"))) |
    # Sort by priority: P0 first, then P1, P2
    sort_by(if .priority == "P0" then 0 elif .priority == "P1" then 1 elif .priority == "P2" then 2 else 3 end) |
    .[0].id // empty
  ' "$TASK_QUEUE_FILE"
}

# ─── Progress Tracking ────────────────────────────────────────────────────────

update_progress() {
  local new_queue=$(jq '
    (.tasks // .taskQueue) as $tasks |
    .progress = {
      completed: ($tasks | map(select((.status // "pending") == "completed")) | length),
      inProgress: ($tasks | map(select((.status // "pending") == "in-progress")) | length),
      pending: ($tasks | map(select((.status // "pending") == "pending")) | length),
      failed: ($tasks | map(select((.status // "pending") == "failed")) | length)
    }
  ' "$TASK_QUEUE_FILE")
  echo "$new_queue" > "$TASK_QUEUE_FILE"
}

show_status() {
  if [ ! -f "$TASK_QUEUE_FILE" ]; then
    echo "Task queue not initialized"
    return
  fi

  local completed=$(jq -r '.progress.completed' "$TASK_QUEUE_FILE")
  local total=$(jq '(.tasks // .taskQueue) | length' "$TASK_QUEUE_FILE")

  echo ""
  echo "═══════════════════════════════════════"
  echo "  Task Queue Status"
  echo "═══════════════════════════════════════"
  echo ""
  echo -e "  Progress: ${GREEN}${completed}${NC} / ${total}"
  echo "  ✓ Completed:  $(jq -r '.progress.completed' "$TASK_QUEUE_FILE")"
  echo "  ⟳ In Progress: $(jq -r '.progress.inProgress' "$TASK_QUEUE_FILE")"
  echo "  ○ Pending:     $(jq -r '.progress.pending' "$TASK_QUEUE_FILE")"
  echo "  ✗ Failed:      $(jq -r '.progress.failed' "$TASK_QUEUE_FILE")"
  echo ""
  echo "  Tasks:"
  jq -r '(.tasks // .taskQueue) | sort_by(.priority) | .[] | "  [\(.status // "pending")] \(.id): \(.name)"' "$TASK_QUEUE_FILE"
  echo ""
}

# ─── Run Tasks ────────────────────────────────────────────────────────────────

run_next_task() {
  phase "Running Next Task"
  local task_id=$(get_next_ready_task)

  if [ -z "$task_id" ] || [ "$task_id" = "null" ]; then
    ok "No more tasks to run"
    return 0
  fi

  update_task "$task_id" '{"status": "in-progress", "startedAt": "'$(date -Iseconds)'"}'
  update_progress
  log "Starting task: $task_id"
  echo "$task_id"
}

complete_task() {
  local task_id="$1"
  local result="${2:-success}"

  update_task "$task_id" "{
    \"status\": \"$result\",
    \"completedAt\": \"$(date -Iseconds)\",
    \"result\": { \"status\": \"$result\" }
  }"
  update_progress
  ok "Task $task_id completed: $result"
}

fail_task() {
  local task_id="$1"
  local reason="${2:-Unknown error}"

  update_task "$task_id" "{
    \"status\": \"failed\",
    \"completedAt\": \"$(date -Iseconds)\",
    \"result\": { \"status\": \"failed\", \"reason\": \"$reason\" }
  }"
  update_progress
  fail "Task $task_id failed: $reason"
}

# ─── Main ────────────────────────────────────────────────────────────────────

COMMAND="${1:-status}"
shift || true

case "$COMMAND" in
  init)
    init_queue "$@"
    ;;
  add)
    [ $# -eq 0 ] && { fail "Usage: $0 add TASK_JSON"; exit 1; }
    add_task "$1"
    ;;
  status)
    show_status
    ;;
  run)
    if [ $# -gt 0 ] && [[ "$1" == --task ]]; then
      task_id="$2"
      update_task "$task_id" '{"status": "in-progress"}'
      echo "$task_id"
    else
      run_next_task
    fi
    ;;
  complete)
    [ $# -lt 1 ] && { fail "Usage: $0 complete TASK_ID [result]"; exit 1; }
    complete_task "$1" "${2:-success}"
    ;;
  fail)
    [ $# -lt 1 ] && { fail "Usage: $0 fail TASK_ID [reason]"; exit 1; }
    fail_task "$1" "${2:-Unknown error}"
    ;;
  update)
    [ $# -lt 2 ] && { fail "Usage: $0 update TASK_ID UPDATES_JSON"; exit 1; }
    update_task "$1" "$2"
    ;;
  *)
    echo "Usage: $0 {init|add|status|run|complete|fail|update}"
    exit 1
    ;;
esac
