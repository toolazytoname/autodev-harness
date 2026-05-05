#!/bin/bash
# =============================================================================
# State Library - Workflow state management
# =============================================================================

# State variables
CURRENT_PHASE=""
COMPLETED_PHASES=()
STATE_FILES=()
ITERATION_COUNT=0

# === Load state ===
load_state() {
    local state_file="$PROJECT_DIR/state/workflow-state.json"

    if [[ ! -f "$state_file" ]]; then
        return 1  # No state
    fi

    # Load state into variables
    CURRENT_PHASE=$(grep '"currentPhase"' "$state_file" | sed 's/.*: *"\([^"]*\)".*/\1/')
    ITERATION_COUNT=$(grep '"iterationCount"' "$state_file" | sed 's/.*: *\([0-9]*\).*/\1/')

    # Source the state file (ignore errors from malformed lines)
    source <(grep -E '^\s+[a-zA-Z_]+=' "$state_file" 2>/dev/null | sed 's/: */=/') || true

    return 0
}

# === Save state ===
save_state() {
    local next_phase="$1"
    local state_file="$PROJECT_DIR/state/workflow-state.json"

    ensure_dir "$PROJECT_DIR/state"

    # Build completed phases string
    local completed_str=$(IFS=','; echo "${COMPLETED_PHASES[*]}")
    [[ -z "$completed_str" ]] && completed_str="$next_phase"

    cat > "$state_file" <<EOF
{
  "projectDir": "$PROJECT_DIR",
  "currentPhase": "$next_phase",
  "completedPhases": "$completed_str",
  "mode": "$MODE",
  "maxIterations": $MAX_ITERATIONS,
  "passThreshold": $PASS_THRESHOLD,
  "iterationCount": $ITERATION_COUNT,
  "files": {
    "000-brief": "$PROJECT_DIR/000-brief.md",
    "001-research": "$PROJECT_DIR/001-research-report.md",
    "002-plan": "$PROJECT_DIR/002-plan.md",
    "003-tasks": "$PROJECT_DIR/003-task-queue.json"
  }
}
EOF

    log "💾 State saved: $next_phase"
}

# === Ensure project directory ===
ensure_project_dir() {
    if [[ ! -d "$PROJECT_DIR" ]]; then
        mkdir -p "$PROJECT_DIR"
        log "📁 Created project directory: $PROJECT_DIR"
    fi
}
