#!/bin/bash
# AutoDevHarness Default Configuration

# Mode settings
DEFAULT_MODE="new"

# Development loop settings
DEFAULT_MAX_ITERATIONS=15
DEFAULT_PASS_THRESHOLD=7.0

# Test mode settings
TEST_MAX_ITERATIONS=3
TEST_PASS_THRESHOLD=5.0

# Feature flags
SKIP_E2E=false
SKIP_SECURITY=false

# State file locations
STATE_DIR="state"
STATE_FILE="workflow-state.json"
LOG_FILE="logs/harness.log"

# Agent timeouts (seconds)
AGENT_TIMEOUT=300
AGENT_MAX_RETRIES=3

# Project file naming
BRIEF_FILE="000-brief.md"
RESEARCH_FILE="001-research-report.md"
PLAN_FILE="002-plan.md"
TASKS_FILE="003-task-queue.json"
SPEC_FILE="004-spec.md"
RUBRIC_FILE="005-eval-rubric.md"
UI_SPEC_FILE="006-ui-spec.md"
ACTION=""
PROJECT_DIR=""
BRIEF_ARGS=""

# Infrastructure config file
INFRA_CONFIG_FILE=".infrastructure.conf"
