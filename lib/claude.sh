#!/bin/bash
# =============================================================================
# Claude Library - Claude API interactions with retry and observability
# =============================================================================

# Retry configuration
MAX_RETRIES=3
RETRY_BASE_DELAY=2

# === Call Claude with agent (with retry and logging) ===
call_claude() {
    local agent="$1"
    local input="${2:-}"
    local output="${3:-}"
    local agent_file="$SCRIPT_DIR/agents/${agent}.md"

    log_step "┌─ Agent call: $agent"
    log_step "│  Input: ${input:-stdin}"
    log_step "│  Output: ${output:-stdout}"
    log_step "│  Model: ${LLM_MODEL:-MiniMax-M2.7}"

    if [[ ! -f "$agent_file" ]]; then
        log_error "│  ✗ Agent file not found: $agent_file"
        error "Agent not found: $agent"
    fi

    # Prepare prompt file
    local prompt_file=$(mktemp)
    cat "$agent_file" > "$prompt_file"

    if [[ -n "$input" && -f "$input" ]]; then
        echo "" >> "$prompt_file"
        echo "---INPUT---" >> "$prompt_file"
        cat "$input" >> "$prompt_file"
    fi

    local input_size=$(wc -c < "$prompt_file")
    log_step "│  Prompt size: ${input_size} bytes"

    # Execute with retry
    local attempt=1
    local exit_code=0
    local last_error=""

    while [[ $attempt -le $MAX_RETRIES ]]; do
        log_step "│  Attempt $attempt/$MAX_RETRIES..."
        log_step "│  ▶ Starting agent..."

        local start_time=$(date +%s)

        if [[ -n "$output" ]]; then
            # Run with output streaming - show progress every 10 seconds
            {
                ECC_GATEGUARD=off claude @"$prompt_file" --model "${LLM_MODEL:-MiniMax-M2.7}" 2>&1
            } | tee "$output" &
            local pid=$!
            
            # Show progress while running
            while kill -0 $pid 2>/dev/null; do
                log_step "│  ⏳ Agent running... (pid: $pid)"
                sleep 10
            done
            
            # Wait for completion
            wait $pid
            exit_code=$?
        else
            ECC_GATEGUARD=off claude @"$prompt_file" --model "${LLM_MODEL:-MiniMax-M2.7}" 2>&1
            exit_code=$?
        fi

        local end_time=$(date +%s)
        local duration=$((end_time - start_time))

        if [[ $exit_code -eq 0 ]]; then
            log_step "│  ✓ Completed in ${duration}s"
            break
        else
            last_error=$(cat "$output" 2>/dev/null | tail -10 | head -5)
            log_step "│  ✗ Failed in ${duration}s (exit: $exit_code)"
            log_step "│  ↺ Retrying in ${RETRY_BASE_DELAY}s..."

            if [[ $attempt -lt $MAX_RETRIES ]]; then
                sleep $RETRY_BASE_DELAY
            fi
        fi

        ((attempt++))
    done

    rm -f "$prompt_file"

    if [[ $exit_code -ne 0 ]]; then
        log_error "│  ✗ All $MAX_RETRIES attempts failed"
        return $exit_code
    fi

    if [[ -n "$output" && -f "$output" ]]; then
        local output_size=$(wc -c < "$output")
        log_step "│  Output size: ${output_size} bytes"
    fi

    log_step "└─ Call complete"
    return 0
}

# === Run generator ===
run_generator() {
    local task="$1"
    local iteration="$2"

    log_step "Generator for task: $task (iteration $iteration)"

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

    local score=$(grep -oP '\*\*TOTAL\*\*.*?(\d+\.\d+)' "$feedback_file" | grep -oP '\d+\.\d+' | head -1)

    log_step "Score: ${score:-0}"
    echo "${score:-0}"
}

# === Check if score passed ===
is_score_passed() {
    local score="$1"

    if command -v bc &>/dev/null; then
        $(echo "$score >= $PASS_THRESHOLD" | bc -l)
    else
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

    # Persist iteration to state
    local iter_file="$PROJECT_DIR/state/iterations.json"
    mkdir -p "$PROJECT_DIR/state"

    if [[ -f "$iter_file" ]]; then
        # Append to existing
        local temp=$(mktemp)
        jq --arg i "$iteration" --arg s "$score" '. + [{iteration: $i, score: $s, timestamp: now}]' "$iter_file" > "$temp" 2>/dev/null || echo "[{\"iteration\":\"$iteration\",\"score\":\"$score\",\"timestamp\":$(date +%s)}]" > "$temp"
        mv "$temp" "$iter_file"
    else
        echo "[{\"iteration\":\"$iteration\",\"score\":\"$score\",\"timestamp\":$(date +%s)}]" > "$iter_file"
    fi
}

# === Save feedback ===
save_feedback() {
    local iteration="$1"
    local score="$2"

    log "📝 Saved feedback for iteration $iteration (score: $score)"
}
