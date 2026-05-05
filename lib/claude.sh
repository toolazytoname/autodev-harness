#!/bin/bash
# =============================================================================
# Claude Library - Claude API interactions
# =============================================================================

# === Call Claude with agent ===
call_claude() {
    local agent="$1"
    local input="${2:-}"
    local output="${3:-}"
    local agent_file="$SCRIPT_DIR/agents/${agent}.md"

    log_step "Agent: $agent, Input: ${input:-stdin}, Output: ${output:-stdout}"

    if [[ ! -f "$agent_file" ]]; then
        error "Agent not found: $agent"
    fi

    # Use temp file for prompt
    local prompt_file=$(mktemp)
    cat "$agent_file" > "$prompt_file"

    if [[ -n "$input" && -f "$input" ]]; then
        echo "" >> "$prompt_file"
        echo "---INPUT---" >> "$prompt_file"
        cat "$input" >> "$prompt_file"
    fi

    log_step "Calling claude with model: ${LLM_MODEL:-claude-3-5-sonnet-4-7}"
    local start_time=$(date +%s)

    # Execute claude with prompt file
    if [[ -n "$output" ]]; then
        ECC_GATEGUARD=off claude @"$prompt_file" --model "${LLM_MODEL:-claude-3-5-sonnet-4-7}" > "$output" 2>&1
        local exit_code=$?
    else
        ECC_GATEGUARD=off claude @"$prompt_file" --model "${LLM_MODEL:-claude-3-5-sonnet-4-7}" 2>&1
        local exit_code=$?
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    rm -f "$prompt_file"

    if [[ -n "$output" && -f "$output" ]]; then
        local output_size=$(wc -c < "$output")
        log_step "Output: ${output_size} bytes, Duration: ${duration}s, Exit: $exit_code"
    else
        log_step "Duration: ${duration}s, Exit: $exit_code"
    fi

    return $exit_code
}

# === Run generator ===
run_generator() {
    local task="$1"
    local iteration="$2"

    log_step "Generator for task: $task (iteration $iteration)"

    # Create context file for generator
    local context_file="$PROJECT_DIR/.claude/generator-context.md"
    ensure_dir "$PROJECT_DIR/.claude"

    cat > "$context_file" <<EOF
# Generator Context

Task: $task
Iteration: $iteration
Project: $PROJECT_DIR

Current Spec: $PROJECT_DIR/004-spec.md
Eval Rubric: $PROJECT_DIR/005-eval-rubric.md
EOF

    call_claude "generator" "$context_file"
}

# === Run evaluator ===
run_evaluator() {
    local iteration="$1"
    local feedback_file="$PROJECT_DIR/feedback/gan/iteration-$(printf '%03d' $iteration).md"

    log_step "Running evaluator..."

    ensure_dir "$PROJECT_DIR/feedback/gan"

    call_claude "evaluator" > "$feedback_file"

    # Extract score (simple grep)
    local score=$(grep -oP '\*\*TOTAL\*\*.*?(\d+\.\d+)' "$feedback_file" | grep -oP '\d+\.\d+' | head -1)

    log_step "Score: ${score:-0}"
    echo "${score:-0}"
}

# === Check if score passed ===
is_score_passed() {
    local score="$1"

    # Compare with threshold (simple bc comparison)
    if command -v bc &>/dev/null; then
        $(echo "$score >= $PASS_THRESHOLD" | bc -l)
    else
        # Fallback: compare as integers (5.0 -> 50, 7.0 -> 70)
        local score_int=$(echo "$score * 10" | bc 2>/dev/null || echo "0")
        local threshold_int=$(echo "$PASS_THRESHOLD * 10" | bc 2>/dev/null || echo "0")
        [[ $score_int -ge $threshold_int ]]
    fi
}

# === Save iteration ===
save_iteration() {
    local iteration="$1"
    local score="$2"

    log "📊 Iteration $iteration: score $score"
}

# === Save feedback ===
save_feedback() {
    local iteration="$1"
    local score="$2"

    log "📝 Saved feedback for iteration $iteration (score: $score)"
}
