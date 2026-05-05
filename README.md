# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → Develop** workflow.

## Features

- **Three Modes**: new / iterate / test
- **Research Phase**: Competitive analysis with best practices
- **Interactive Plan**: User confirmation before development
- **Resumable**: Continue from checkpoint
- **Multi-Provider LLM**: Anthropic, OpenAI, Ollama, Groq, DeepSeek
- **ECC Integration**: Uses everything-claude-code commands

## Input Your Project Brief

Before running the harness, create a `000-brief.md` file in your project directory:

```bash
mkdir my-project && cd my-project
cat > 000-brief.md << 'EOF'
# 项目需求描述

[在这里描述你的项目需求]

示例：我要开发一个宠物养成系统，
用户可以领养虚拟宠物，喂养并看着它成长升级。
EOF
```

## Quick Start

```bash
# New project
./autodev-harness.sh /path/to/project

# Test mode (quick validation)
./autodev-harness.sh --test /path/to/test-project

# Iterate on existing project
./autodev-harness.sh --iterate /path/to/existing-project

# Continue from checkpoint
./autodev-harness.sh -c /path/to/project
```

## LLM Configuration

Priority: CLI args > Environment > Config file > Defaults

```bash
# CLI options
./autodev-harness.sh --provider openai --llm-key sk-xxx /path

# Environment variables
export ANTHROPIC_API_KEY=xxx
export OPENAI_API_KEY=xxx
export OLLAMA_API_KEY=xxx

# Config file (~/.autodev-harness/config.json)
{
  "provider": "anthropic",
  "url": "https://api.anthropic.com",
  "api_key": "${ANTHROPIC_API_KEY}",
  "model": "claude-3-5-sonnet-4-7"
}
```

## Workflow

```
000-brief.md               ← User input
    ↓
001-research-report.md     ← Research (competitive analysis)
    ↓
002-plan.md               ← Plan (user confirms)
    ↓
003-task-queue.json       ← Tasks (auto-generated)
004-spec.md               ← Specification
005-eval-rubric.md       ← Evaluation rubric
    ↓
Development Loop (Generator → Evaluator)
```

## Modes

| Mode | Iterations | Threshold | Use Case |
|------|------------|-----------|----------|
| `new` | 15 | 7.0 | Full project |
| `iterate` | 10 | 7.0 | Bug fix / feature |
| `test` | 3 | 5.0 | Quick validation |

## Supported LLM Providers

| Provider | URL | Default Model |
|----------|-----|--------------|
| anthropic | api.anthropic.com | claude-3-5-sonnet-4-7 |
| openai | api.openai.com/v1 | gpt-4o |
| ollama | localhost:11434 | llama3 |
| groq | api.groq.com | llama-3.1-70b |
| deepseek | api.deepseek.com | deepseek-chat |

## Project Structure

```
autodev-harness/
├── autodev-harness.sh     # Main entry
├── agents/                 # Agent prompts
├── lib/                    # Libraries
├── config/                 # LLM providers & config
└── tests/                  # Test suite
```

## License

MIT

---

## 参考资料

- [Anthropic: Harness Design for Long-Running Applications](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [GAN-Style Harness Skill](https://github.com/everything-claude-code/everything-claude-code)
- [Auto Coding Agent Demo](https://github.com/SamuelQZQ/auto-coding-agent-demo)

---

## 许可证

MIT License
