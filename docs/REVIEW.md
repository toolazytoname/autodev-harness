# AutoDevHarness 现状 Review（2026-07-05，by Fable 5）

> 结论先行：**架子方向是对的（分阶段 pipeline + 状态可恢复 + agent prompt 外置），但 develop 阶段的质量闭环
> 基本不可用，且有 4 个 CRITICAL 级 bug 会让开发循环静默失效。** 建议不再修补 bash，
> 核心编排层重写为 Python orchestrator（决策已定），bash 只留一层薄入口。

## 一、值得保留的设计

| 设计 | 为什么好 |
|------|----------|
| 五阶段 pipeline（research → plan → ui_design → tasks → develop） | 与 GitHub spec-kit（118k star）的 SDD 范式同构，方向正确 |
| Agent prompt 外置为 `agents/*.md` | 与编排解耦，换模型/换 CLI 不用改代码 |
| 状态文件 + `--continue` / `--phase` 断点续跑 | 长程任务的基本盘，保留语义，实现重写 |
| Plan / UI 阶段的人工迭代反馈环 | "人只当裁判"的正确落点：只在早期低成本阶段介入 |
| UI 4 版本对比选稿 | 便宜的多样性采样，保留并升级（见总纲 P1） |
| 产物按 `000-brief / 001-research / 002-plan...` 编号落盘 | 上下文外置到文件系统，不靠 LLM 记忆，正确 |

## 二、CRITICAL bug（当前 develop 循环实际上是坏的）

1. **`get_next_task` 永远返回空** — `lib/files.sh:68` 用 `grep -oE '"id":"[^"]*"'`（无空格），
   而 taskgen 输出的是 pretty JSON `"id": "task-001"`（带空格）。结果：develop 循环第一轮就
   报 "All tasks completed!" 直接退出。**这就是"感觉 harness 效果和直接开 auto mode 差不多"的直接原因之一——
   develop 阶段根本没在按任务队列跑。**
2. **`is_score_passed` 语法错误** — `lib/claude.sh:159` 写了 `$(echo "$score >= $PASS_THRESHOLD" | bc -l)`，
   命令替换会把 bc 输出的 `1`/`0` 当命令执行 → "command not found" → 永远判不过。
3. **`grep -oP` 在 macOS 上不存在** — `lib/claude.sh:148` 提取分数用 PCRE，BSD grep 不支持 `-P`，
   分数永远解析成 0。用正则从自由文本里抠分数这个思路本身就该废弃，换 JSON schema 结构化输出。
4. **`complete_task` 的 sed 会污染依赖字段** — `lib/files.sh:82` 全局替换 `"task-001"` → `"task-001_done"`，
   会把其他任务 `dependencies: ["task-001"]` 里的引用一起改掉，依赖图直接损坏。

其他问题（HIGH 级）：`sed -i ''` 是 macOS-only 写法（Linux 上报错）；`state.sh:34` 用 `source <(grep ...)` 
解析 JSON 是注入隐患；`save_feedback` 只写了一行 log，评分失败的 blockers 完全没有回灌给下一轮 generator——
**失败信息不落地，重跑等于裸跑**。

## 三、与目标形态的差距（对照 harness skill 五阶段闭环）

当前 develop 循环 vs 内层质量闭环应有的样子，差 6 件事：

| # | 差距 | 现状 | 应该 |
|---|------|------|------|
| 1 | 评审数量 | 单 evaluator | ≥4 个按维度并行（correctness / test / boundary / +UI: a11y+visual） |
| 2 | 上下文隔离 | 无保证，生成和评审可能同 session | 生成者与评审者必须独立进程/独立 context |
| 3 | 分数通道 | 正则抠 markdown | JSON score card（schema 校验 + 不合法自动重试） |
| 4 | 失败回灌 | 无 | blockers + suggestions 写入 `score-cards/iter-N.json`，喂回下一轮 |
| 5 | Gate 与 commit | 无 commit 步骤 | gate 全绿才 commit（附 score card），不绿不落 |
| 6 | 升级机制 | MAX_ITER=15 硬跑 | MAX_ITER=5，撞顶升级问人，附全部 score card |

## 四、六大痛点 → 差距映射

| 痛点 | 现状覆盖 | 缺口 |
|------|---------|------|
| 1 UI 审美 | 4 版本对比 + 4 源参考 | 参考源脆弱（关键词写死宠物/儿童）；未注入本机 3 个反-slop 设计 skill；无截图视觉评审 |
| 2 模型路由 | 单一 `LLM_MODEL` 全局一个模型 | 无按阶段/角色分级；Fable/Opus 干架构、Haiku/MiniMax 干体力活的路由表不存在 |
| 3 交付质量 | evaluator 自由文本打分（且已坏） | 见第三节 6 条；另外 E2E 是"让 agent 自己说测过了"，没有独立执行器真跑流程 |
| 4 巨人肩膀 | researcher 只写竞品分析文章 | 没有强制 `gh search` / 包注册表检查 / "复用决策表"产出 |
| 5 跨端测试 | 无 | web 可用 browser-use/Playwright；小程序 Linux headless 无现成方案（见总纲 P5 的诚实结论） |
| 6 进度外露 | 本地 log + state.json | 无对外链接。决策已定接 Linear（MCP），task-queue 双向同步 |

## 五、可复用的巨人肩膀（调研结论摘要）

本机现成（零成本接入）：
- **品味注入三件套**：`~/.claude/skills/{high-end-visual-design,frontend-design,design-taste-frontend}` —— 拼进 ui-design prompt
- **风格模块**：`minimalist-ui` / `industrial-brutalist-ui` / `gpt-taste` —— 按 brief 条件挂载
- **harness skill**（`~/.claude/skills/harness/SKILL.md`）—— 内层闭环的规范蓝本（五阶段 + 5 条硬规则 + score card schema）
- **orchestrate.py 参考实现**：`~/.claude/skill-packages/atelier/examples/harness-demo/orchestrate.py`（276 行，可抄骨架）
- **ECC reviewer 池**：`~/.claude/plugins/cache/everything-claude-code/.../agents/`（46 个现成 reviewer 定义）
- **browser-use skill**：有状态浏览器 CLI，直接当 E2E/visual 评审执行器
- **deep-research skill**：research 阶段的现成引擎

外部开源（按接入优先级）：
1. **github/spec-kit**（118k）— spec/plan/tasks 模板范式，直接借鉴产物结构
2. **BerriAI/litellm**（52k）— 如需网关级模型路由；MVP 阶段用配置表路由即可，不必先引入
3. **jerhadf/linear-mcp-server** / **streamlinear**（省 token 版）— Linear 接入
4. **mobile-dev-inc/Maestro**（14k）— 移动端 E2E 首选；Appium 生态在退，不碰
5. **zhnt/loushang**、**sd0xdev/sd0x-dev-flow** — 与目标最接近的两个参考实现，抄思路不抄代码
6. 小程序 Linux headless：**无现成方案**，官方 automator 强依赖微信开发者工具（仅 macOS/Windows）

## 六、总体判断

这个工程的价值不在现有 bash 代码（约 1500 行，其中核心循环已坏），而在于：
1. 已经验证的**阶段划分和人工介入点**设计；
2. 一套编号产物约定（可升级为 spec-kit 风格）；
3. 6 个 agent prompt 的雏形。

重写成本低（核心逻辑 < 1000 行 Python），修补成本高（bash 无类型、无测试、跨平台坑多，
且用户目标里的模型路由/并行评审/Linear 同步都不适合 bash 承载）。**结论：按 MASTER-PLAN.md 重建。**
