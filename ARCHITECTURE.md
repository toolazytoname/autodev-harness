# AutoDevHarness 架构设计

## 概述

AutoDevHarness 是一个基于 GAN（生成对抗网络）思想的全自动 AI 开发系统。它通过分离"代码生成"和"质量评审"两个角色，解决了 AI Agent 高估自己代码质量的核心问题。

## 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      AutoDevHarness 主控制器                      │
│                                                                 │
│  ┌──────────┐                                                    │
│  │ Planner  │────▶ 生成产品规格 + 任务分解                        │
│  └────┬─────┘                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    任务队列引擎                              │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │   │
│  │  │ Task 1  │─▶│ Task 2  │─▶│ Task N  │  (DAG依赖管理)    │   │
│  │  └─────────┘  └────┬────┘  └─────────┘                  │   │
│  └───────────────────┼────────────────────────────────────┘   │
│                      │                                           │
│      ┌───────────────┼───────────────┐                          │
│      ▼               ▼               ▼                          │
│ ┌──────────┐  ┌──────────┐  ┌──────────────┐                  │
│ │ Generator │◀─▶│Evaluator │  │Quality Gates │                  │
│ │  生成器   │   │  评审官   │  │   质量门禁   │                  │
│ └──────────┘  └──────────┘  └──────────────┘                  │
│      │               │               │                          │
│      │               │               ├── lint (阻塞)            │
│      │               │               ├── build (阻塞)           │
│      │               │               ├── test (阻塞)            │
│      │               │               ├── e2e (条件阻塞)          │
│      │               │               └── security (非阻塞)       │
│      │               │                                           │
│      │               └── GAN 评分: Design/Originality/           │
│      │                            Craft/Functionality             │
│      │                                                       │
│      └── 循环直到评分 >= 7.0 或达到最大迭代                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 三代理系统

### 1. Planner（规划师）

**职责**: 将用户的简短需求扩展为完整的产品规格

**输入**: 用户 brief（如"Build a todo app"）

**输出**:
- `SPEC.md` - 完整产品规格
- `config/eval-rubric.md` - 评审标准
- `state/task-queue.json` - 任务分解

**核心逻辑**:
```bash
# 调用方式
claude -p --model opus "扩展 brief 为详细规格..."
```

### 2. Generator（生成器）

**职责**: 根据任务队列实现功能

**输入**:
- 当前任务详情
- SPEC.md 规格
- 上一轮评审反馈

**输出**:
- 实现的代码
- 通过质量门禁

**核心流程**:
1. 读取任务描述
2. 实现功能代码
3. 运行质量门禁
4. 提交代码
5. 更新任务状态

### 3. Evaluator（评审官）

**职责**: 严格评审代码质量，输出分数和反馈

**评分维度**:
| 维度 | 权重 | 说明 |
|------|------|------|
| Design Quality | 30% | 视觉一致性、配色、布局 |
| Originality | 20% | 原创性 vs 模板代码 |
| Craft | 30% | 工艺细节、动画、交互 |
| Functionality | 20% | 功能完整性 |

**通过标准**: 总分 >= 7.0/10.0

## 任务队列引擎

### DAG 依赖管理

任务之间可能有依赖关系，使用有向无环图（DAG）管理：

```json
{
  "tasks": [
    { "id": "task-001", "name": "项目初始化", "deps": [] },
    { "id": "task-002", "name": "实现认证", "deps": ["task-001"] },
    { "id": "task-003", "name": "实现Dashboard", "deps": ["task-002"] }
  ],
  "dag": {
    "layers": [
      ["task-001"],
      ["task-002"],
      ["task-003"]
    ]
  }
}
```

### 任务状态流转

```
pending ──▶ in-progress ──▶ completed
              │
              └──▶ failed ──▶ pending (可重试)
```

### 执行顺序

1. 获取所有依赖已完成的 pending 任务
2. 按优先级排序
3. 执行任务
4. 更新状态
5. 重复直到队列为空

## 质量门禁

### 门禁类型

| 门禁 | 命令 | 阻塞 | 说明 |
|------|------|------|------|
| lint | `npm run lint` | ✓ | 代码风格检查 |
| build | `npm run build` | ✓ | 生产构建 |
| test | `npm test` | ✓ | 单元测试 |
| e2e | Playwright | 条件 | E2E 测试 |
| security | `npm audit` | ✗ | 安全扫描 |

### 执行策略

```bash
# 并行执行非阻塞门禁
npm audit &

# 串行执行阻塞门禁
npm run lint && npm run build && npm test
```

### 失败处理

- **阻塞门禁失败**: 停止当前迭代，要求 Generator 修复
- **非阻塞门禁失败**: 记录警告，继续执行

## GAN 反馈循环

### 迭代流程

```
┌─────────────────────────────────────────────┐
│            GAN Loop (最多15次)                │
├─────────────────────────────────────────────┤
│                                              │
│  ┌─────────┐      ┌─────────┐               │
│  │Generator │◀───▶│Evaluator │               │
│  └────┬────┘      └────┬────┘               │
│       │                │                      │
│       ▼                ▼                      │
│   实现代码 ───────▶ 测试评分                   │
│                        │                      │
│                        ▼                      │
│               ┌──────────────┐               │
│               │ 分数 >= 7.0?  │               │
│               └──────┬───────┘               │
│                      │                        │
│           ┌─────────┴─────────┐              │
│           ▼                   ▼              │
│         YES                  NO              │
│          │                    │                │
│          ▼                    ▼              │
│       退出循环          继续下一轮迭代          │
│                                              │
└─────────────────────────────────────────────┘
```

### 分数提取

从评审反馈中提取分数：
```bash
extract_score() {
  grep -oP '(?<=\*\*TOTAL\*\*.*\*\*)[0-9]+\.[0-9]+' feedback.md
}
```

###  plateau 检测

连续3轮分数增长 <= 0.2 时，判定为 plateau，停止迭代：

```bash
if [ $PLATEAU_COUNT -ge 2 ]; then
  warn "Score plateau detected. Stopping."
  break
fi
```

## 状态持久化

### 检查点机制

```bash
# 保存检查点
./scripts/checkpoint.sh save "before-feature-x"

# 恢复检查点
./scripts/checkpoint.sh restore cp-20240502-143000
```

### 状态文件

| 文件 | 内容 |
|------|------|
| `state/task-queue.json` | 任务队列和进度 |
| `state/progress.json` | 执行统计 |
| `state/checkpoints/` | 检查点存档 |
| `feedback/gan/summary.json` | GAN 评估结果 |

## 配置系统

### 主配置 (harness.config.json)

```json
{
  "brief": "用户需求",
  "projectType": "fullstack|frontend|api|library",
  "models": {
    "planner": "opus",
    "generator": "opus"
  },
  "harness": {
    "maxIterations": 15,
    "passThreshold": 7.0
  },
  "devServer": {
    "port": 3000,
    "command": "npm run dev"
  }
}
```

### 环境变量覆盖

```bash
GAN_MAX_ITERATIONS=20 \
GAN_PASS_THRESHOLD=7.5 \
GAN_DEV_SERVER_PORT=5173 \
./scripts/gan-loop.sh
```

## Web UI 架构

### 技术栈

- React 18 + TypeScript
- Vite 构建
- TailwindCSS 样式
- Zustand 状态管理
- Socket.IO 实时通信

### 核心组件

```
App
├── TaskProgress       # 任务进度条
├── GanScore          # GAN 评分展示
├── QualityGates      # 门禁状态
├── ControlPanel      # 控制按钮
└── LogViewer        # 日志查看
```

### 数据流

```
用户操作 → Zustand Store → React 组件更新
                ↑
         WebSocket 推送
                ↑
    Shell 脚本执行 → 状态文件更新
```

## GitHub Actions 集成

### 工作流触发链

```
Push/PR
    ↓
ci.yml (质量门禁)
    ↓
pr-review.yml (AI 审查)
    ↓
代码合并
    ↓
autodev.yml (定时/手动 GAN)
    ↓
deploy.yml (预览部署)
    ↓
生产部署
```

### Secrets 配置

| Secret | 用途 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API 调用 |
| `SLACK_WEBHOOK` | Slack 通知 |
| `DINGTALK_WEBHOOK` | 钉钉通知 |
| `VERCEL_TOKEN` | Vercel 部署 |

## 扩展点

### 自定义质量门禁

在 `run-quality-gates.sh` 中添加：

```bash
run_custom_gate() {
  local gate=$1
  case $gate in
    my-gate) my-custom-check ;;
  esac
}
```

### 自定义 Agent

在 `agents/` 目录添加新的 agent 文件：

```bash
agents/
├── planner.md
├── generator.md
├── evaluator.md
├── reviewer.md      # 新增
└── tester.md       # 新增
```

### 自定义评分标准

修改 `config/eval-rubric.md`：

```markdown
## 新评分维度
[Penalize]: ...
[Reward]: ...
```

## 性能考量

### API 调用优化

- 使用 Haiku 做轻量级检查
- Opus 仅用于关键决策
- 批量处理减少 API 次数

### 上下文管理

- 检查点压缩历史日志
- 只保留最新 N 轮反馈
- 增量更新状态文件

### 并行执行

- 非阻塞门禁并行
- 独立任务可并行（需 DAG 支持）
