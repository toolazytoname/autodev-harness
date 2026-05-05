# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → Develop** workflow.

## Features

- **Three Modes**: new / iterate / test
- **Research Phase**: Competitive analysis with best practices
- **Interactive Plan**: User confirmation before development
- **Resumable**: Continue from checkpoint
- **ECC Integration**: Uses everything-claude-code commands

## Prerequisites

Set up LLM configuration via environment variables:

```bash
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
export ANTHROPIC_MODEL="MiniMax-M2.7"
```

## Quick Start

```bash
# 1. 设置环境变量
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
export ANTHROPIC_MODEL="MiniMax-M2.7"

# 2. 进入项目目录，用 -- 分隔描述内容（自动创建 000-brief.md）
cd /path/to/project
/path/to/autodev-harness.sh -- "我要开发一个宠物养成系统"

# 或者已有 000-brief.md，直接运行
cd /path/to/project
/path/to/autodev-harness.sh

# 其他模式
./autodev-harness.sh --test -- "快速验证任务"
./autodev-harness.sh --iterate -- "修复登录bug"
./autodev-harness.sh -c        # 从检查点继续
```

## Usage

```bash
./autodev-harness.sh [OPTIONS] [PROJECT_DIR] -- PROJECT_DESCRIPTION

OPTIONS:
    --new           New project mode (default)
    --iterate       Iterate on existing project (bug fix / feature)
    --test          Test mode (quick validation)
    -c, --continue  Continue from checkpoint
    --status        Show project status
    --restart       Restart from beginning

LLM OPTIONS:
    --llm-key KEY   Override API key
    --llm-url URL   Override API URL
    --model MODEL   Override model name
```

## LLM Configuration

Priority: CLI args > Environment variables > Defaults

| Variable | Default |
|----------|---------|
| ANTHROPIC_API_KEY | (required) |
| ANTHROPIC_BASE_URL | https://api.minimaxi.com/anthropic |
| ANTHROPIC_MODEL | MiniMax-M2.7 |

## Workflow

```
PROJECT_DESCRIPTION  ← User input (via CLI -- or 000-brief.md)
    ↓
000-brief.md               ← Created automatically from CLI
001-research-report.md     ← Research (competitive analysis)
002-plan.md               ← Plan (user confirms)
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