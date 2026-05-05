#!/bin/bash
# LLM Configuration - Simple model/key/url config
# Defaults from environment variables (like Claude Code)

LLM_MODEL=""; LLM_API_KEY=""; LLM_URL=""

load_config_env() {
    [[ -n "$ANTHROPIC_MODEL" ]] && LLM_MODEL="$ANTHROPIC_MODEL"
    [[ -n "$ANTHROPIC_API_KEY" ]] && LLM_API_KEY="$ANTHROPIC_API_KEY"
    [[ -n "$ANTHROPIC_BASE_URL" ]] && LLM_URL="$ANTHROPIC_BASE_URL"
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

create_project_config() {
    local pd="$1"; local cf="$pd/.autodev-harness/config.json"
    mkdir -p "$pd/.autodev-harness"
    cat > "$cf" <<'CONF'
{
  "model": "MODEL",
  "api_key": "KEY",
  "url": "URL"
}
CONF
    sed -i.bak "s/MODEL/${LLM_MODEL}/g; s/KEY/${LLM_API_KEY}/g; s/URL/${LLM_URL}/g" "$cf"
    rm -f "$cf.bak"
    echo "Config saved to: $cf"
}