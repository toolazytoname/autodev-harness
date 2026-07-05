#!/bin/bash
# =============================================================================
# Tests for lib/claude.sh - critical bug fixes
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/../lib/claude.sh"

echo "=== Test: is_score_passed with PASS_THRESHOLD=0.8 ==="
export PASS_THRESHOLD=0.8

# Test passing scores
for score in "0.8" "0.85" "0.9" "1.0"; do
    if is_score_passed "$score"; then
        echo "PASS: is_score_passed($score) = true"
    else
        echo "FAIL: is_score_passed($score) should be true, got false"
        exit 1
    fi
done

# Test failing scores
for score in "0.0" "0.5" "0.79"; do
    if is_score_passed "$score"; then
        echo "FAIL: is_score_passed($score) should be false, got true"
        exit 1
    else
        echo "PASS: is_score_passed($score) = false"
    fi
done

echo ""
echo "=== Test: Score extraction from feedback file ==="
TEMP_FEEDBACK=$(mktemp)

# Create a fake feedback file with a TOTAL score
cat > "$TEMP_FEEDBACK" <<'EOF'
# Evaluation Report

Some content here...

**TOTAL**: 0.85 / 1.0

More content...
EOF

# Use grep to extract the score (same logic as run_evaluator)
score=$(grep -oE '\*\*TOTAL\*\*[^[:digit:]]*[[:digit:]]+\.[[:digit:]]+' "$TEMP_FEEDBACK" | grep -oE '[[:digit:]]+\.[[:digit:]]+' | head -1)

if [[ "$score" == "0.85" ]]; then
    echo "PASS: score extraction returned '$score'"
else
    echo "FAIL: expected '0.85', got '$score'"
    rm -f "$TEMP_FEEDBACK"
    exit 1
fi

# Test edge case: score at beginning of line
cat > "$TEMP_FEEDBACK" <<'EOF'
**TOTAL** 0.92
EOF
score=$(grep -oE '\*\*TOTAL\*\*[^[:digit:]]*[[:digit:]]+\.[[:digit:]]+' "$TEMP_FEEDBACK" | grep -oE '[[:digit:]]+\.[[:digit:]]+' | head -1)
if [[ "$score" == "0.92" ]]; then
    echo "PASS: edge case score extraction returned '$score'"
else
    echo "FAIL: edge case expected '0.92', got '$score'"
    rm -f "$TEMP_FEEDBACK"
    exit 1
fi

rm -f "$TEMP_FEEDBACK"

echo ""
echo "=== All claude.sh tests passed ==="
