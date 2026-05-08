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

# === Load Default Config ===
source "$SCRIPT_DIR/config/harness.config.sh"

# Apply defaults (CLI args override config defaults)
MAX_ITERATIONS="${MAX_ITERATIONS:-$DEFAULT_MAX_ITERATIONS}"
PASS_THRESHOLD="${PASS_THRESHOLD:-$DEFAULT_PASS_THRESHOLD}"

# === Load Libraries ===
source "$LIB_DIR/ui.sh"
source "$LIB_DIR/files.sh"
source "$LIB_DIR/claude.sh"
source "$LIB_DIR/state.sh"
source "$SCRIPT_DIR/config/llm-config.sh"

# Load LLM config (priority: CLI > env > config file > defaults)
load_llm_config

# === Usage ===
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [PROJECT_DIR] [-- PROJECT_DESCRIPTION]

OPTIONS:
    --new           New project mode (default)
    --iterate       Iterate on existing project (bug fix / feature)
    --test          Test mode (quick validation, 2-3 iterations)
    -c, --continue  Continue from last checkpoint
    --status        Show project status
    --restart       Restart from beginning
    --max-iterations N  Set max iterations (default: 15)

LLM OPTIONS:
    --llm-key KEY        LLM API key
    --llm-url URL        LLM API URL
    --model MODEL        Model name

EXAMPLES:
    # Run with project description (creates 000-brief.md automatically)
    $(basename "$0") /path/to/project -- "我要开发一个宠物养成系统"

    # Run in project directory with existing 000-brief.md
    cd /path/to/project
    $(basename "$0")

    # Test mode
    $(basename "$0") --test /path/to/project -- "Quick validation task"

    # Continue from checkpoint
    $(basename "$0") -c /path/to/project
EOF
}

# === Parse Arguments ===
parse_args() {
    local args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --new) MODE="new"; shift ;;
            --iterate) MODE="iterate"; shift ;;
            --test) MODE="test"; shift ;;
            -c|--continue) ACTION="continue"; shift ;;
            --status) ACTION="status"; shift ;;
            --restart) ACTION="restart"; shift ;;
            --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
            --llm-key) LLM_API_KEY="$2"; shift 2 ;;
            --llm-url) LLM_URL="$2"; shift 2 ;;
            --model) LLM_MODEL="$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            --) shift; BRIEF_ARGS="$@"; break ;;
            -*) error "Unknown option: $1" ;;
            *) PROJECT_DIR="$1"; shift ;;
        esac
    done

    # Apply CLI overrides
    apply_cli_config "$@"

    # Default to current directory
    [[ -n "$PROJECT_DIR" ]] || PROJECT_DIR="$PWD"
}

# === Create Brief from CLI ===
create_brief_from_args() {
    local brief="$PROJECT_DIR/000-brief.md"
    # Check if brief already exists
    [[ -f "$brief" ]] && return 0

    # If brief args exist, use them as brief content
    [[ -z "$BRIEF_ARGS" ]] && return 0

    log "Creating 000-brief.md from input..."
    cat > "$brief" <<EOF
# 项目需求

$BRIEF_ARGS

EOF
    log "Brief created: $brief"
}

# === Mode Configuration ===
configure_mode() {
    CURRENT_PHASE="init"
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
    log "  Model: $LLM_MODEL"
}

# === Phase: Research ===
phase_research() {
    log_phase "research"
    local brief="$PROJECT_DIR/000-brief.md"
    local output="$PROJECT_DIR/001-research-report.md"

    log_step "Reading brief from: $brief"
    ensure_file "$brief"

    log_step "Calling research agent..."
    call_claude "researcher" "$brief" "$output"

    log_step "Research report saved: $output"
    save_state "plan"
    log_done "Research complete"
}

# === Phase: Plan ===
phase_plan() {
    log_phase "plan"

    # Collect infrastructure config first (Supabase URL, keys)
    log_step "Collecting infrastructure configuration..."
    collect_infra_config "$PROJECT_DIR"
    load_infra_config "$PROJECT_DIR"

    local research="$PROJECT_DIR/001-research-report.md"
    local output="$PROJECT_DIR/002-plan.md"

    log_step "Reading research report: $research"
    ensure_file "$research"

    log_step "Calling planner agent..."
    call_claude "planner" "$research" "$output"

    log_step "Plan saved: $output"

    log_step "Waiting for user confirmation..."
    confirm_plan "$output"

    save_state "ui_design"
    log_done "Plan confirmed"
}

# === Phase: UI Design ===
phase_ui_design() {
    log_phase "ui_design"

    local plan="$PROJECT_DIR/002-plan.md"
    local spec_output="$PROJECT_DIR/006-ui-spec.md"
    local html_output="$PROJECT_DIR/preview/index.html"
    local context_file="$PROJECT_DIR/.claude/ui-design-context.md"
    local temp_output=$(mktemp)

    log_step "Reading plan: $plan"
    ensure_file "$plan"

    # Create preview directory
    mkdir -p "$PROJECT_DIR/preview"

    # Create context file with project info
    cat > "$context_file" <<EOF
# UI Design Context

Project: $PROJECT_DIR
Plan: $plan

---PLAN---
$(cat "$plan")
EOF

    log_step "Calling UI design agent..."
    call_claude "ui-design" "$context_file" > "$temp_output"

    # Split output by delimiter
    if grep -q "---HTML---" "$temp_output"; then
        # Extract spec (before ---HTML---)
        sed '/---HTML---/q' "$temp_output" | sed '/---HTML---$/d' > "$spec_output"
        # Extract HTML (after ---HTML---)
        sed '1,/---HTML---/d' "$temp_output" > "$html_output"
    else
        # No HTML found, treat entire output as spec
        cp "$temp_output" "$spec_output"
        # Create minimal HTML placeholder
        cat > "$html_output" <<'HTML'
<!DOCTYPE html>
<html>
<head>
  <title>UI Mockup Placeholder</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="p-8">
  <div class="text-red-500">HTML not generated. Please check spec.</div>
</body>
</html>
HTML
    fi

    rm -f "$temp_output"

    log_step "UI spec saved: $spec_output"
    log_step "Preview saved: $html_output"
    log_step "Open in browser: file://$html_output"

    # Check if HTML is valid (non-empty and looks like HTML)
    if [[ ! -s "$html_output" ]] || ! grep -q "<!DOCTYPE html>" "$html_output"; then
        log_error "Invalid HTML file generated"
        return 1
    fi

    log_step "Waiting for UI design confirmation..."
    confirm "Do you approve the UI design?"

    save_state "tasks"
    log_done "UI design confirmed"
}

# === Phase: Tasks ===
phase_tasks() {
    log_phase "tasks"
    local plan="$PROJECT_DIR/002-plan.md"
    local output="$PROJECT_DIR/003-task-queue.json"

    log_step "Reading plan: $plan"
    ensure_file "$plan"

    log_step "Calling taskgen agent..."
    call_claude "taskgen" "$plan" "$output"

    log_step "Tasks saved: $output"
    save_state "develop"
    log_done "Tasks generated"
}

# === Phase: Develop ===
phase_develop() {
    log_phase "develop"
    load_state

    local iteration=0
    local score=0

    log "Starting development loop (max $MAX_ITERATIONS iterations)"

    while true; do
        ((iteration++))

        # Check max iterations
        if [[ $iteration -gt $MAX_ITERATIONS ]]; then
            warn "Max iterations ($MAX_ITERATIONS) reached"
            break
        fi

        log ""
        log "━━━ Iteration $iteration/$MAX_ITERATIONS ━━━"

        # Get next pending task
        local task=$(get_next_task)
        if [[ -z "$task" ]]; then
            log_done "All tasks completed!"
            break
        fi

        log_step "Task: $task"

        # Run generator for this task
        log_step "Running generator..."
        run_generator "$task" "$iteration"

        # Run evaluator
        log_step "Running evaluator..."
        score=$(run_evaluator "$iteration")

        # Check if passed
        if is_score_passed "$score"; then
            log "  Score: $score (passed threshold: $PASS_THRESHOLD)"
            complete_task "$task"
            save_iteration "$iteration" "$score"
        else
            log "  Score: $score (below threshold: $PASS_THRESHOLD)"
            save_feedback "$iteration" "$score"
        fi
    done

    log_done "Development complete"
}

# === Resume Workflow ===
resume_workflow() {
    log_phase "resume"
    load_state

    log "Resuming from phase: $CURRENT_PHASE"
    case "$CURRENT_PHASE" in
        plan)
            phase_plan
            phase_ui_design
            phase_tasks
            phase_develop
            ;;
        ui_design)
            phase_ui_design
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
    log_done "Restarted. Run without --restart to begin fresh."
}

# === Main ===
main() {
    parse_args "$@"
    configure_mode

    # Initialize logging for this project
    init_logging "$PROJECT_DIR"
    log ""
    log "═══════════════════════════════════════════════════════"
    log " AutoDevHarness v1.0"
    log " Mode: $MODE, Project: $PROJECT_DIR"
    log "═══════════════════════════════════════════════════════"
    log ""

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

    # Create brief from remaining args if provided
    create_brief_from_args "$@"

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
    phase_ui_design
    phase_tasks
    phase_develop

    log ""
    log "═══════════════════════════════════════════════════════"
    log " Workflow complete!"
    log " Log saved: $LOG_FILE"
    log "═══════════════════════════════════════════════════════"
}

# === Entry Point ===
main "$@"
