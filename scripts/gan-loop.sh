#!/bin/bash
# gan-loop.sh — GAN Generator-Evaluator Feedback Loop
#
# Usage:
#   ./scripts/gan-loop.sh [--iterations N] [--threshold SCORE]
#   GAN_DEV_SERVER_PORT=3000 ./scripts/gan-loop.sh

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

MAX_ITERATIONS="${GAN_MAX_ITERATIONS:-15}"
PASS_THRESHOLD="${GAN_PASS_THRESHOLD:-7.0}"
DEV_PORT="${GAN_DEV_SERVER_PORT:-3000}"
DEV_CMD="${GAN_DEV_SERVER_CMD:-npm run dev}"
EVAL_MODE="${GAN_EVAL_MODE:-playwright}"

HARNESS_DIR="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECT_DIR="${PROJECT_DIR:-$HARNESS_DIR}"
export HARNESS_DIR PROJECT_DIR

FEEDBACK_DIR="${PROJECT_DIR}/feedback/gan"
SCREENSHOTS_DIR="${FEEDBACK_DIR}/screenshots"
START_TIME=$(date +%s)

mkdir -p "$FEEDBACK_DIR" "$SCREENSHOTS_DIR" "${PROJECT_DIR}/logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────

log()    { echo -e "${BLUE}[GAN]${NC} $*"; }
ok()     { echo -e "${GREEN}[✓]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()   { echo -e "${RED}[✗]${NC} $*"; }
phase()  { echo -e "\n${PURPLE}═══════════════════════════════════════════════${NC}"; echo -e "${PURPLE}  $*${NC}"; echo -e "${PURPLE}═══════════════════════════════════════════════${NC}\n"; }

extract_score() {
  local file="$1"
  grep -oP '(?<=\*\*TOTAL\*\*.*\*\*)[0-9]+\.[0-9]+' "$file" 2>/dev/null \
    || grep -oP '(?<=TOTAL.*\|.*\| \*\*)[0-9]+\.[0-9]+' "$file" 2>/dev/null \
    || grep -oP 'Verdict:.*([0-9]+\.[0-9]+)' "$file" 2>/dev/null | grep -oP '[0-9]+\.[0-9]+' \
    || echo "0.0"
}

score_passes() {
  local score="$1"
  local threshold="$2"
  awk -v s="$score" -v t="$threshold" 'BEGIN { exit !(s >= t) }'
}

elapsed() {
  local now=$(date +%s)
  local diff=$((now - START_TIME))
  printf '%dh %dm %ds' $((diff/3600)) $((diff%3600/60)) $((diff%60))
}

# ─── Generator ────────────────────────────────────────────────────────────────

run_generator() {
  local iteration=$1
  local feedback_context=""

  if [ $iteration -gt 1 ]; then
    local prev_file="${FEEDBACK_DIR}/feedback-$(printf '%03d' $((iteration-1))).md"
    if [ -f "$prev_file" ]; then
      feedback_context="IMPORTANT: Read and address ALL issues in ${prev_file}"
    fi
  fi

  log "Launching Generator (iteration $iteration)..."

  effort=high claude -p --model minimax-latest --dangerously-skip-permissions \
    "You are the Generator in a GAN-style harness.

Iteration: $iteration
$feedback_context

Read autodev-harness/SPEC.md for the product specification.
Read autodev-harness/agents/generator.md for your full instructions.
Build/improve the application. Ensure the dev server runs on port $DEV_PORT.
Commit your changes with message: 'iteration-$(printf '%03d' $iteration)'
Update autodev-harness/state/generator-state.md." \
    2>&1 | tee "${HARNESS_DIR}/logs/generator-${iteration}.log"

  ok "Generator completed iteration $iteration"
}

# ─── Evaluator ───────────────────────────────────────────────────────────────

run_evaluator() {
  local iteration=$1

  log "Launching Evaluator (iteration $iteration)..."

  effort=high claude -p --model minimax-latest --dangerously-skip-permissions \
    "You are the Evaluator in a GAN-style harness.

Iteration: $iteration
Eval mode: $EVAL_MODE
Dev server: http://localhost:$DEV_PORT

Read autodev-harness/SPEC.md for feature requirements.
Read autodev-harness/config/eval-rubric.md for scoring criteria.
Read autodev-harness/state/generator-state.md for what was built.
Test the live application (mode: $EVAL_MODE)
Score against the rubric (1-10 per criterion)
Write detailed feedback to ${FEEDBACK_DIR}/feedback-$(printf '%03d' $iteration).md

Be RUTHLESSLY strict. A 7 means genuinely good, not 'good for AI.'
Include weighted TOTAL score: | **TOTAL** | | | **X.X** |" \
    2>&1 | tee "${HARNESS_DIR}/logs/evaluator-${iteration}.log"

  ok "Evaluator completed iteration $iteration"
}

# ─── Main Loop ───────────────────────────────────────────────────────────────

phase "GAN LOOP — Generator-Evaluator Feedback"

log "Max iterations: $MAX_ITERATIONS"
log "Pass threshold: $PASS_THRESHOLD"
log "Dev server port: $DEV_PORT"

SCORES=()
PREV_SCORE="0.0"
PLATEAU_COUNT=0

for (( i=1; i<=MAX_ITERATIONS; i++ )); do
  echo ""
  log "━━━ Iteration $i / $MAX_ITERATIONS ━━━"

  echo -e "${GREEN}>> GENERATOR${NC}"
  run_generator $i

  echo -e "${RED}>> EVALUATOR${NC}"
  run_evaluator $i

  local feedback_file="${FEEDBACK_DIR}/feedback-$(printf '%03d' $i).md"
  local score="0.0"

  if [ -f "$feedback_file" ]; then
    score=$(extract_score "$feedback_file")
    SCORES+=("$score")
    ok "Score: ${CYAN}${score}${NC} / 10.0 (threshold: $PASS_THRESHOLD)"
  else
    warn "No feedback file produced"
    SCORES+=("0.0")
  fi

  if score_passes "$score" "$PASS_THRESHOLD"; then
    echo ""
    ok "PASSED at iteration $i with score $score"
    break
  fi

  local score_diff=$(awk -v s="$score" -v p="$PREV_SCORE" 'BEGIN { printf "%.1f", s - p }')
  if [ $i -ge 3 ] && awk -v d="$score_diff" 'BEGIN { exit !(d <= 0.2) }'; then
    PLATEAU_COUNT=$((PLATEAU_COUNT + 1))
  else
    PLATEAU_COUNT=0
  fi

  if [ $PLATEAU_COUNT -ge 2 ]; then
    warn "Score plateau detected. Stopping."
    break
  fi

  PREV_SCORE="$score"
done

# ─── Summary ─────────────────────────────────────────────────────────────────

phase "GAN Loop Complete"

FINAL_SCORE="${SCORES[-1]:-0.0}"
NUM_ITERATIONS=${#SCORES[@]}
TIME_ELAPSED=$(elapsed)

echo ""
echo "━━━ Final Results ━━━"
if score_passes "$FINAL_SCORE" "$PASS_THRESHOLD"; then
  echo -e "  Result:     ${GREEN}PASS${NC}"
else
  echo -e "  Result:     ${RED}FAIL${NC}"
fi
echo -e "  Score:      ${CYAN}${FINAL_SCORE}${NC} / 10.0"
echo -e "  Iterations: ${NUM_ITERATIONS} / $MAX_ITERATIONS"
echo -e "  Elapsed:    ${TIME_ELAPSED}"
echo ""

# Save summary
cat > "${HARNESS_DIR}/feedback/gan/summary.json" << EOF
{
  "finalScore": "$FINAL_SCORE",
  "passed": $(score_passes "$FINAL_SCORE" "$PASS_THRESHOLD" && echo "true" || echo "false"),
  "iterations": $NUM_ITERATIONS,
  "maxIterations": $MAX_ITERATIONS,
  "elapsed": "$TIME_ELAPSED",
  "scores": [$(IFS=,; echo "${SCORES[*]}")]
}
EOF

ok "GAN loop complete. Summary: ${HARNESS_DIR}/feedback/gan/summary.json"
