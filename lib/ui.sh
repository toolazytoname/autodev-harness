#!/bin/bash
# =============================================================================
# UI Library - User interface functions and logging
# =============================================================================

# Log file for the project
LOG_FILE=""
CURRENT_PHASE=""

# === Init logging ===
init_logging() {
    local project_dir="$1"
    LOG_FILE="$project_dir/logs/harness.log"
    mkdir -p "$project_dir/logs"
}

# === Logging with file output ===
log() {
    local msg="[$(date +%Y-%m-%d\ %H:%M:%S)] [${CURRENT_PHASE:-init}] $*"
    echo "$msg"
    if [[ -n "$LOG_FILE" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
}

log_phase() {
    local phase="$1"
    CURRENT_PHASE="$phase"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "▶ PHASE START: $phase"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

log_step() {
    log "  ➜ $*"
}

log_done() {
    log "✅ DONE: $*"
}

log_error() {
    log "❌ ERROR: $*"
}

warn() {
    local msg="[$(date +%Y-%m-%d\ %H:%M:%S)] [${CURRENT_PHASE:-init}] ⚠️ $*"
    echo "$msg" >&2
    if [[ -n "$LOG_FILE" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
}

error() {
    local msg="[$(date +%Y-%m-%d\ %H:%M:%S)] [${CURRENT_PHASE:-init}] ❌ $*"
    echo "$msg" >&2
    if [[ -n "$LOG_FILE" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
    exit 1
}

success() {
    local msg="[$(date +%Y-%m-%d\ %H:%M:%S)] [${CURRENT_PHASE:-init}] ✅ $*"
    echo "$msg"
    if [[ -n "$LOG_FILE" ]]; then
        echo "$msg" >> "$LOG_FILE"
    fi
}

# === User Confirmation ===
confirm() {
    local question="$1"
    local response=""

    # Non-interactive mode: auto-approve
    if [[ ! -t 0 ]]; then
        return 0
    fi

    # Interactive mode: read user input
    read -p "$question [y/n]: " response
    [[ "$response" =~ ^[Yy]$ ]]
}

# === Confirm Plan ===
# Returns: 0 = approved, 1 = rejected/cancelled
confirm_plan() {
    local plan_file="$1"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 PLAN PREVIEW"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Show first 50 lines of plan
    head -50 "$plan_file"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if ! confirm "Do you approve this plan?"; then
        echo ""
        echo "Options:"
        echo "  1) Modify the plan file and re-run"
        echo "  2) Cancel"
        read -p "Choose [1/2]: " choice

        case "$choice" in
            1)
                log "Edit $plan_file and run: ./autodev-harness.sh -c $PROJECT_DIR"
                return 1
                ;;
            2)
                log "Cancelled"
                return 1
                ;;
        esac
    fi

    log "Plan approved!"
    return 0
}

# === Spinner ===
spin() {
    local pid=$1
    local delay=0.1
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    while kill -0 $pid 2>/dev/null; do
        local temp="${spinstr#?}"
        printf " [%c]  " "$spinstr"
        spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done

    printf "    \b\b\b\b"
}
