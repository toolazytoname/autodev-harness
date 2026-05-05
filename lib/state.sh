#!/bin/bash
# =============================================================================
# State Library - Enhanced workflow state management
# =============================================================================

# State variables
CURRENT_PHASE=""
COMPLETED_PHASES=()
STATE_FILES=()
ITERATION_COUNT=0
LAST_ERROR=""
SESSION_START=""

# === Init session ===
init_session() {
    SESSION_START=$(date +%s)
    log_step "Session started at: $(date '+%Y-%m-%d %H:%M:%S')"
}

# === Load state ===
load_state() {
    local state_file="$PROJECT_DIR/state/workflow-state.json"

    if [[ ! -f "$state_file" ]]; then
        return 1
    fi

    log_step "Loading state from: $state_file"

    CURRENT_PHASE=$(grep '"currentPhase"' "$state_file" | sed 's/.*: *"\([^"]*\)".*/\1/')
    ITERATION_COUNT=$(grep '"iterationCount"' "$state_file" | sed 's/.*: *\([0-9]*\).*/\1/')
    LAST_ERROR=$(grep '"lastError"' "$state_file" | sed 's/.*: *"\([^"]*\)".*/\1/' 2>/dev/null || echo "")

    source <(grep -E '^\s+[a-zA-Z_]+=' "$state_file" 2>/dev/null | sed 's/: */=/') || true

    log_step "State loaded: phase=$CURRENT_PHASE, iterations=$ITERATION_COUNT"
    return 0
}

# === Save state ===
save_state() {
    local next_phase="$1"
    local state_file="$PROJECT_DIR/state/workflow-state.json"

    ensure_dir "$PROJECT_DIR/state"

    local completed_str=$(IFS=','; echo "${COMPLETED_PHASES[*]}")
    [[ -z "$completed_str" ]] && completed_str="$next_phase"

    # Get previous state for comparison
    local prev_phase="$CURRENT_PHASE"

    # Build files section without leading digits in keys (bash source compatibility)
    local brief_path="${STATE_FILES[brief]:-$PROJECT_DIR/000-brief.md}"
    local research_path="${STATE_FILES[research]:-$PROJECT_DIR/001-research-report.md}"
    local plan_path="${STATE_FILES[plan]:-$PROJECT_DIR/002-plan.md}"
    local tasks_path="${STATE_FILES[tasks]:-$PROJECT_DIR/003-task-queue.json}"
    local spec_path="${STATE_FILES[spec]:-$PROJECT_DIR/004-spec.md}"
    local rubric_path="${STATE_FILES[rubric]:-$PROJECT_DIR/005-eval-rubric.md}"

    cat > "$state_file" <<EOF
{
  "projectDir": "$PROJECT_DIR",
  "currentPhase": "$next_phase",
  "previousPhase": "$prev_phase",
  "completedPhases": "$completed_str",
  "mode": "$MODE",
  "maxIterations": $MAX_ITERATIONS,
  "passThreshold": $PASS_THRESHOLD,
  "iterationCount": $ITERATION_COUNT,
  "lastError": "${LAST_ERROR:-}",
  "updatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "files": {
    "brief": "$brief_path",
    "research": "$research_path",
    "plan": "$plan_path",
    "tasks": "$tasks_path",
    "spec": "$spec_path",
    "rubric": "$rubric_path"
  }
}
EOF

    CURRENT_PHASE="$next_phase"
    log_step "State saved: phase=$next_phase"
}

# === Update phase info ===
update_phase_files() {
    local phase="$1"
    local file_path="$2"

    case "$phase" in
        research) STATE_FILES[research]="$file_path" ;;
        plan) STATE_FILES[plan]="$file_path" ;;
        tasks) STATE_FILES[tasks]="$file_path" ;;
        spec) STATE_FILES[spec]="$file_path" ;;
        rubric) STATE_FILES[rubric]="$file_path" ;;
    esac

    log_step "Phase file registered: $phase -> $file_path"
}

# === Record error ===
record_error() {
    LAST_ERROR="$1"
    log_step "Error recorded: ${LAST_ERROR:0:100}"
}

# === Ensure project directory ===
ensure_project_dir() {
    if [[ ! -d "$PROJECT_DIR" ]]; then
        mkdir -p "$PROJECT_DIR"
        log_step "Project directory created: $PROJECT_DIR"
    fi
}

# === Get state summary ===
get_state_summary() {
    cat <<EOF
State Summary:
  Current Phase: ${CURRENT_PHASE:-none}
  Completed: ${COMPLETED_PHASES[*]:-none}
  Iterations: ${ITERATION_COUNT:-0}
  Last Error: ${LAST_ERROR:-none}
  Session Start: ${SESSION_START:-none}
EOF
}
