# AutoDevHarness v2 — 架构总纲（MASTER PLAN）

> 本文档由 Fable 5 产出，是后续所有开发工作的**总纲**。执行者（便宜模型）遇到与本文冲突的
> 实现细节，以本文为准；遇到本文没覆盖的决策，停下来在 Linear issue 里留言问人，不要自行发挥。
>
> 配套文档：`docs/REVIEW.md`（现状诊断）、`docs/TASKS.md`（任务清单，按序执行）。

## 0. 一句话目标

**"说一句话，转身离开，回来验收一个高质量结果"** —— 人只出现在三个点：
① 开始时描述需求 + 确认 plan/UI 稿；② 中途（可选）看 Linear 上的进度；③ 结束时验收。
其余全部由 harness 闭环消化，哪怕执行模型是便宜/较笨的模型，质量由**结构**保证而不是由**模型智商**保证。

## 1. 核心设计原则（不可违背）

1. **质量来自闭环，不来自模型。** 生成者与评审者必须是独立进程（独立 context）；gate 不过不 commit；
   失败原因结构化落盘（score card）回灌下一轮。永远不让模型"自己说自己测过了"。
2. **贵模型出图纸，便宜模型搬砖。** Fable/Opus 级只出现在：plan、架构决策、坑点预判、最终验收仲裁。
   generate/测试/修复/文档一律路由到便宜档。路由表是配置，不是代码。
3. **上下文外置到文件系统。** 一切阶段产物落盘为编号文档（spec-kit 风格），任何一轮 agent 挂了/换了，
   靠读文件恢复，不靠会话记忆。
4. **先找轮子，再造轮子。** research 阶段强制产出"复用决策表"（找到什么库/repo、为什么用/不用），
   没有这张表不允许进 plan。
5. **CLI 无关。** 编排器通过 adapter 调 `claude -p` / `opencode run` / `codex exec`，
   agent prompt 是纯 markdown，不依赖任何 CLI 的私有功能。MVP 先做 claude adapter，接口留好。
6. **人是裁判不是操作员。** 除了 plan/UI 确认点和 gate 撞顶升级，中途不 ping 人。

## 2. 总体架构

```
┌─ 外层 Pipeline（阶段编排，Python: harness/pipeline.py）────────────────┐
│                                                                        │
│  brief → research → plan ⇄人 → ui_design ⇄人 → tasks → ┌──────────┐   │
│  (Haiku)  (Haiku+    (Fable/    (Sonnet×4版+   (Haiku)  │ develop  │   │
│           deep-      Opus 出    品味注入)               │ 每个task │   │
│           research)  总纲)                              │ 走内层▼  │   │
│                                                         └──────────┘   │
│  产物: 000-brief / 001-research(+复用决策表) / 002-plan /              │
│        003-tasks.json / 006-ui-spec + preview/                         │
└────────────────────────────────────────────────────────────────────────┘
                                │ 每个 task
┌─ 内层 Quality Loop（harness/inner_loop.py，蓝本=harness skill）────────┐
│                                                                        │
│   spec → Generate(便宜模型, 独立进程, worktree)                        │
│        → N 个 Reviewer 并行(各自独立进程, 互不可见)                    │
│            correctness / test / boundary [/ a11y / visual(截图)]      │
│        → Gate: 全部 score≥0.8 && blockers空 && 测试真跑全绿           │
│        → pass: commit + score card 归档 + Linear issue → Done         │
│        → fail: blockers 回灌, iter++ (MAX_ITER=5)                     │
│        → 撞顶: 升级问人(Fable 仲裁), Linear issue → Blocked           │
└────────────────────────────────────────────────────────────────────────┘
         │                        │                       │
   ┌───────────┐          ┌──────────────┐        ┌──────────────┐
   │ ModelRouter│          │ CLI Adapter  │        │ Linear Sync  │
   │ 配置表路由 │          │ claude/open- │        │ MCP, task↔   │
   │ (YAML)    │          │ code/codex   │        │ issue 双向   │
   └───────────┘          └──────────────┘        └──────────────┘
```

目录规划（新增，bash 保留为薄入口直到 Python 对齐后删除）：

```
autodev-harness/
├── harness/                  # Python 包（核心，新建）
│   ├── pipeline.py           # 外层阶段编排 + 断点续跑
│   ├── inner_loop.py         # 内层 generate→review→gate 闭环
│   ├── router.py             # 模型路由（读 config/models.yaml）
│   ├── adapters/             # claude.py / opencode.py / codex.py（统一 run(prompt, model, cwd) 接口）
│   ├── reviewers.py          # reviewer 池装配（按 task 类型选组合）
│   ├── score_card.py         # score card schema + 校验 + 归档
│   ├── linear_sync.py        # Linear MCP 双向同步
│   └── artifacts.py          # 编号产物读写 + 状态管理
├── agents/                   # prompt 全部外置（现有 6 个升级 + 新增 reviewer 若干）
├── config/
│   ├── models.yaml           # ★ 路由表（见 §4）
│   └── reviewers.yaml        # task 类型 → reviewer 组合
├── skills-bundle/            # 从 ~/.claude/skills 拷贝进仓库的品味注入素材（自包含，不依赖本机）
├── docs/                     # REVIEW / MASTER-PLAN / TASKS
└── autodev-harness.sh        # 薄入口，转发到 python -m harness
```

## 3. 六大痛点的解法（P1–P6）

### P1 UI 审美：品味注入 + 视觉评审双保险
- **注入侧**：ui-design agent 的 prompt 固定拼入品味基座三件套
  （high-end-visual-design + frontend-design + design-taste-frontend，拷进 `skills-bundle/` 自包含），
  按 brief 关键词条件挂载风格模块（minimalist / brutalist / gpt-taste 动效）。
  4 版本对比保留，但 4 版改为"4 种美学方向"而非"4 个参考源"（参考源可以合并喂给全部版本）。
- **评审侧**：内层 loop 对 UI 任务强制加 `visual` reviewer——用 browser-use/Playwright 截图，
  与 006-ui-spec 对照打分；截图不像 spec 就是 blocker。**这一步是"默认产出就漂亮"的硬保证**，
  注入只能提均值，评审才能砍长尾。
- 人工确认点保留：opendesign 出的稿子可以直接放进 `preview/` 作为 v0 参考版一起对比。

### P2 模型路由：配置表 + 三档分级（不引入网关）
- MVP 不上 litellm/RouteLLM 网关（YAGNI），用 `config/models.yaml` 静态路由表 + adapter 传 `--model` 即可。
  之后若要跨供应商负载均衡再挂 litellm，router.py 接口不变。
- 三档：`architect`（Fable/Opus：plan、坑点预判、gate 撞顶仲裁、最终验收）/
  `worker`（MiniMax/Haiku/GLM 等便宜档：generate、修复、文档、taskgen、research 摘要）/
  `reviewer`（Sonnet 档：评审需要判断力但不需要顶级架构能力）。
- **省钱的关键洞察**：评审比生成便宜得多（读 diff 打分 vs 写全量代码），所以"便宜模型生成 + 中档模型多路评审"
  比"贵模型直接生成"总成本低且质量可控。架构档全程输出总量应 < 全项目 token 的 10%。

### P3 交付质量：六板斧（对应 REVIEW.md 第三节 6 条差距）
独立评审、上下文隔离、JSON score card、blockers 回灌、gate-then-commit、MAX_ITER=5 撞顶升级。
外加一条：**test reviewer 必须真的执行命令**（npm test / playwright run），evidence 字段要求贴运行输出路径，
"我认为测试会通过"不是 evidence。E2E 用 browser-use 跑真实用户流程（点击/输入/断言），
验收标准写在 task 的 `acceptance` 字段里（taskgen 阶段就生成）。

### P4 巨人肩膀：research 阶段强制"复用决策表"
researcher prompt 重写：先 `gh search repos/code` + 包注册表检查 + deep-research，
产出固定含一张表：`候选(repo/库) | star/成熟度 | 覆盖需求% | 决策(fork/port/wrap/弃) | 理由`。
plan 阶段读这张表，凡决策为 fork/wrap 的，plan 必须体现"在其上迭代"而不是重写。

### P5 跨端测试：诚实分层
- **Web**：browser-use / Playwright，Linux headless 无障碍 → 内层 visual+e2e reviewer 直接可用。
- **移动 native**：Maestro（YAML flow，iOS/Android），需要模拟器/真机，Linux 可跑 Android 模拟器。
- **微信小程序**：**Linux headless 无现成方案**（官方 automator 强依赖开发者工具，仅 macOS/Windows）。
  策略：a) 开发期把业务逻辑层做成可单测的纯函数（不依赖 wx API）；b) UI 层在 macOS 上用
  miniprogram-automator 跑（本机就是 macOS，可行）；c) 若必须 Linux CI，把页面编译 H5 后用 Playwright 近似回归。
  不要试图在 Linux 上 Wine 微信开发者工具，成本不值。

### P6 进度外露：Linear 单一事实源
- tasks 阶段生成 task-queue 的同时经 MCP 建 Linear project + issues（含依赖关系）；
- 内层 loop 状态机同步：开始→In Progress，gate 过→Done（评论附 score card 摘要），撞顶→Blocked（评论附 blockers）；
- 进度链接 = Linear project URL，甘特/时间线用 Linear 自带视图，**不自建 dashboard**（YAGNI，决策已定）。
- 降级路径：无 Linear API key 时自动降级为本地 `003-tasks.json` + 终端表格，功能不阻塞。

## 4. 路由表初稿（config/models.yaml）

```yaml
tiers:
  architect:  { model: claude-fable-5,  fallback: claude-opus-4-8 }
  reviewer:   { model: claude-sonnet-5, fallback: claude-haiku-4-5-20251001 }
  worker:     { model: MiniMax-M2.7,    base_url: https://api.minimaxi.com/anthropic,
                fallback: claude-haiku-4-5-20251001 }
assignments:
  research: worker          # + deep-research skill
  plan: architect           # 唯一必须用贵模型的生成环节
  ui_design: reviewer       # 品味主要靠注入的 skill 文本，Sonnet 档足够
  taskgen: worker
  generate: worker
  review.correctness: reviewer
  review.test: worker       # 跑命令为主，判断为辅
  review.boundary: reviewer
  review.visual: reviewer
  review.a11y: worker
  escalation: architect     # gate 撞顶仲裁
  final_acceptance: architect
```

## 5. 坑点预判（执行者必读）

1. **429 限流是常态**（本总纲的调研 agent 就被 Fable 限流打断过）：adapter 必须做指数退避重试 +
   限流时自动降 fallback 档；architect 档任务失败不允许静默降级，要升级问人。
2. **JSON 输出不可信**：所有结构化产物（tasks、score card）必须 schema 校验，失败自动带错误重问同一模型，
   最多 2 次，再失败换 fallback 模型。绝不用正则从 markdown 里抠数据（现有 bash 就死在这）。
3. **`claude -p` 的输出会混杂非 JSON 前后缀**：解析前先做 fence/前后缀剥离（现有 extract_html 的教训）。
4. **并行 reviewer 的写冲突**：reviewer 只读 + 各自写自己的 score card 文件，绝不共写一个文件。
   generator 修改代码用 git worktree 隔离（每个 task 一个分支，gate 过了才 merge）。
5. **不要让 generator 看到 reviewer 的完整 transcript**，只喂 score card（防"讨好评审"，harness skill 硬规则#3）。
6. **macOS/Linux 双兼容**：禁用 `sed -i ''`、`grep -P` 等平台限定用法——这也是重写用 Python 的原因之一。
7. **成本护栏**：pipeline 级 token 预算计数（各 adapter 返回 usage 累加），超预算 80% 时告警、100% 时暂停问人。
8. **凭据**：`.infrastructure.conf` / API keys 不进 git；score card / Linear 评论里禁止出现 key 明文。

## 6. 验收标准（本工程自身的 Definition of Done）

- [ ] `python -m harness --test -- "做一个 TODO web app"` 能全流程跑完：从 brief 到 gate 通过的 commit，中途只在 plan/UI 停下问人
- [ ] 全程 architect 档 token 占比 < 10%（usage 统计输出）
- [ ] 故意在 generate 里埋一个 bug，test reviewer 能拦下且 blockers 回灌后第二轮修复
- [ ] Linear 上能看到 project/issues 状态流转（或无 key 时优雅降级）
- [ ] 在 claude CLI 之外，adapter 接口能通过 mock 证明 opencode/codex 可插入
- [ ] harness 包自身单测覆盖 ≥ 80%（router/score_card/artifacts 为重点）
