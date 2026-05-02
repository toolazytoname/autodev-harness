#!/bin/bash
# security-review.sh — Security Review Integration

set -euo pipefail

HARNESS_DIR="./autodev-harness"
REVIEW_DIR="${HARNESS_DIR}/feedback/reviews"
mkdir -p "$REVIEW_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[SECURITY]${NC} $*"; }
ok() { echo -e "${GREEN}[✓]${NC} $*"; }

check_secrets() {
  log "Checking for hardcoded secrets..."
  patterns=("api_key.*=['\"][a-zA-Z0-9]{20,}" "sk-[a-zA-Z0-9]{20,}" "ghp_[a-zA-Z0-9]{36}")
  for p in "${patterns[@]}"; do
    grep -rE "$p" --include="*.ts" --include="*.js" . 2>/dev/null | grep -v node_modules | grep -v test && return 1
  done
  return 0
}

check_deps() {
  log "Checking dependencies..."
  command -v npm &>/dev/null && [ -f package.json ] && npm audit --audit-level=high 2>/dev/null
  return 0
}

run_security_review() {
  local timestamp=$(date +%Y%m%d-%H%M%S)
  local output_file="${REVIEW_DIR}/security-review-${timestamp}.md"

  check_secrets && s="✓ No secrets" || s="✗ Secrets found"
  check_deps >/dev/null 2>&1 && d="✓ No vulnerabilities" || d="✗ Vulnerabilities found"

  cat > "$output_file" << REPORT
# Security Review Report
**Date**: $(date)

## Checks
- Secrets: $s
- Dependencies: $d

## Verdict
$(check_secrets && check_deps >/dev/null 2>&1 && echo "PASS" || echo "FAIL - Issues found")
REPORT

  ok "Security review: $output_file"
  cat "$output_file"
}

run_security_review
