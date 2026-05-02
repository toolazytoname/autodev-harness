#!/bin/bash
# code-review.sh — Code Review Integration

set -euo pipefail

HARNESS_DIR="./autodev-harness"
REVIEW_DIR="${HARNESS_DIR}/feedback/reviews"
SCOPE="${1:-changes}"

mkdir -p "$REVIEW_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[CODE-REVIEW]${NC} $*"; }
ok() { echo -e "${GREEN}[✓]${NC} $*"; }

get_files_to_review() {
  case "$SCOPE" in
    changes) git diff --name-only HEAD 2>/dev/null | grep -E '\.(ts|tsx|js|jsx)$' | head -20 ;;
    staged) git diff --cached --name-only | grep -E '\.(ts|tsx|js|jsx)$' | head -20 ;;
    all) find . -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" | grep -v node_modules | head -50 ;;
    *) echo "$SCOPE" ;;
  esac
}

run_review() {
  local timestamp=$(date +%Y%m%d-%H%M%S)
  local output_file="${REVIEW_DIR}/code-review-${timestamp}.md"
  local files=$(get_files_to_review)

  [ -z "$files" ] && { log "No files to review"; return 0; }

  log "Reviewing files..."
  echo "$files" > "${REVIEW_DIR}/files-reviewed-${timestamp}.txt"

  claude -p --model sonnet --allowedTools "Read,Write,Bash,Grep,Glob" \
    "You are a code reviewer. Review files in ${REVIEW_DIR}/files-reviewed-${timestamp}.txt
Output to ${output_file}. Check: code quality, security, TypeScript, performance, testing.
Format with Critical/High/Medium/Low issues and Verdict: APPROVE or BLOCK." \
    2>&1 | tee "${REVIEW_DIR}/code-review-${timestamp}.log"

  [ -f "$output_file" ] && ok "Review complete: $output_file"
  grep -q "BLOCK" "$output_file" 2>/dev/null && return 1 || return 0
}

run_review && ok "Code review passed" || { log "Code review found issues"; exit 1; }
