#!/bin/bash
# Bash 3.2 compatible provider config (no associative arrays)

get_provider_info() {
    local provider="$1"; local field="$2"
    local info=""

    case "$provider" in
        anthropic) info="Anthropic|https://api.anthropic.com|claude-3-5-sonnet-4-7|ANTHROPIC_API_KEY" ;;
        openai) info="OpenAI|https://api.openai.com/v1|gpt-4o|OPENAI_API_KEY" ;;
        ollama) info="Ollama|http://localhost:11434|llama3|OLLAMA_API_KEY" ;;
        groq) info="Groq|https://api.groq.com/openai/v1|llama-3.1-70b-versatile|GROQ_API_KEY" ;;
        deepseek) info="DeepSeek|https://api.deepseek.com|deepseek-chat|DEEPSEEK_API_KEY" ;;
        *) return 1 ;;
    esac

    case "$field" in
        name) echo "$info" | cut -d'|' -f1 ;;
        url) echo "$info" | cut -d'|' -f2 ;;
        model) echo "$info" | cut -d'|' -f3 ;;
        key_env) echo "$info" | cut -d'|' -f4 ;;
    esac
}

list_providers() {
    echo "Supported LLM Providers:"
    echo "  - anthropic (Anthropic, default model: claude-3-5-sonnet-4-7)"
    echo "  - openai (OpenAI, default model: gpt-4o)"
    echo "  - ollama (Ollama, default model: llama3)"
    echo "  - groq (Groq, default model: llama-3.1-70b-versatile)"
    echo "  - deepseek (DeepSeek, default model: deepseek-chat)"
}
