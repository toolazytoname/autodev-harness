# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → Develop** workflow.

## Features

- **Three Modes**: new / iterate / test
- **Research Phase**: Competitive analysis with best practices
- **Interactive Plan**: User confirmation before development
- **Resumable**: Continue from checkpoint
- **ECC Integration**: Uses everything-claude-code commands

## Prerequisites

Before running, set up your LLM configuration via environment variables:

```bash
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
export ANTHROPIC_MODEL="MiniMax-M2.7"
```

These are the only required configurations. All other settings are optional.

## Input Your Project Brief

Create a `000-brief.md` file in your project directory:

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
# 1. 设置环境变量
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
export ANTHROPIC_MODEL="MiniMax-M2.7"

# 2. 进入项目目录并运行
cd /path/to/project
/path/to/autodev-harness.sh

# 其他模式
./autodev-harness.sh --test      # 测试模式 (3次迭代)
./autodev-harness.sh --iterate   # 迭代模式 (10次迭代)
./autodev-harness.sh -c          # 从检查点继续
```

## LLM Configuration

Priority: CLI args > Environment variables > Defaults

```bash
# CLI options (会覆盖环境变量)
./autodev-harness.sh --model MiniMax-M2.7 --llm-key sk-xxx --llm-url https://api.minimaxi.com/anthropic
```

| Variable | Default | Description |
|----------|---------|-------------|
| ANTHROPIC_API_KEY | (none) | API key for LLM provider |
| ANTHROPIC_BASE_URL | https://api.minimaxi.com/anthropic | API endpoint |
| ANTHROPIC_MODEL | MiniMax-M2.7 | Model name |

## Workflow

```
000-brief.md               ← User input (required)
    ↓
001-research-report.md     ← Research (competitive analysis)
    ↓
002-plan.md               ← Plan (user confirms)
    ↓
003-task-queue.json       ← Tasks (auto-generated)
    ↓
Development Loop (Generator → Evaluator)
```

## Modes

| Mode | Iterations | Threshold | Use Case |
|------|------------|-----------|----------|
| `new` (default) | 15 | 7.0 | Full project |
| `iterate` | 10 | 7.0 | Bug fix / feature |
| `test` | 3 | 5.0 | Quick validation |

## Project Structure

```
autodev-harness/
├── autodev-harness.sh     # Main entry
├── agents/                # Agent prompts
├── lib/                   # Libraries
├── config/                # Configuration
└── tests/                 # Test suite
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