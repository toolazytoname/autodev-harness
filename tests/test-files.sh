#!/bin/bash
# =============================================================================
# Tests for lib/files.sh - critical bug fixes
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
export PROJECT_DIR

# Source the library
source "$SCRIPT_DIR/../lib/files.sh"

# Use Python to create valid test JSON (since jq not available)
create_task_queue() {
    local file="$1"
    python3 - "$file" <<'PYEOF'
import json
import sys
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
PYEOF
}

# Use Python to validate JSON structure (avoids jq dependency)
validate_task_queue() {
    python3 - "$1" <<'PYEOF'
import json
import sys
with open(sys.argv[1]) as f:
    data = json.load(f)

tasks = {t["id"]: t for t in data["tasks"]}
issues = []

# Check task-001 is not done
if "task-001_done" in tasks:
    issues.append("FAIL: task-001 was incorrectly renamed to task-001_done")

# Check dependencies still reference original task IDs
for tid, task in tasks.items():
    for dep in task.get("dependencies", []):
        if dep not in tasks and dep + "_done" in tasks:
            issues.append(f"FAIL: dependency '{dep}' was incorrectly renamed to {dep}_done")
        if dep == "task-001_done":
            issues.append(f"FAIL: dependency still references task-001_done instead of task-001")

if issues:
    for i in issues:
        print(i)
    sys.exit(1)
else:
    print("PASS: JSON structure intact")
PYEOF
}

echo "=== Test: get_next_task with pretty-JSON ==="
TEMP_DIR=$(mktemp -d)
TEMP_QUEUE="$TEMP_DIR/003-task-queue.json"
export PROJECT_DIR="$TEMP_DIR"

# Create a pretty-JSON task queue (with spaces, like "id": "task-001")
python3 - "$TEMP_QUEUE" <<'PYEOF'
import json
import sys
queue = {
    "tasks": [
        {"id": "task-001", "title": "First", "status": "pending", "dependencies": []},
        {"id": "task-002", "title": "Second", "status": "pending", "dependencies": ["task-001"]}
    ]
}
with open(sys.argv[1], 'w') as f:
    json.dump(queue, f, indent=2)
PYEOF

RESULT=$(get_next_task)
if [[ "$RESULT" == "task-001" ]]; then
    echo "PASS: get_next_task returned '$RESULT'"
else
    echo "FAIL: expected 'task-001', got '$RESULT'"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo ""
echo "=== Test: complete_task does NOT corrupt dependencies ==="
# Create a fresh queue
python3 - "$TEMP_QUEUE" <<'PYEOF'
import json
import sys
queue = {
    "tasks": [
        {"id": "task-001", "title": "First", "status": "pending", "dependencies": []},
        {"id": "task-002", "title": "Second", "status": "pending", "dependencies": ["task-001"]},
        {"id": "task-003", "title": "Third", "status": "pending", "dependencies": ["task-001", "task-002"]}
    ]
}
with open(sys.argv[1], 'w') as f:
    json.dump(queue, f, indent=2)
PYEOF

# Mark task-001 as complete
complete_task "task-001"

# Validate the JSON structure is intact
python3 - "$TEMP_QUEUE" <<'PYEOF'
import json
import sys
with open(sys.argv[1]) as f:
    raw = f.read()
    data = json.loads(raw)

# Check that dependencies arrays were NOT corrupted by global sed replacement
# The original bug replaced ALL occurrences of "task-001" with "task-001_done"
# So dependencies that originally said ["task-001"] would become ["task-001_done"]
# We must verify this did NOT happen

errors = []

# task-002 should still have deps: ["task-001"] (not ["task-001_done"])
task_002_deps = [t["dependencies"] for t in data["tasks"] if t["id"] == "task-002"][0]
if task_002_deps != ["task-001"]:
    errors.append(f"task-002 dependencies corrupted: expected ['task-001'], got {task_002_deps}")

# task-003 should still have deps: ["task-001", "task-002"] (not corrupted with _done)
task_003_deps = [t["dependencies"] for t in data["tasks"] if t["id"] == "task-003"][0]
if task_003_deps != ["task-001", "task-002"]:
    errors.append(f"task-003 dependencies corrupted: expected ['task-001', 'task-002'], got {task_003_deps}")

# task-001's own id should be renamed to task-001_done
task_001_id = [t["id"] for t in data["tasks"] if "task-001" in t["id"]][0]
if task_001_id != "task-001_done":
    errors.append(f"task-001 not marked as done: expected 'task-001_done', got '{task_001_id}'")

if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("PASS: dependencies array intact after complete_task")
    print(f"task-001 marked as: {[t['id'] for t in data['tasks'] if 'task-001' in t['id']][0]}")
    print(f"task-002 deps: {task_002_deps}")
    print(f"task-003 deps: {task_003_deps}")
PYEOF

rm -rf "$TEMP_DIR"

echo ""
echo "=== All tests passed ==="
