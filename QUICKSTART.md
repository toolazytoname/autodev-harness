# 快速入门指南

本文档帮助你在 5 分钟内启动 AutoDevHarness。

## 前置要求

- Node.js 18+
- Claude Code CLI
- jq

### 检查安装

```bash
# 检查 Node.js
node --version  # 应该 >= 18.0.0

# 检查 Claude Code
claude --version

# 检查 jq
jq --version
```

### 安装缺失工具

```bash
# 安装 Claude Code
npm install -g @anthropic-ai/claude-code

# 安装 jq (macOS)
brew install jq

# 安装 jq (Linux)
sudo apt install jq
```

---

## 5 分钟快速启动

### Step 1: 进入目录

```bash
cd /Users/lazy/Code/crack/test/autodev-harness
```

### Step 2: 初始化项目

```bash
./scripts/init-project.sh fullstack my-first-app
cd my-first-app
```

这会创建一个 Next.js 项目，包含：
- TypeScript
- Tailwind CSS
- ESLint
- Jest (测试)

### Step 3: 启动全自动开发

```bash
../autodev-harness/scripts/autodev-harness.sh "Build a simple todo app"
```

你会看到：

```
═══════════════════════════════════════════════
  AutoDevHarness - 全自动开发
═══════════════════════════════════════════════

[PLANNER] 生成产品规格...
[PLANNER] 生成任务队列 (12 个任务)
[PLANNER] 完成 ✓

[GAN LOOP] 迭代 1/15
[GENERATOR] 实现任务 1/12: 项目初始化
[GATES] lint ✓, build ✓, test ✓
[EVALUATOR] 评分: 5.1/10 - 需要改进

[GENERATOR] 实现任务 2/12: 任务创建
...
```

### Step 4: 查看进度

另开一个终端：

```bash
cd /Users/lazy/Code/crack/test/my-first-app
../autodev-harness/scripts/dashboard.sh
```

---

## 常用命令速查

### 日常使用

| 命令 | 说明 |
|------|------|
| `./autodev-harness.sh "需求"` | 一键启动 |
| `./dashboard.sh` | 查看进度 |
| `./watch.sh 5` | 实时监控 |

### 开发调试

| 命令 | 说明 |
|------|------|
| `./task-queue-engine.sh status` | 查看任务列表 |
| `./task-queue-engine.sh run --task task-003` | 运行特定任务 |
| `./run-quality-gates.sh build` | 只运行构建 |

### 项目管理

| 命令 | 说明 |
|------|------|
| `./checkpoint.sh save` | 保存快照 |
| `./checkpoint.sh list` | 查看快照 |
| `./checkpoint.sh restore <id>` | 恢复快照 |
| `./init-project.sh fullstack <name>` | 初始化项目 |

---

## 常见场景

### 场景 1: 开发 Web 应用

```bash
./init-project.sh fullstack my-web-app
cd my-web-app
./autodev-harness.sh "Build a blog platform with comments"
```

### 场景 2: 开发 API

```bash
./init-project.sh api my-api
cd my-api
./autodev-harness.sh "Build a REST API for user management"
```

### 场景 3: 开发组件库

```bash
./init-project.sh library my-ui
cd my-ui
./autodev-harness.sh "Build a React component library with 20 components"
```

### 场景 4: 添加新功能

```bash
cd my-existing-app
./autodev-harness.sh "Add dark mode support to the app"
```

---

## 调整参数

### 高质量要求

```bash
./autodev-harness.sh "Build an app" --threshold 8.0 --iterations 20
```

### 快速原型（跳过 GAN）

```bash
./autodev-harness.sh "Build a prototype" --skip-gan
```

### 使用 Sonnet 模型（更快更便宜）

```bash
./autodev-harness.sh "Build an app" --model sonnet
```

---

## 查看结果

### CLI 仪表盘

```bash
./dashboard.sh
```

### HTML 仪表盘

```bash
./generate-html-dashboard.sh
open dashboard.html
```

### Web UI

```bash
cd ../ui
npm install
npm run dev
# 访问 http://localhost:5173
```

---

## 下一步

- 详细文档：查看 [README.md](README.md)
- Agent 系统：查看 [AGENTS.md](AGENTS.md)
- CI/CD 配置：查看 [.github/ENVIRONMENT_SETUP.md](.github/ENVIRONMENT_SETUP.md)

---

## 遇到问题？

### Claude 未授权

```bash
# 登录 Claude
claude auth login

# 或设置 API Key
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 脚本没有执行权限

```bash
chmod +x scripts/*.sh
```

### 项目初始化失败

```bash
# 检查 Node.js
node --version

# 手动初始化
npm init -y
npm install next react react-dom
npm install -D typescript @types/react @types/node
```

---

**准备好开始了吗？** 回到 [README.md](README.md) 查看完整文档。
