# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → UI Design (iterative) → Tasks → Develop** workflow.

## Features

- **Five Phases**: Research → Plan (iterative) → UI Design (iterative) → Tasks → Develop
- **Iterative Plan**: Preview plan, provide feedback, regenerate until satisfied
- **Iterative UI Design**: Preview HTML, provide feedback, regenerate until satisfied
- **Lazyweb Integration**: AI-powered UI design references from 257k+ real app screenshots
- **Infrastructure First**: Collect Supabase config before development
- **Visual UI Preview**: HTML mockup with Tailwind CSS for design verification
- **Test Coverage Gate**: Enforce >= 80% coverage
- **Three Modes**: new / iterate / test
- **Resumable**: Continue from checkpoint or jump to specific phase

## Prerequisites

```bash
export AUTODEV_API_KEY="your-api-key"
export AUTODEV_BASE_URL="https://api.minimaxi.com/anthropic"
export AUTODEV_MODEL="MiniMax-M2.7"
```

## Quick Start

```bash
cd /path/to/project
./autodev-harness.sh -- "我要开发一个宠物养成系统"

# 或者已有 000-brief.md
./autodev-harness.sh

# 其他模式
./autodev-harness.sh --test -- "快速验证任务"
./autodev-harness.sh --iterate -- "修复登录bug"
```

## 断点续学 / 阶段跳转

### 场景1：中断后继续

```bash
# 自动检测当前阶段，从断点继续
./autodev-harness.sh -c /path/to/project

# 等价于（显式指定）
./autodev-harness.sh --continue /path/to/project
```

### 场景2：跳转到指定阶段

```bash
# 跳过前面阶段，直接从 plan 开始
./autodev-harness.sh --phase plan /path/to/project

# 从 UI design 开始（需要已有 001-research-report.md 和 002-plan.md）
./autodev-harness.sh --phase ui_design /path/to/project

# 从 tasks 开始（需要已有 006-ui-spec.md）
./autodev-harness.sh --phase tasks /path/to/project
```

### 场景3：重新开始

```bash
# 删除状态文件，重新从头开始
./autodev-harness.sh --restart /path/to/project
```

## Usage

```bash
./autodev-harness.sh [OPTIONS] [PROJECT_DIR] -- PROJECT_DESCRIPTION

OPTIONS:
    --new              New project mode (default)
    --iterate          Iterate on existing project
    --test             Test mode (quick validation, 2-3 iterations)
    -c, --continue     Continue from last checkpoint (自动推断阶段)
    --phase PHASE      Jump to specific phase
    --status           Show project status
    --restart          Restart project (删除状态文件，重新开始)
    --max-iterations N Set max iterations (default: 15)

PHASES:
    research      Research agent (竞争分析)
    plan          Plan agent with user feedback (中文计划，可迭代)
    ui_design     UI design with user feedback (HTML预览，可迭代)
    tasks         Task generation
    develop       Generator → Evaluator loop

LLM OPTIONS:
    --llm-key KEY   Override API key
    --llm-url URL   Override API URL
    --model MODEL   Override model name
```

## Workflow

```
PROJECT_DESCRIPTION  ← User input (via CLI -- or 000-brief.md)
    ↓
000-brief.md               ← Created automatically from CLI
    ↓
001-research-report.md     ← Research (竞争分析)
    ↓
002-plan.md               ← Plan (iterative, user can provide feedback)
    ↓
006-ui-spec.md            ← UI Design (iterative, with Lazyweb refs)
preview/index.html        ← HTML Mockup for browser preview
    ↓
003-task-queue.json       ← Tasks (auto-generated)
    ↓
Development Loop (Generator → Evaluator)
```

### Plan Phase (Iterative)

After the initial plan is generated, you can iterate:

```
    ↓
┌─────────────────────────────┐
│  Plan preview (60 lines)    │
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  修改意见? (直接回车接受)    │ ← User provides feedback
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  N → Agent regenerates      │ ← Agent incorporates feedback
│      (Research + Previous + Feedback)
└─────────────────────────────┘
    ↓ (once satisfied or max iterations)
    ↓
UI Design
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
│  修改意见? (直接回车接受)    │
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│  N → Agent regenerates      │
│      (Plan + Previous + Feedback)
└─────────────────────────────┘
    ↓ (once satisfied or max iterations)
    ↓
Tasks
```

### Lazyweb Design References

During UI design phase, the system searches Lazyweb for similar app screenshots
and passes them to the UI design agent for grounded, real-world inspiration.

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
│   ├── planner.md         # Planner with iterative feedback
│   ├── ui-design.md       # UI design agent with Lazyweb refs
│   ├── taskgen.md
│   ├── generator.md
│   └── evaluator.md
├── lib/                   # Libraries
│   ├── ui.sh              # UI + infra config + Lazyweb search
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
