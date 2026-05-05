# AutoDevHarness

AI-Powered Development Framework with **Research → Plan → Develop** workflow.

## Features

- **Three Modes**: new / iterate / test
- **Research Phase**: Competitive analysis with best practices
- **Interactive Plan**: User confirmation before development
- **Resumable**: Continue from checkpoint
- **Multi-Provider LLM**: Anthropic, OpenAI, Ollama, Groq, DeepSeek
- **ECC Integration**: Uses everything-claude-code commands

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


### 工作流程

```
1. 规划阶段 (Planner)
   └── 用户输入 brief → 自动生成详细规格 + 任务列表

2. 开发阶段 (Generator + Evaluator)
   ├── Generator 实现功能
   ├── 质量门禁检查 (lint/build/test)
   ├── Evaluator 评审 (GAN 评分)
   └── 循环直到通过

3. 完成阶段
   ├── 生成构建报告
   ├── 代码提交
   └── 通知 (可选)
```

---

## 核心组件

### 1. 脚本 (scripts/)

| 脚本 | 功能 | 使用场景 |
|------|------|----------|
| `autodev-harness.sh` | **主入口**，一键启动全自动开发 | 日常使用 |
| `task-queue-engine.sh` | **任务队列管理**，DAG 依赖编排 | 管理任务 |
| `gan-loop.sh` | **GAN 反馈循环**，生成-评审迭代 | 质量把关 |
| `run-quality-gates.sh` | **质量门禁**，lint/build/test/e2e/security | 质量检查 |
| `dashboard.sh` | **CLI 仪表盘**，终端内查看进度 | 快速查看 |
| `watch.sh` | **实时监控**，自动刷新仪表盘 | 持续观察 |
| `generate-html-dashboard.sh` | **HTML 仪表盘**，浏览器查看 | 可视化 |
| `checkpoint.sh` | **检查点**，保存/恢复状态 | 中断恢复 |
| `init-project.sh` | **项目初始化**，快速创建项目 | 新项目 |
| `dev-server.sh` | **开发服务器**，启动/停止服务 | 开发调试 |
| `code-review.sh` | **代码审查**，静态分析 | PR 检查 |
| `security-review.sh` | **安全审查**，漏洞扫描 | 安全检查 |
| `metrics-collector.sh` | **指标收集**，汇总数据 | 统计分析 |

### 2. Agent 定义 (agents/)

| Agent | 角色 | 说明 |
|-------|------|------|
| `planner.md` | 规划师 | 将 brief 扩展为详细规格 + 任务分解 |
| `generator.md` | 开发者 | 根据规格实现功能 |
| `evaluator.md` | 评审官 | 严格评审，输出分数和问题 |

### 3. 配置文件 (config/)

| 文件 | 说明 |
|------|------|
| `harness.config.json` | 主配置：模型、阈值、端口等 |
| `eval-rubric.md` | 评审标准：评分细则 |

### 4. 状态文件 (state/)

| 文件 | 说明 |
|------|------|
| `task-queue.json` | 任务队列状态 |
| `progress.json` | 进度统计 |
| `checkpoints/` | 检查点存档 |

### 5. 输出目录

| 目录 | 说明 |
|------|------|
| `quality/gates/` | 各质量门禁执行结果 |
| `feedback/gan/` | GAN 评审反馈 |
| `logs/` | 执行日志 |
| `build-report.md` | 构建报告 |

---

## 使用指南

### 基本用法

```bash
# 启动全自动开发（最简单方式）
./autodev-harness/scripts/autodev-harness.sh "Build a Kanban board app"

# 指定参数
./autodev-harness/scripts/autodev-harness.sh \
  "Build a recipe sharing platform" \
  --type fullstack \
  --iterations 10 \
  --threshold 7.5
```

### 选项说明

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--type` | 项目类型：`fullstack`, `frontend`, `api`, `library` | `fullstack` |
| `--model` | AI 模型：`opus`, `sonnet` | `opus` |
| `--iterations` | 最大 GAN 迭代次数 | `15` |
| `--threshold` | 通过阈值 (1-10) | `7.0` |
| `--skip-planner` | 跳过规划阶段 | `false` |
| `--skip-gan` | 跳过 GAN 评审 | `false` |
| `--continue` | 从上次中断处继续 | `false` |

### 分步执行

```bash
# 1. 初始化项目
./scripts/init-project.sh fullstack my-app
cd my-app

# 2. 单独运行规划
./scripts/autodev-harness.sh "Build a dashboard" --skip-gan

# 3. 查看任务队列
./scripts/task-queue-engine.sh status

# 4. 手动运行 GAN 评估
./scripts/gan-loop.sh

# 5. 查看结果
./scripts/dashboard.sh
```

### 单独使用质量门禁

```bash
# 运行所有门禁
./scripts/run-quality-gates.sh all

# 只运行关键门禁（lint + build + test）
./scripts/run-quality-gates.sh critical

# 只运行构建
./scripts/run-quality-gates.sh build

# 指定超时（秒）
GAN_TIMEOUT=60 ./scripts/run-quality-gates.sh test
```

### 检查点与恢复

```bash
# 保存当前状态
./scripts/checkpoint.sh save "before-adding-auth"

# 查看可用检查点
./scripts/checkpoint.sh list

# 恢复到某个检查点
./scripts/checkpoint.sh restore cp-20240502-143000
```

---

## 监控仪表盘

### CLI 仪表盘

```bash
./scripts/dashboard.sh
```

输出示例：
```
╔══════════════════════════════════════════════════════════════╗
║            AutoDevHarness Dashboard                            ║
╚══════════════════════════════════════════════════════════════╝

━━━ Tasks ━━━
[████████████████████░░░░░░░░░░░░] 67%
  ✓ Completed:   8
  ⟳ In Progress: 2
  ○ Pending:     4

━━━ GAN Loop ━━━
  Score:       7.2/10.0 (threshold: 7.0)
  Status:      ✓ PASS

━━━ Quality Gates ━━━
  ✓ lint    ✓ build    ✓ test    ○ e2e    ✓ security

━━─ Time ━━━
  Started: 2024-05-02T10:00:00+08:00
```

### 实时监控

```bash
# 每5秒自动刷新
./scripts/watch.sh 5

# 每10秒自动刷新
./scripts/watch.sh 10
```

### HTML 仪表盘

```bash
# 生成 HTML 仪表盘
./scripts/generate-html-dashboard.sh

# 在浏览器中打开
open autodev-harness/dashboard.html

# 可以设置定时刷新（默认30秒）
```

### Web UI

```bash
cd autodev-harness/ui
npm install
npm run dev
# 访问 http://localhost:5173
```

---

## GAN 评分系统

### 评分指标

| 指标 | 权重 | 说明 |
|------|------|------|
| **Design Quality** (设计质量) | 30% | 视觉一致性、配色、布局 |
| **Originality** (原创性) | 20% | 是否是模板代码 vs 原创设计 |
| **Craft** (工艺) | 30% | 排版、间距、动画、交互细节 |
| **Functionality** (功能性) | 20% | 所有功能是否正常工作 |

### 评分标准

| 分数 | 含义 |
|------|------|
| 1-3 | 损坏、丢人、不会给任何人看 |
| 4-5 | 能用但明显是 AI 生成的 |
| 6 | 凑合但不惊艳 |
| 7 | **合格** - 初级开发者的不错作品 |
| 8 | 很好 - 专业级质量 |
| 9 | 优秀 - 高级开发者水平 |
| 10 | 卓越 - 可以作为真实产品发布 |

### 通过标准

- **默认阈值**: 7.0 / 10.0
- 低于 7.0 会继续迭代直到通过或达到最大迭代次数

### 避免 AI 敷衍 (AI Slop)

评审官会特别扣分以下模式：
- 通用渐变背景 (#667eea → #764ba2)
- 库存占位图
- 默认 UI 库主题未定制
- 模板化布局

---

## 质量门禁

### 门禁列表

| 门禁 | 命令 | 是否阻塞 | 说明 |
|------|------|----------|------|
| **lint** | `npm run lint` | ✓ 阻塞 | 代码风格检查 |
| **build** | `npm run build` | ✓ 阻塞 | 生产构建 |
| **test** | `npm test` | ✓ 阻塞 | 单元测试 |
| **e2e** | Playwright | 条件阻塞 | 端到端测试 |
| **security** | `npm audit` | 非阻塞 | 安全漏洞扫描 |

### 阻塞规则

- **阻塞**: 失败则停止开发流程，必须修复
- **非阻塞**: 失败只记录，不阻止继续

---

## CI/CD 集成

### GitHub Actions 工作流

| 工作流 | 触发条件 | 功能 |
|--------|----------|------|
| `ci.yml` | Push/PR | 质量门禁检查 |
| `pr-review.yml` | PR | AI 代码审查 + 安全扫描 |
| `gan-evaluation.yml` | 手动 | 完整 GAN 评估 |
| `autodev.yml` | Push/定时/手动 | 全自动开发 CI |
| `deploy.yml` | Push/手动 | 部署到环境 |
| `notifications.yml` | 完成 | 通知推送 |

### 部署流程

```
PR 创建
    ↓
ci.yml (质量门禁)
    ↓
pr-review.yml (AI 审查)
    ↓
代码合并到 main
    ↓
autodev.yml (GAN 评估)
    ↓
deploy.yml (预览部署)
    ↓
GAN 评分 >= 7.0？
    ↓
deploy.yml (生产部署)
```

### 配置步骤

1. 复制工作流到项目：
   ```bash
   cp -r autodev-harness/.github /your-project/
   ```

2. 在 GitHub 仓库设置中添加 Secret：
   - `ANTHROPIC_API_KEY` (必需)

3. 可选 Secrets：
   - `SLACK_WEBHOOK` - Slack 通知
   - `DINGTALK_WEBHOOK` - 钉钉通知
   - `VERCEL_TOKEN` - Vercel 部署

详见 [.github/ENVIRONMENT_SETUP.md](.github/ENVIRONMENT_SETUP.md)

---

## 常见问题

### Q: 如何调整 GAN 评分阈值？

```bash
./scripts/autodev-harness.sh "Build an app" --threshold 8.0
```

### Q: 如何跳过 GAN 评审直接开发？

```bash
./scripts/autodev-harness.sh "Build an app" --skip-gan
```

### Q: 如何继续中断的开发？

```bash
./scripts/autodev-harness.sh --continue
```

### Q: 费用大概多少？

基于 Anthropic 官方定价（参考）：
- 一次完整开发（10-15个任务）约 **$50-200**
- 主要开销在 GAN 评审迭代

### Q: 支持其他 AI 模型吗？

目前使用 Claude Opus 4.6，可通过环境变量配置：
```bash
MODEL=opus ./scripts/autodev-harness.sh "Build an app"
```

### Q: 能否集成到现有项目？

可以，只需复制 `autodev-harness/` 目录到项目根目录即可：
```bash
cp -r autodev-harness/ /your-existing-project/
cd /your-existing-project
./autodev-harness/scripts/autodev-harness.sh "Add new feature"
```

---

## 目录结构

```
autodev-harness/
├── README.md                    # 本文件
├── SPEC.md                     # 产品规格（自动生成）
├── build-report.md             # 构建报告（自动生成）
│
├── scripts/                    # 脚本目录
│   ├── autodev-harness.sh      # ⭐ 主入口
│   ├── task-queue-engine.sh    # 任务队列
│   ├── gan-loop.sh             # GAN 循环
│   ├── run-quality-gates.sh    # 质量门禁
│   ├── dashboard.sh            # CLI 仪表盘
│   ├── watch.sh                # 实时监控
│   ├── generate-html-dashboard.sh # HTML 仪表盘
│   ├── checkpoint.sh           # 检查点
│   ├── init-project.sh         # 项目初始化
│   ├── dev-server.sh           # 开发服务器
│   ├── code-review.sh          # 代码审查
│   ├── security-review.sh      # 安全审查
│   └── metrics-collector.sh     # 指标收集
│
├── agents/                     # Agent 定义
│   ├── planner.md               # 规划师
│   ├── generator.md             # 开发者
│   └── evaluator.md             # 评审官
│
├── config/                     # 配置文件
│   ├── harness.config.json     # 主配置
│   └── eval-rubric.md          # 评审标准
│
├── state/                      # 状态文件
│   ├── task-queue.json          # 任务队列
│   ├── checkpoints/            # 检查点存档
│   └── metrics/                # 指标数据
│
├── quality/                    # 质量结果
│   └── gates/                  # 门禁结果
│       ├── lint/
│       ├── build/
│       ├── test/
│       ├── e2e/
│       └── security/
│
├── feedback/                   # 反馈文件
│   ├── gan/                    # GAN 评审
│   │   ├── summary.json
│   │   └── feedback-*.md
│   └── reviews/                # 代码审查
│
├── logs/                       # 执行日志
│
├── .github/                    # GitHub Actions
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── pr-review.yml
│   │   ├── gan-evaluation.yml
│   │   ├── autodev.yml
│   │   ├── deploy.yml
│   │   └── notifications.yml
│   ├── README.md
│   └── ENVIRONMENT_SETUP.md
│
└── ui/                        # Web UI (可选)
    ├── src/
    │   ├── components/
    │   ├── hooks/
    │   └── ...
    └── package.json
```

---

## 参考资料

- [Anthropic: Harness Design for Long-Running Applications](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [GAN-Style Harness Skill](https://github.com/everything-claude-code/everything-claude-code)
- [Auto Coding Agent Demo](https://github.com/SamuelQZQ/auto-coding-agent-demo)

---

## 许可证

MIT License
