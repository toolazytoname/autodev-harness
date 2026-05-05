#!/bin/bash
# =============================================================================
# UI Library - User interface functions
# =============================================================================

# === Logging ===
log() {
    echo "[$(date +%H:%M:%S)] $*"
}

warn() {
    echo "[$(date +%H:%M:%S)] ⚠️ $*" >&2
}

error() {
    echo "[$(date +%H:%M:%S)] ❌ $*" >&2
    exit 1
}

success() {
    echo "[$(date +%H:%M:%S)] ✅ $*"
}

# === User Confirmation ===
confirm() {
    local question="$1"
    local response=""

    if [[ ! -t 0 ]] && ! read -p "$question [y/n]: " response 2>/dev/null; then
        # Non-interactive mode: auto-approve
        return 0
    fi
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
                log "Please edit $plan_file and run again"
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
