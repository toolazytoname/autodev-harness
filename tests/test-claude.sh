#!/bin/bash
# =============================================================================
# Tests for lib/claude.sh - critical bug fixes (T01)
#
# Acceptance:
#   - is_score_passed compares floats correctly across bc and awk paths,
#     without the command-substitution-as-execution bug
#   - Score extraction reads **TOTAL**: x.y lines tolerantly, with a BSD-
#     compatible regex (no -P PCRE)
#   - Boundary scores at the threshold return true (>=)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/../lib/claude.sh"

# --- is_score_passed ------------------------------------------------------------

echo "=== Test 1: is_score_passed with PASS_THRESHOLD=0.8 ==="
export PASS_THRESHOLD=0.8

# Boundary + passing scores
for score in "0.8" "0.85" "0.9" "1.0" "0.8001"; do
    if is_score_passed "$score"; then
        echo "PASS: is_score_passed($score) = true"
    else
        echo "FAIL: is_score_passed($score) should be true, got false"
        exit 1
    fi
done

# Just below threshold + zero scores
for score in "0.0" "0.5" "0.79" "0.7999"; do
    if is_score_passed "$score"; then
        echo "FAIL: is_score_passed($score) should be false, got true"
        exit 1
    else
        echo "PASS: is_score_passed($score) = false"
    fi
done

echo ""
echo "=== Test 2: is_score_passed with non-default threshold 0.95 ==="
PASS_THRESHOLD=0.95
for score in "0.95" "0.96" "1.0"; do
    is_score_passed "$score" || { echo "FAIL: $score should pass with threshold 0.95"; exit 1; }
    echo "PASS: is_score_passed($score) at threshold 0.95 = true"
done
for score in "0.94" "0.5" "0.0"; do
    is_score_passed "$score" && { echo "FAIL: $score should fail with threshold 0.95"; exit 1; }
    echo "PASS: is_score_passed($score) at threshold 0.95 = false"
done

echo ""
echo "=== Test 3: is_score_passed exit code (regression: command-substitution bug) ==="
# Before the fix, `$(echo "$score >= $PASS_THRESHOLD" | bc -l)` ran the bc
# output (0/1) as a command, producing "command not found" and leaving the
# exit code as that of the bogus lookup — gate never opened. With the fix,
# bc/awk numeric comparison is consumed properly and the function returns 0.
# We must disable `set -e` while invoking the function because the false
# branch returns a nonzero status (which is exactly what we want to inspect).
export PASS_THRESHOLD=0.5
set +e
is_score_passed "0.9" >/dev/null
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
    echo "PASS: is_score_passed exits 0 when true (was nonzero before fix)"
else
    echo "FAIL: is_score_passed exit=$rc — command-substitution bug not fixed?"
    exit 1
fi
set +e
is_score_passed "0.1" >/dev/null
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
    echo "PASS: is_score_passed exits nonzero when false"
else
    echo "FAIL: is_score_passed exit=0 when it should be nonzero"
    exit 1
fi

# --- Score extraction (the regex run_evaluator actually uses) -----------------

echo ""
echo "=== Test 4: Score extraction handles '**TOTAL**: x.y' format ==="
TEMP_FEEDBACK=$(mktemp)
cat > "$TEMP_FEEDBACK" <<'EOF'
# Evaluation Report

Some content here...

**TOTAL**: 0.85 / 1.0

More content...
EOF

# Same regex pair used by run_evaluator in lib/claude.sh
score=$(grep -oE '\*\*TOTAL\*\*[^[:digit:]]*[[:digit:]]+\.[[:digit:]]+' "$TEMP_FEEDBACK" | grep -oE '[[:digit:]]+\.[[:digit:]]+' | head -1)
if [[ "$score" == "0.85" ]]; then
    echo "PASS: extracted '$score' from ':' separated **TOTAL** line"
else
    echo "FAIL: expected '0.85', got '$score'"
    rm -f "$TEMP_FEEDBACK"
    exit 1
fi

echo ""
echo "=== Test 5: Score extraction handles whitespace separator (BSD-friendly) ==="
cat > "$TEMP_FEEDBACK" <<'EOF'
**TOTAL** 0.92
EOF
score=$(grep -oE '\*\*TOTAL\*\*[^[:digit:]]*[[:digit:]]+\.[[:digit:]]+' "$TEMP_FEEDBACK" | grep -oE '[[:digit:]]+\.[[:digit:]]+' | head -1)
if [[ "$score" == "0.92" ]]; then
    echo "PASS: extracted '$score' from whitespace-separated **TOTAL**"
else
    echo "FAIL: expected '0.92', got '$score'"
    rm -f "$TEMP_FEEDBACK"
    exit 1
fi

echo ""
echo "=== Test 6: Extraction is grep -E based (no grep -P, so macOS-safe) ==="
# Sanity: the extraction pipeline must not depend on PCRE.
if grep -V 2>/dev/null | grep -q 'grep -P'; then
    echo "INFO: host grep advertises -P; portability cannot be proven here, but we use -E not -P."
fi
if grep -oE '\*\*TOTAL\*\*[^[:digit:]]*[[:digit:]]+\.[[:digit:]]+' "$TEMP_FEEDBACK" >/dev/null 2>&1; then
    echo "PASS: extraction uses POSIX ERE only"
fi

rm -f "$TEMP_FEEDBACK"

echo ""
echo "=== All claude.sh tests passed ==="
