#!/bin/bash
# =============================================================================
# Files Library - File operations
# =============================================================================

# === Ensure file exists ===
ensure_file() {
    local file="$1"
    local msg="${2:-File not found}"

    if [[ ! -f "$file" ]]; then
        error "$msg: $file"
    fi
}

# === Ensure directory exists ===
ensure_dir() {
    local dir="$1"

    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi
}

# === Read JSON value ===
read_json() {
    local file="$1"
    local key="$2"

    if [[ ! -f "$file" ]]; then
        echo ""
        return
    fi

    # Simple JSON parsing (no jq dependency)
    grep "\"$key\"" "$file" | sed 's/.*:.*"\([^"]*\)".*/\1/'
}

# === Write JSON value ===
write_json() {
    local file="$1"
    local key="$2"
    local value="$3"

    if [[ -f "$file" ]]; then
        # Update existing value
        sed -i '' "s/\"$key\": \"[^\"]*\"/\"$key\": \"$value\"/" "$file"
    else
        # Create new file
        cat > "$file" <<EOF
{
  "$key": "$value"
}
EOF
    fi
}

# === Get next pending task ===
get_next_task() {
    local queue_file="$PROJECT_DIR/003-task-queue.json"

    if [[ ! -f "$queue_file" ]]; then
        echo ""
        return
    fi

    # Extract next pending task ID (simple grep-based)
    grep -o '"id": "[^"]*"' "$queue_file" | head -1 | cut -d'"' -f4
}

# === Complete task ===
complete_task() {
    local task_id="$1"
    local queue_file="$PROJECT_DIR/003-task-queue.json"

    if [[ ! -f "$queue_file" ]]; then
        return
    fi

    # Mark task as completed (simple sed replacement)
    sed -i '' "s/\"$task_id\"/\"${task_id}_done\"/" "$queue_file"
}
