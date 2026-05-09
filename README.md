# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → UI Design → Tasks → Develop** workflow.

## Features

- **Five Phases**: Research → Plan → UI Design (iterative) → Tasks → Develop
- **Iterative UI Design**: Preview HTML, provide feedback, regenerate until satisfied
- **Infrastructure First**: Collect Supabase config before development
- **Visual UI Preview**: HTML mockup with Tailwind CSS for design verification
- **Test Coverage Gate**: Enforce >= 80% coverage
- **Three Modes**: new / iterate / test
- **Resumable**: Continue from checkpoint

## Prerequisites

Set up LLM configuration via environment variables:

```bash
export AUTODEV_API_KEY="your-api-key"
export AUTODEV_BASE_URL="https://api.minimaxi.com/anthropic"
export AUTODEV_MODEL="MiniMax-M2.7"
```

If not set, falls back to Claude Code's variables:
- `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`

## Quick Start

```bash
# 1. 设置环境变量
export AUTODEV_API_KEY="your-api-key"
export AUTODEV_BASE_URL="https://api.minimaxi.com/anthropic"
export AUTODEV_MODEL="MiniMax-M2.7"

# 2. 进入项目目录，用 -- 分隔描述内容（自动创建 000-brief.md）
cd /path/to/project
./autodev-harness.sh -- "我要开发一个宠物养成系统"

# 或者已有 000-brief.md，直接运行
cd /path/to/project
./autodev-harness.sh

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

Priority: CLI args > AUTODEV_* env > ANTHROPIC_* env > Defaults

| Variable | Default |
|----------|---------|
| AUTODEV_API_KEY | (required) |
| AUTODEV_BASE_URL | https://api.minimaxi.com/anthropic |
| AUTODEV_MODEL | MiniMax-M2.7 |

## Workflow

```
PROJECT_DESCRIPTION  ← User input (via CLI -- or 000-brief.md)
    ↓
000-brief.md               ← Created automatically from CLI
    ↓
001-research-report.md     ← Research (competitive analysis)
    ↓
002-plan.md               ← Plan (user confirms)
    ↓
006-ui-spec.md            ← UI Design (iterative)
preview/index.html        ← HTML Mockup for browser preview
    ↓
003-task-queue.json       ← Tasks (auto-generated)
    ↓
Development Loop (Generator → Evaluator)
```

### UI Design Phase (Iterative)

After the initial design is generated, you can iterate:

```
    ↓
┌─────────────────────────────┐
│  Preview: file://.../index.html
│  Spec: 006-ui-spec.md
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  修改意见? (直接回车接受)    │ ← User provides feedback
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  N → Agent regenerates      │ ← Agent incorporates feedback
│      (Plan + Previous + Feedback)
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  Up to 5 iterations         │
└─────────────────────────────┘
    ↓ (once satisfied or max iterations)
    ↓
003-task-queue.json
```

### Infrastructure Configuration

Before planning, you will be prompted for infrastructure details:

```
1) Supabase Project URL
2) Supabase Anon Key (客户端使用)
3) Supabase Service Role Key (建表/执行SQL)
```

Config is saved to `.infrastructure.conf` (gitignored).

## Evaluation Criteria

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Design Quality | 25% | Visual consistency, colors, layout |
| Originality | 15% | Original vs template code |
| Craftsmanship | 25% | Animations, interaction details |
| Feature Completeness | 15% | Feature completeness |
| Test Coverage | 20% | Unit test coverage >= 80% |

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
│   ├── researcher.md
│   ├── planner.md
│   ├── ui-design.md       # UI design agent with iterative feedback
│   ├── taskgen.md
│   ├── generator.md
│   └── evaluator.md
├── lib/                   # Libraries
│   ├── ui.sh              # UI + infra config collection
│   ├── claude.sh          # Claude API interaction
│   ├── files.sh           # File operations
│   └── state.sh           # State management
├── config/
│   ├── harness.config.sh  # Configuration
│   └── llm-config.sh      # LLM settings
└── README.md
```

## License

MIT
