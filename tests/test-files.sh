#!/bin/bash
# =============================================================================
# Tests for lib/files.sh - critical bug fixes (T01)
#
# Acceptance:
#   - get_next_task tolerates pretty-JSON whitespace ("id": "x" and "id":"x")
#   - get_next_task skips tasks whose status is already "completed" (does NOT
#     return the just-completed task again)
#   - complete_task marks the task done by setting status="completed"
#     (per T01 spec: "用 jq 精确改 status 字段")
#   - complete_task does NOT corrupt other tasks' dependencies arrays
#   - All four scenarios above work on macOS and Linux.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
export PROJECT_DIR

# Source the library
source "$SCRIPT_DIR/../lib/files.sh"

# Use Python (universally available) as the JSON engine; tests, scripts, and
# production all share the same status-field semantics.
create_task_queue() {
    local file="$1"
    python3 - "$file" <<'PYEOF'
import json, sys
queue = {
    "tasks": [
        {
            "id": "task-001",
            "title": "First task",
            "status": "pending",
            "dependencies": []
        },
        {
            "id": "task-002",
            "title": "Second task",
            "status": "pending",
            "dependencies": ["task-001"]
        },
        {
            "id": "task-003",
            "title": "Third task",
            "status": "pending",
            "dependencies": ["task-001", "task-002"]
        }
    ]
}
with open(sys.argv[1], 'w') as f:
    json.dump(queue, f, indent=2)
    f.write("\n")
PYEOF
}

# Pure-JSON validity + structural integrity check (no jq required).
validate_task_queue() {
    python3 - "$1" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    raw = f.read()
try:
    data = json.loads(raw)
except json.JSONDecodeError as exc:
    print(f"FAIL: queue is not valid JSON: {exc}")
    sys.exit(1)

if "tasks" not in data or not isinstance(data["tasks"], list):
    print("FAIL: queue missing 'tasks' array")
    sys.exit(1)

ids = [t["id"] for t in data["tasks"]]
if "task-001" not in ids:
    print(f"FAIL: task-001 id was mutated; current ids: {ids}")
    sys.exit(1)

# Every dependency must be one of the original task ids — never "_done"
# suffixed and never missing.
original_ids = set(ids)
for t in data["tasks"]:
    for dep in t.get("dependencies", []) or []:
        if dep not in original_ids:
            print(f"FAIL: task {t['id']} has corrupted dep '{dep}' (original ids: {sorted(original_ids)})")
            sys.exit(1)

print("PASS: JSON structure intact, no _done suffix poisoning")
PYEOF
}

echo "=== Test 1: get_next_task on pretty-JSON queue returns first pending task ==="
TEMP_DIR=$(mktemp -d)
export PROJECT_DIR="$TEMP_DIR"
TEMP_QUEUE="$TEMP_DIR/003-task-queue.json"
create_task_queue "$TEMP_QUEUE"

RESULT=$(get_next_task)
if [[ "$RESULT" == "task-001" ]]; then
    echo "PASS: get_next_task returned '$RESULT' (pretty-JSON, whitespace tolerated)"
else
    echo "FAIL: expected 'task-001', got '$RESULT'"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo ""
echo "=== Test 2: complete_task marks status=completed (does NOT rename id) ==="
complete_task "task-001"

python3 - "$TEMP_QUEUE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)

errors = []
task_001 = next((t for t in data["tasks"] if t["id"] == "task-001"), None)
if task_001 is None:
    errors.append("task-001 id was renamed/mutated (id should remain 'task-001')")
elif task_001.get("status") != "completed":
    errors.append(f"task-001 status should be 'completed', got '{task_001.get('status')}'")

# Any _done suffix anywhere would indicate we're back to the buggy sed path
for t in data["tasks"]:
    if t["id"].endswith("_done"):
        errors.append(f"task id mutated to {t['id']} (no _done suffix expected)")

if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
print("PASS: task-001 status flipped to completed, id unchanged")
PYEOF

echo ""
echo "=== Test 3: get_next_task returns NEXT pending task, NOT the completed one ==="
NEXT=$(get_next_task)
# task-001 is done so task-002 (only blocker is task-001, which is now done)
# should be eligible. task-003 needs both task-001 and task-002 done.
if [[ "$NEXT" == "task-002" ]]; then
    echo "PASS: get_next_task returns '$NEXT' after completing task-001"
else
    echo "FAIL: expected 'task-002' (the next ready task), got '$NEXT'"
    echo "      (regression: this was the CRITICAL bug — loop returned done tasks)"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo ""
echo "=== Test 4: dependencies arrays of other tasks are NOT corrupted ==="
validate_task_queue "$TEMP_QUEUE"

# Additionally, raw read for sanity
python3 - "$TEMP_QUEUE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)

deps_map = {t["id"]: t.get("dependencies", []) for t in data["tasks"]}

# task-002 deps must still be exactly ["task-001"] (not "_done" version)
if deps_map.get("task-002") != ["task-001"]:
    print(f"FAIL: task-002 deps are {deps_map.get('task-002')}, expected ['task-001']")
    sys.exit(1)

# task-003 deps must still be exactly ["task-001", "task-002"]
if deps_map.get("task-003") != ["task-001", "task-002"]:
    print(f"FAIL: task-003 deps are {deps_map.get('task-003')}, expected ['task-001', 'task-002']")
    sys.exit(1)

print(f"PASS: dependencies intact (task-002: {deps_map['task-002']}, task-003: {deps_map['task-003']})")
PYEOF

echo ""
echo "=== Test 5: completing all tasks returns empty (loop exit signal) ==="
complete_task "task-002"
complete_task "task-003"

NEXT=$(get_next_task)
if [[ -z "$NEXT" ]]; then
    echo "PASS: get_next_task returned empty when all tasks done"
else
    echo "FAIL: expected empty, got '$NEXT'"
    rm -rf "$TEMP_DIR"
    exit 1
fi

rm -rf "$TEMP_DIR"

echo ""
echo "=== All files.sh tests passed ==="
