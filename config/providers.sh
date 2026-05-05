#!/bin/bash
declare -A PROVIDERS=(
    ["anthropic"]="Anthropic|https://api.anthropic.com|claude-3-5-sonnet-4-7|ANTHROPIC_API_KEY"
    ["openai"]="OpenAI|https://api.openai.com/v1|gpt-4o|OPENAI_API_KEY"
    ["ollama"]="Ollama|http://localhost:11434|llama3|OLLAMA_API_KEY"
    ["groq"]="Groq|https://api.groq.com/openai/v1|llama-3.1-70b-versatile|GROQ_API_KEY"
    ["deepseek"]="DeepSeek|https://api.deepseek.com|deepseek-chat|DEEPSEEK_API_KEY"
)
get_provider_info() {
    local provider="$1"; local field="$2"
    local info="${PROVIDERS[$provider]}"
    [[ -z "$info" ]] && return 1
    case "$field" in
        name) echo "$info" | cut -d'|' -f1 ;;
        url) echo "$info" | cut -d'|' -f2 ;;
        model) echo "$info" | cut -d'|' -f3 ;;
        key_env) echo "$info" | cut -d'|' -f4 ;;
    esac
}
list_providers() {
    echo "Supported LLM Providers:"
    for provider in "${!PROVIDERS[@]}"; do
        local name=$(get_provider_info "$provider" "name")
        local model=$(get_provider_info "$provider" "model")
        echo "  - $provider ($name, default model: $model)"
    done
}
