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
cd /path/to/project          # 进入你的项目目录
/path/to/autodev-harness.sh  # 运行 harness（使用当前目录）

# 或者传入项目路径
./autodev-harness.sh /path/to/project
./autodev-harness.sh --test # 测试模式
./autodev-harness.sh --iterate  # 迭代模式
./autodev-harness.sh -c     # 从检查点继续
```

## LLM Configuration

Priority: CLI args > Environment > Config file > Defaults

```bash
# CLI options
./autodev-harness.sh --model claude-3-5-sonnet-4-7 --llm-key sk-xxx --llm-url https://api.anthropic.com

# Environment variables
export LLM_MODEL=claude-3-5-sonnet-4-7
export LLM_API_KEY=xxx
export LLM_URL=https://api.anthropic.com

# Config file (~/.autodev-harness/config.json)
{
  "model": "claude-3-5-sonnet-4-7",
  "api_key": "${LLM_API_KEY}",
  "url": "https://api.anthropic.com"
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

## Default LLM Settings

| Model | URL |
|-------|-----|
| claude-3-5-sonnet-4-7 | https://api.anthropic.com |

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
