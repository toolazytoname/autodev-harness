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
    -c, --continue  Continue from last checkpoint (自动推断阶段)
    --phase PHASE   Jump to specific phase (research|plan|ui_design|tasks|develop)
    --status        Show project status
    --restart       Restart project (删除状态文件，重新开始)
    --max-iterations N  Set max iterations (default: 15)

PHASES (执行顺序):
    research   → Research agent (竞争分析)
    plan       → Plan agent (中文计划，支持用户反馈迭代)
    ui_design  → UI design with Lazyweb references (HTML预览，支持迭代)
    tasks      → Task generation
    develop    → Generator → Evaluator loop

LLM OPTIONS:
    --llm-key KEY        LLM API key
    --llm-url URL        LLM API URL
    --model MODEL        Model name

EXAMPLES:
    # 新项目，从命令行描述开始
    $(basename "$0") /path/to/project -- "我要开发一个宠物养成系统"

    # 已有 000-brief.md，直接运行
    cd /path/to/project
    $(basename "$0")

    # 从断点继续（自动检测当前阶段）
    $(basename "$0") -c /path/to/project

    # 跳转到指定阶段（跳过已完成阶段）
    $(basename "$0") --phase plan /path/to/project
    $(basename "$0") --phase ui_design /path/to/project

    # 重启项目（删除状态文件）
    $(basename "$0") --restart /path/to/project

    # Test mode
    $(basename "$0") --test /path/to/project -- "Quick validation task"
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
            --phase) TARGET_PHASE="$2"; shift 2 ;;
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
    local feedback_file="$PROJECT_DIR/.claude/plan-feedback.md"
    local context_file="$PROJECT_DIR/.claude/plan-context.md"
    local iteration=1

    log_step "Reading research report: $research"
    ensure_file "$research"

    while true; do
        log_step "━━━ Plan Iteration $iteration ━━━"

        # Build context: research + previous plan + feedback (for iteration > 1)
        cat > "$context_file" <<EOF
# Planning Context

---INPUT---
EOF
        cat "$research" >> "$context_file"

        if [[ $iteration -gt 1 && -f "$output" ]]; then
            cat >> "$context_file" <<EOF

---PREVIOUS PLAN---
$(cat "$output")
EOF
            if [[ -f "$feedback_file" ]]; then
                cat >> "$context_file" <<EOF

---USER FEEDBACK---
$(cat "$feedback_file")
EOF
            fi
        fi

        log_step "Calling planner agent..."
        call_claude "planner" "$context_file" "$output"

        log_step "Plan saved: $output"

        # Show plan preview and ask for feedback
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📋 PLAN PREVIEW (first 60 lines)"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        head -60 "$output"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""

        read -p "修改意见（或直接回车接受当前计划）: " feedback

        if [[ -z "$feedback" ]]; then
            # User accepted
            rm -f "$feedback_file"
            break
        fi

        # Save feedback for next iteration
        echo "$feedback" > "$feedback_file"
        log_step "Feedback saved, will regenerate with your意见..."

        ((iteration++))
        if [[ $iteration -gt 5 ]]; then
            warn "Max iterations (5) reached, using current plan"
            rm -f "$feedback_file"
            break
        fi
    done

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
    local feedback_file="$PROJECT_DIR/.claude/ui-design-feedback.md"
    local iteration=1

    log_step "Reading plan: $plan"
    ensure_file "$plan"

    # Create preview directory
    mkdir -p "$PROJECT_DIR/preview"

    # Search Lazyweb for similar designs
    log_step "Searching Lazyweb for design references..."
    local lazyweb_ref_file="$PROJECT_DIR/.claude/lazyweb-ref.txt"
    search_lazyweb_refs "$PROJECT_DIR" > "$lazyweb_ref_file" 2>&1 || true
    if [[ -s "$lazyweb_ref_file" ]]; then
        log_step "Found design references from Lazyweb"
    fi

    while true; do
        log_step "━━━ UI Design Iteration $iteration ━━━"

        # Build context: plan + previous spec (if exists) + feedback
        cat > "$context_file" <<EOF
# UI Design Context

Project: $PROJECT_DIR
Plan: $plan

---PLAN---
$(cat "$plan")
EOF

        # Append Lazyweb references if available
        if [[ -s "$lazyweb_ref_file" ]]; then
            cat >> "$context_file" <<EOF

---LAZYWEB REF---
$(cat "$lazyweb_ref_file")
EOF
        fi

        # If this is iteration > 1, include previous spec and feedback
        if [[ $iteration -gt 1 ]]; then
            cat >> "$context_file" <<EOF

---PREVIOUS SPEC---
$(cat "$spec_output")
EOF
            if [[ -f "$feedback_file" ]]; then
                cat >> "$context_file" <<EOF

---USER FEEDBACK---
$(cat "$feedback_file")
EOF
            fi
        fi

        log_step "Calling UI design agent..."
        local temp_output=$(mktemp)
        call_claude "ui-design" "$context_file" > "$temp_output"

        # Split output by delimiter
        # Find line numbers of key delimiters
        spec_start=$(awk '/^---SPEC---$/{print NR; exit}' "$temp_output")
        html_start=$(awk '/^---HTML---$/{print NR; exit}' "$temp_output")
        html_end=$(awk '/^---END---$/{print NR; exit}' "$temp_output")

        if [[ -n "$html_start" && -n "$html_end" ]]; then
            # Extract spec lines (after ---SPEC--- line, before ---HTML--- line)
            if [[ -n "$spec_start" ]]; then
                awk "NR>$spec_start && NR<$html_start" "$temp_output" > "$spec_output"
            fi
            # Extract HTML lines (after ---HTML--- line, before ---END--- line)
            awk "NR>$html_start && NR<$html_end" "$temp_output" > "$html_output"
        elif [[ -n "$html_start" ]]; then
            # No END marker, just take everything after ---HTML---
            awk "NR>$html_start" "$temp_output" > "$html_output"
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
            rm -f "$feedback_file"
            return 1
        fi

        # Ask for user feedback
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📋 UI Design Preview"
        echo "  Spec: $spec_output"
        echo "  HTML: file://$html_output"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        read -p "修改意见（或直接回车接受当前设计）: " feedback

        if [[ -z "$feedback" ]]; then
            # User accepted, clean up and continue
            rm -f "$feedback_file"
            log_done "UI design confirmed"
            break
        fi

        # Save feedback for next iteration
        echo "$feedback" > "$feedback_file"
        log_step "Feedback saved, will regenerate with your意见..."

        ((iteration++))
        if [[ $iteration -gt 5 ]]; then
            warn "Max iterations (5) reached, using current design"
            rm -f "$feedback_file"
            break
        fi
    done

    save_state "tasks"
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
    local target_phase="${1:-}"
    log_phase "resume"

    if [[ -n "$target_phase" ]]; then
        log "Jumping to phase: $target_phase"
    else
        load_state
        target_phase="$CURRENT_PHASE"
        log "Resuming from phase: $CURRENT_PHASE"
    fi

    case "$target_phase" in
        research)
            phase_research
            phase_plan
            phase_ui_design
            phase_tasks
            phase_develop
            ;;
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
            error "Unknown phase: $target_phase"
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

    # Handle --phase jump or --continue
    if [[ -n "$TARGET_PHASE" ]]; then
        log "🔍 Jumping to phase: $TARGET_PHASE"
        resume_workflow "$TARGET_PHASE"
    elif load_state; then
        log "📂 Found existing workflow state"
        if confirm "Continue from checkpoint?"; then
            resume_workflow
        else
            log "Starting fresh..."
            rm -f "$PROJECT_DIR/state/workflow-state.json"
            phase_research
            phase_plan
            phase_ui_design
            phase_tasks
            phase_develop
        fi
    else
        # Start fresh
        log "🆕 Starting new workflow in: $PROJECT_DIR"
        phase_research
        phase_plan
        phase_ui_design
        phase_tasks
        phase_develop
    fi

    log ""
    log "═══════════════════════════════════════════════════════"
    log " Workflow complete!"
    log " Log saved: $LOG_FILE"
    log "═══════════════════════════════════════════════════════"
}

# === Entry Point ===
main "$@"
