#!/bin/bash
# LLM Configuration - Priority-based config loader
# Note: API keys are handled by Claude Code, not by this harness

PROVIDERS_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/providers.sh"
source "$PROVIDERS_SH"

LLM_PROVIDER=""; LLM_URL=""; LLM_MODEL=""

load_config_file() {
    local cf="$1"
    if [[ ! -f "$cf" ]]; then
        return 0
    fi
    LLM_PROVIDER=$(grep -m1 "\"provider\"" "$cf" 2>/dev/null | sed "s/.*: *\"\([^\"]*\)\".*/\1/")
    LLM_URL=$(grep -m1 "\"url\"" "$cf" 2>/dev/null | sed "s/.*: *\"\([^\"]*\)\".*/\1/")
    LLM_MODEL=$(grep -m1 "\"model\"" "$cf" 2>/dev/null | sed "s/.*: *\"\([^\"]*\)\".*/\1/")
    return 0
}

load_config_env() {
    [[ -n "$LLM_PROVIDER" ]] || LLM_PROVIDER="${PROVIDER:-}"
    [[ -n "$LLM_URL" ]] || LLM_URL="${LLM_URL:-}"
    [[ -n "$LLM_MODEL" ]] || LLM_MODEL="${LLM_MODEL:-}"
}

set_defaults() {
    [[ -z "$LLM_PROVIDER" ]] && LLM_PROVIDER="anthropic"
    [[ -z "$LLM_URL" ]] && LLM_URL=$(get_provider_info "$LLM_PROVIDER" "url")
    [[ -z "$LLM_MODEL" ]] && LLM_MODEL=$(get_provider_info "$LLM_PROVIDER" "model")
}

load_llm_config() {
    load_config_file ".autodev-harness/config.json"
    load_config_file "$HOME/.autodev-harness/config.json"
    load_config_env
    set_defaults
}

apply_cli_config() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --provider) LLM_PROVIDER="$2"; shift 2 ;;
            --llm-url) LLM_URL="$2"; shift 2 ;;
            --model) LLM_MODEL="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    [[ -z "$LLM_URL" ]] && LLM_URL=$(get_provider_info "$LLM_PROVIDER" "url")
}

show_llm_config() {
    echo "LLM Configuration:"
    echo "  Provider: ${LLM_PROVIDER:-not set}"
    echo "  URL: ${LLM_URL:-not set}"
    echo "  Model: ${LLM_MODEL:-not set}"
}

create_project_config() {
    local pd="$1"; local cf="$pd/.autodev-harness/config.json"
    mkdir -p "$pd/.autodev-harness"
    cat > "$cf" <<EOF
{
  "provider": "${LLM_PROVIDER:-anthropic}",
  "url": "${LLM_URL:-}",
  "model": "${LLM_MODEL:-}"
}
EOF
    echo "Config saved to: $cf"
}
