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
        sed -i "s/\"$key\": \"[^\"]*\"/\"$key\": \"$value\"/" "$file"
    else
        # Create new file
        cat > "$file" <<EOF
{
  "$key": "$value"
}
EOF
    fi
}

# === Run a small Python helper that reads JSON from stdin and writes JSON to stdout ===
# Used to avoid sed/grep hacks that don't understand JSON structure. jq is the
# production preference, but this script is meant to run even on systems
# without jq (acceptance must not silently fail because of tooling gaps).
_py_json() {
    python3 - "$@"
}

# === Get next pending task ===
# Returns the id of the first task whose status is "pending" and whose
# dependencies are all "completed". Skips already-done tasks by status field.
# Tolerant of pretty-JSON whitespace ("id": "task-001" and "id":"task-001").
# NOTE: the spec calls for jq; we fall back to Python when jq is unavailable
# so the develop loop never silently returns the wrong task.
get_next_task() {
    local queue_file="$PROJECT_DIR/003-task-queue.json"

    if [[ ! -f "$queue_file" ]]; then
        echo ""
        return
    fi

    if command -v jq >/dev/null 2>&1; then
        jq -r '
            .tasks
            | map(select(.status == "pending"))
            | map(select((.dependencies // []) | all(. as $d | any(.id == $d and .status == "completed"))))
            | .[0].id // empty
        ' "$queue_file"
    else
        python3 - "$queue_file" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
done_ids = {t["id"] for t in data["tasks"] if t.get("status") == "completed"}
for task in data["tasks"]:
    if task.get("status") != "pending":
        continue
    deps = task.get("dependencies", []) or []
    if all(d in done_ids for d in deps):
        print(task["id"])
        sys.exit(0)
sys.exit(0)
PYEOF
    fi
}

# === Complete task ===
# Marks the given task id as completed by setting its status field to
# "completed". This is the spec-aligned approach (jq on status field) so
# that subsequent get_next_task calls correctly skip it without corrupting
# the dependencies arrays of other tasks.
# NOTE: backwards-compat — if a queue file still uses the old "_done" id
# suffix (written by the buggy sed), we treat those ids as already
# completed too, so old state files don't cause double-completion.
complete_task() {
    local task_id="$1"
    local queue_file="$PROJECT_DIR/003-task-queue.json"

    if [[ ! -f "$queue_file" ]]; then
        return
    fi

    if command -v jq >/dev/null 2>&1; then
        local tmp
        tmp=$(mktemp)
        jq --arg id "$task_id" '
            .tasks |= map(
                if .id == $id or (.id == ($id + "_done"))
                then .status = "completed"
                else . end
            )
        ' "$queue_file" > "$tmp" && mv "$tmp" "$queue_file"
    else
        local tmp
        tmp=$(mktemp)
        python3 - "$queue_file" "$tmp" "$task_id" <<'PYEOF'
import json, sys
queue_file, out_file, task_id = sys.argv[1], sys.argv[2], sys.argv[3]
with open(queue_file) as f:
    data = json.load(f)
for task in data["tasks"]:
    if task.get("id") == task_id or task.get("id") == f"{task_id}_done":
        task["status"] = "completed"
with open(out_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
        mv "$tmp" "$queue_file"
    fi
}
