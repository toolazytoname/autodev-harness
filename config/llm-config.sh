#!/bin/bash
# LLM Configuration - Simple model/key/url config

LLM_MODEL=""; LLM_API_KEY=""; LLM_URL=""

load_config_env() {
    # First check harness-specific variables
    [[ -n "$AUTODEV_MODEL" ]] && LLM_MODEL="$AUTODEV_MODEL"
    [[ -n "$AUTODEV_API_KEY" ]] && LLM_API_KEY="$AUTODEV_API_KEY"
    [[ -n "$AUTODEV_BASE_URL" ]] && LLM_URL="$AUTODEV_BASE_URL"

    # Fall back to Claude Code variables if not set
    [[ -n "$LLM_MODEL" ]] || [[ -n "$ANTHROPIC_MODEL" ]] && LLM_MODEL="${ANTHROPIC_MODEL:-}"
    [[ -n "$LLM_API_KEY" ]] || [[ -n "$ANTHROPIC_API_KEY" ]] && LLM_API_KEY="${ANTHROPIC_API_KEY:-}"
    [[ -n "$LLM_URL" ]] || [[ -n "$ANTHROPIC_BASE_URL" ]] && LLM_URL="${ANTHROPIC_BASE_URL:-}"
}

set_defaults() {
    [[ -n "$LLM_MODEL" ]] || LLM_MODEL="MiniMax-M2.7"
    [[ -n "$LLM_URL" ]] || LLM_URL="https://api.minimaxi.com/anthropic"
}

load_llm_config() {
    load_config_env
    set_defaults
}

apply_cli_config() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model) LLM_MODEL="$2"; shift 2 ;;
            --llm-key) LLM_API_KEY="$2"; shift 2 ;;
            --llm-url) LLM_URL="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
}

show_llm_config() {
    echo "LLM Configuration:"
    echo "  Model: ${LLM_MODEL:-not set}"
    echo "  URL: ${LLM_URL:-not set}"
    echo "  API Key: ${LLM_API_KEY:+***}"
}
