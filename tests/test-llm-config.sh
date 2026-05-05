#!/bin/bash
# Test LLM config priority resolution
echo "=== Testing LLM Config ==="
cd "$(dirname "$0")/.."
source config/llm-config.sh
load_llm_config
echo "Provider: ${LLM_PROVIDER}"
echo "URL: ${LLM_URL}"
echo "Model: ${LLM_MODEL}"
echo "API Key: ${LLM_API_KEY:+***set***}"
echo "=== Test Complete ==="
