#!/bin/bash
# =============================================================================
# AutoDevHarness - AI-Powered Development Framework
# =============================================================================
# Supports three modes:
#   - new: New project development
#   - iterate: Bug fixes / feature additions on existing projects
#   - test: Quick validation (2-3 iterations, minimal viable)
# =============================================================================

set -e

# === Configuration ===
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly LIB_DIR="$SCRIPT_DIR/lib"

# Default config
MODE="new"
ACTION=""
PROJECT_DIR=""
MAX_ITERATIONS=15
PASS_THRESHOLD=7.0
SKIP_E2E=false
SKIP_SECURITY=false

# === Load Libraries ===
source "$LIB_DIR/ui.sh"
source "$LIB_DIR/files.sh"
source "$LIB_DIR/claude.sh"
source "$LIB_DIR/state.sh"
source "$SCRIPT_DIR/config/providers.sh"
source "$SCRIPT_DIR/config/llm-config.sh"

# Load LLM config (priority: CLI > env > config file > defaults)
load_llm_config

# === Usage ===
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [PROJECT_DIR]

OPTIONS:
    --new           New project mode (default)
    --iterate       Iterate on existing project (bug fix / feature)
    --test          Test mode (quick validation, 2-3 iterations)
    -c, --continue  Continue from last checkpoint
    --status        Show project status
    --restart       Restart from beginning
    --max-iterations N  Set max iterations (default: 15)

LLM OPTIONS:
    --provider PROVIDER   LLM provider (anthropic, openai, ollama, groq, deepseek)
    --llm-url URL        LLM API URL
    --llm-key KEY        LLM API Key
    --model MODEL        Model name

EXAMPLES:
    $(basename "$0") /path/to/new-project
    $(basename "$0") --iterate /path/to/existing-project
    $(basename "$0") --test /path/to/test-project
    $(basename "$0") -c /path/to/project  # Resume
    $(basename "$0") --provider openai --llm-key sk-xxx /path/to/project
EOF
}

# === Parse Arguments ===
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --new) MODE="new"; shift ;;
            --iterate) MODE="iterate"; shift ;;
            --test) MODE="test"; shift ;;
            -c|--continue) ACTION="continue"; shift ;;
            --status) ACTION="status"; shift ;;
            --restart) ACTION="restart"; shift ;;
            --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
            --provider) LLM_PROVIDER="$2"; shift 2 ;;
            --llm-url) LLM_URL="$2"; shift 2 ;;
            --llm-key) LLM_API_KEY="$2"; shift 2 ;;
            --model) LLM_MODEL="$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            -*) error "Unknown option: $1" ;;
            *) PROJECT_DIR="$1"; shift ;;
        esac
    done

    # Apply CLI overrides
    apply_cli_config "$@"

    # Default to current directory
    [[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="$PWD"
}

# === Mode Configuration ===
configure_mode() {
    case "$MODE" in
        test)
            MAX_ITERATIONS=3
            PASS_THRESHOLD=5.0
            SKIP_E2E=true
            SKIP_SECURITY=true
            log "🧪 TEST MODE: Quick validation (max $MAX_ITERATIONS iterations)"
            ;;
        iterate)
            log "🔄 ITERATE MODE: Bug fix / feature addition"
            ;;
        new)
            log "🆕 NEW MODE: Building from scratch"
            ;;
    esac
}

# === Phase: Research ===
phase_research() {
    local brief="$PROJECT_DIR/000-brief.md"
    local output="$PROJECT_DIR/001-research-report.md"

    log "🔍 Phase 1: Research"
    ensure_file "$brief"

    # Run research agent
    call_claude "researcher" < "$brief" > "$output"

    save_state "plan"
    log "✅ Research complete → $output"
}

# === Phase: Plan ===
phase_plan() {
    local research="$PROJECT_DIR/001-research-report.md"
    local output="$PROJECT_DIR/002-plan.md"

    log "📋 Phase 2: Plan"
    ensure_file "$research"

    # Generate plan using ECC plan skill
    call_claude "planner" < "$research" > "$output"

    # User confirmation
    confirm_plan "$output"

    save_state "tasks"
    log "✅ Plan confirmed → $output"
}

# === Phase: Tasks ===
phase_tasks() {
    local plan="$PROJECT_DIR/002-plan.md"
    local output="$PROJECT_DIR/003-task-queue.json"

    log "📝 Phase 3: Generate Tasks"
    ensure_file "$plan"

    call_claude "taskgen" < "$plan" > "$output"

    save_state "develop"
    log "✅ Tasks generated → $output"
}

# === Phase: Develop ===
phase_develop() {
    log "🚀 Phase 4: Development Loop"

    load_state
    local iteration=0
    local score=0

    while true; do
        ((iteration++))

        # Check max iterations
        if [[ $iteration -gt $MAX_ITERATIONS ]]; then
            warn "Max iterations ($MAX_ITERATIONS) reached"
            break
        fi

        log "━━━ Iteration $iteration/$MAX_ITERATIONS ━━━"

        # Get next pending task
        local task=$(get_next_task)
        if [[ -z "$task" ]]; then
            log "✅ All tasks completed!"
            break
        fi

        log "📦 Task: $task"

        # Run generator for this task
        run_generator "$task" "$iteration"

        # Run evaluator
        score=$(run_evaluator "$iteration")

        # Check if passed
        if is_score_passed "$score"; then
            log "✅ Score: $score (passed)"
            complete_task "$task"
            save_iteration "$iteration" "$score"
        else
            log "⚠️ Score: $score (need improvement)"
            save_feedback "$iteration" "$score"
        fi
    done

    log "🎉 Development complete!"
}

# === Resume Workflow ===
resume_workflow() {
    load_state

    case "$CURRENT_PHASE" in
        plan)
            phase_plan
            phase_tasks
            phase_develop
            ;;
        tasks)
            phase_tasks
            phase_develop
            ;;
        develop)
            phase_develop
            ;;
        *)
            error "Unknown phase: $CURRENT_PHASE"
            ;;
    esac
}

# === Show Status ===
show_status() {
    if ! load_state; then
        log "No workflow state found"
        exit 1
    fi

    cat <<EOF
📊 Project Status: $PROJECT_DIR

Current Phase: $CURRENT_PHASE
Mode: $MODE
Completed Phases: ${COMPLETED_PHASES[*]}
Iterations: $ITERATION_COUNT

Files:
EOF

    for key in "${!STATE_FILES[@]}"; do
        echo "  - $key: ${STATE_FILES[$key]}"
    done
}

# === Restart Project ===
restart_project() {
    log "⚠️ Restarting project..."
    rm -f "$PROJECT_DIR/state/workflow-state.json"
    log "✅ Restarted. Run without --restart to begin fresh."
}

# === Main ===
main() {
    parse_args "$@"
    configure_mode

    # Handle non-execution commands
    case "${ACTION:-}" in
        status)
            show_status
            exit 0
            ;;
        restart)
            restart_project
            exit 0
            ;;
    esac

    # Check/create project directory
    ensure_project_dir

    # Check for existing state
    if load_state; then
        log "📂 Found existing workflow state"
        if confirm "Continue from checkpoint?"; then
            resume_workflow
            exit 0
        fi
    fi

    # Start fresh
    log "🆕 Starting new workflow in: $PROJECT_DIR"

    # Run phases
    phase_research
    phase_plan
    phase_tasks
    phase_develop
}

# === Entry Point ===
main "$@"
