#!/bin/bash
# run-quality-gates.sh — Quality Gates Execution Framework
#
# Usage:
#   ./scripts/run-quality-gates.sh [gate1 gate2 ...]
#   ./scripts/run-quality-gates.sh all
#   GAN_TIMEOUT=300 ./scripts/run-quality-gates.sh build
#
# Environment Variables:
#   GAN_TIMEOUT         — Override default gate timeout (seconds)
#   GAN_GATES_DIR       — Output directory for gate results
#   GAN_COVERAGE_THRESHOLD — Required test coverage (default: 80)

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

HARNESS_DIR="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECT_DIR="${PROJECT_DIR:-$HARNESS_DIR}"
export HARNESS_DIR PROJECT_DIR

GATES_DIR="${GAN_GATES_DIR:-$PROJECT_DIR/quality/gates}"
GATE_TIMEOUT="${GAN_TIMEOUT:-300}"
COVERAGE_THRESHOLD="${GAN_COVERAGE_THRESHOLD:-80}"

mkdir -p "$GATES_DIR"/{lint,build,test,e2e,security}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ─── Helpers ─────────────────────────────────────────────────────────────────

log()    { echo -e "${YELLOW}[GATES]${NC} $*"; }
ok()     { echo -e "${GREEN}[PASS]${NC} $*"; }
fail()   { echo -e "${RED}[FAIL]${NC} $*"; }
blocked() { echo -e "${RED}[BLOCKED]${NC} $*"; exit 1; }

timestamp() { date +%Y%m%d-%H%M%S; }

run_gate() {
  local gate=$1
  local output_file="${GATES_DIR}/${gate}/$(timestamp).log"
  local start_time=$(date +%s)

  log "Running gate: $gate"

  local exit_code=0
  case $gate in
    lint)
      if command -v npm &>/dev/null && [ -f package.json ]; then
        if npm run lint &>"$output_file"; then
          ok "lint passed"
          return 0
        fi
      elif [ -f ".eslintrc.js" ] || [ -f ".eslintrc.json" ]; then
        if npx eslint . &>"$output_file"; then
          ok "lint passed"
          return 0
        fi
      else
        echo "No linter configured" > "$output_file"
        ok "lint skipped (no linter)"
        return 0
      fi
      ;;

    build)
      if npm run build &>"$output_file"; then
        ok "build passed"
        return 0
      fi
      ;;

    test)
      if npm test &>"$output_file"; then
        ok "tests passed"
        return 0
      fi
      ;;

    e2e)
      if command -v npx &>/dev/null && [ -d "e2e" ] || [ -d "tests/e2e" ]; then
        if npx playwright test &>"$output_file"; then
          ok "e2e tests passed"
          return 0
        fi
      else
        echo "No e2e tests configured" > "$output_file"
        ok "e2e skipped (no tests)"
        return 0
      fi
      ;;

    security)
      if command -v npm &>/dev/null; then
        if npm audit --audit-level=high &>"$output_file"; then
          ok "security checks passed"
          return 0
        fi
      else
        echo "No npm found, skipping security" > "$output_file"
        ok "security skipped"
        return 0
      fi
      ;;

    *)
      fail "Unknown gate: $gate"
      return 1
      ;;
  esac

  local end_time=$(date +%s)
  local duration=$((end_time - start_time))
  fail "$gate failed after ${duration}s"
  return 1
}

# ─── Main ────────────────────────────────────────────────────────────────────

if [ $# -eq 0 ] || [ "$1" = "all" ]; then
  GATES=(lint build test e2e security)
elif [ "$1" = "critical" ]; then
  GATES=(lint build test)
elif [ "$1" = "basic" ]; then
  GATES=(lint build)
else
  GATES=("$@")
fi

log "Running gates: ${GATES[*]}"
echo ""

FAILED_GATES=()
BLOCKING_FAILURES=()

for gate in "${GATES[@]}"; do
  local blocking=true
  if [ -f autodev-harness/config/harness.config.json ] && command -v jq &>/dev/null; then
    blocking=$(jq -r ".qualityGates.\"${gate}\".blocking // true" autodev-harness/config/harness.config.json 2>/dev/null || echo "true")
  fi

  if run_gate "$gate"; then
    :
  else
    FAILED_GATES+=("$gate")
    if [ "$blocking" = "true" ]; then
      BLOCKING_FAILURES+=("$gate")
    fi
  fi
  echo ""
done

# ─── Summary ─────────────────────────────────────────────────────────────────

echo "═══════════════════════════════════════"
if [ ${#BLOCKING_FAILURES[@]} -eq 0 ]; then
  if [ ${#FAILED_GATES[@]} -eq 0 ]; then
    ok "All gates passed!"
    exit 0
  else
    echo -e "${YELLOW}[WARN]${NC} Non-blocking gates failed: ${FAILED_GATES[*]}"
    exit 0
  fi
else
  blocked "Blocking gates failed: ${BLOCKING_FAILURES[*]}"
fi
