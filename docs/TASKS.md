# AutoDevHarness v2 — 任务清单（TASKS）

> 执行者说明：本清单由 Fable 5（架构档）产出，供便宜模型按序接棒执行。
> - 每个任务自带验收标准，**验收不过不算完成**。
> - 遇到与 `docs/MASTER-PLAN.md` 冲突 → 以 MASTER-PLAN 为准；遇到没覆盖的决策 → 停下问人，不要自行发挥。
> - 动手前先读：`docs/MASTER-PLAN.md` 全文 + `docs/REVIEW.md` 第二、五节 + 本任务的"坑点"。
> - 每完成一个任务：跑通验收 → conventional commit（`feat:`/`fix:`）→ 勾选本文件对应条目。
> - 依赖关系已排好，按编号顺序做即可；标 ⚡ 的可与前一个并行。

---

## M0 止血 + 骨架（先让地基可信）

### T01 修复现有 bash 的 4 个 CRITICAL bug
**内容**：按 `docs/REVIEW.md` 第二节修复 `lib/files.sh` 的 `get_next_task`（空格容错的 JSON 解析，改用 `jq`）、
`complete_task`（用 `jq` 精确改 status 字段而非 sed 全局替换）、`lib/claude.sh` 的 `is_score_passed`
（去掉错误的命令替换）、分数提取（改 `grep -oE` 兼容 BSD）。
**为什么还要修 bash**：Python 重写期间 bash 是唯一能用的版本；且修复过程就是给 Python 版写行为基准。
**验收**：`tests/` 下新增 bats 或 shell 断言脚本，构造一个 pretty-JSON task queue，证明取任务/完任务/判分全对；macOS 上全绿。
**坑点**：`jq` 已是依赖（claude.sh 里用过）；`complete_task` 改完要验证 dependencies 数组不被误伤。

### T02 Python 包骨架 + artifacts 模块
**内容**：建 `harness/` 包（pyproject.toml，Python 3.11+，零重依赖：pydantic + pyyaml + pytest 起步）。
实现 `artifacts.py`：编号产物（000-brief…006-ui-spec）读写、`state/workflow-state.json` 读写、断点恢复语义
（对齐现有 bash 的 `--continue`/`--phase`）。所有数据结构 pydantic model，不可变风格（frozen=True）。
**验收**：pytest 覆盖 artifacts ≥ 90%；能读取现有 bash 跑出来的旧 state 文件（向后兼容）。

### T03 ⚡ CLI adapter 层（claude 先行）
**内容**：`adapters/base.py` 定义接口 `run(prompt: str, model: str, cwd: Path, timeout: int) -> AgentResult`
（AgentResult 含 stdout / exit_code / usage tokens / duration）。实现 `adapters/claude.py`：
subprocess 调 `claude -p --model X --output-format json`（json 格式能拿到 usage 和干净的 result 字段）。
指数退避重试（429/5xx，最多 3 次），限流时按 MASTER-PLAN §5.1 降 fallback。
留 `adapters/opencode.py`、`adapters/codex.py` 的 stub（NotImplementedError + TODO 注释写清接口约定）。
**验收**：mock subprocess 的单测覆盖重试/降级/超时路径；真实 smoke test 一条（调 haiku 说 hi，标记 slow）。
**坑点**：`--output-format json` 的返回结构要先真跑一次确认字段名，不要凭记忆写解析。

### T04 ModelRouter + config/models.yaml
**内容**：按 MASTER-PLAN §4 落地 `config/models.yaml` 和 `router.py`：
`resolve(stage: str) -> ModelSpec(model, base_url?, tier, fallback)`。环境变量可覆盖任意档位。
附 token 预算计数器：累加各 AgentResult.usage，按 tier 分桶，暴露 `spent_by_tier()`，超阈值告警（MASTER-PLAN §5.7）。
**验收**：单测覆盖解析/覆盖/降级/预算告警；`python -m harness config` 能打印当前路由表。

---

## M1 内层质量闭环（价值最大的部分）

### T05 score card schema + reviewers 装配
**内容**：`score_card.py`：pydantic schema（iter/reviewer/score 0-1/blockers[]/suggestions[]/evidence），
落盘到 `score-cards/task-{id}/iter-{n}-{reviewer}.json`。schema 校验失败按 MASTER-PLAN §5.2 自动重问。
`reviewers.py` + `config/reviewers.yaml`：task 类型 → reviewer 组合
（默认 correctness+test+boundary；UI += a11y+visual；API += security；参照 harness skill 的组合表）。
新增 reviewer prompts 到 `agents/reviewers/*.md`——**优先移植 ECC 池里的现成定义**
（`~/.claude/plugins/cache/everything-claude-code/.../agents/` 下的 code-reviewer/security-reviewer 等，
拷贝改造为纯 markdown prompt，去掉 YAML frontmatter 依赖），每个 prompt 末尾统一要求输出 score card JSON。
**验收**：单测：非法 JSON 重试、组合装配正确；5 个 reviewer prompt 就位（correctness/test/boundary/security/visual）。

### T06 inner_loop.py：generate → N reviewers → gate
**内容**：MASTER-PLAN §2 内层闭环完整实现：
- generator 在 git worktree（`task/{id}` 分支）里跑，用 worker 档模型；
- reviewer 并行（asyncio 或 ThreadPool，各自独立 adapter 进程），只读 worktree diff + spec，各写各的 score card；
- gate：全部 score≥0.8 且 blockers 空且 test reviewer 的 evidence 是真实命令输出 → merge + commit（附 score card 摘要）；
- fail：blockers+suggestions 拼进下一轮 generator prompt（**不含 reviewer transcript**），iter++，MAX_ITER=5；
- 撞顶：状态置 blocked，产出升级报告（全部 score card + diff 摘要）等 architect 仲裁。
**验收**：MASTER-PLAN §6 第 3 条——埋 bug 的集成测试：给一个故意有 off-by-one 的 spec 样例，
证明 test reviewer 拦截 → 回灌 → 第二轮通过。用 mock adapter 跑（不花真 token），另留一个真实 slow 测试。
**坑点**：worktree 清理（gate 失败到撞顶时保留现场供仲裁）；并行 reviewer 的超时互不影响。

### T07 pipeline.py：外层五阶段接管
**内容**：把 research/plan/ui_design/tasks/develop 五阶段从 bash 移到 `pipeline.py`，
接 router + adapter + artifacts。plan/UI 的人工反馈环保留（input() 交互 + 非 TTY 时读环境变量自动通过）。
develop 阶段逐 task 调 inner_loop。CLI：`python -m harness [--test|--iterate] [--phase X] [--continue] [DIR] -- "描述"`，
参数语义与 bash 版对齐。`autodev-harness.sh` 改为转发到 Python（保留旧路径 30 天后删）。
**验收**：MASTER-PLAN §6 第 1 条 smoke：`--test` 模式全流程跑通一个 TODO app（用真模型，走 worker 档）。

---

## M2 六大痛点的专项落地

### T08 品味注入：skills-bundle + ui-design prompt 重写  ✅ 2026-07-06
**内容**：把三件套（high-end-visual-design / frontend-design / design-taste-frontend）从
`~/.claude/skills/` 拷进 `skills-bundle/`（自包含，注明来源和日期）。重写 `agents/ui-design.md`：
固定拼入三件套精华 + 按 brief 关键词条件挂载风格模块（minimalist-ui/industrial-brutalist-ui/gpt-taste，也入 bundle）。
4 版本改为 4 美学方向（如：编辑极简 / 高端动效 / 玩具感圆润 / 数据密集工业风），方向由 plan 内容自动选 4 个。
去掉 ui.sh 里写死的宠物/儿童关键词逻辑（那是上一个项目的残留），改为从 brief/plan 提取主题词。
**验收**：同一个 brief 生成 4 版 HTML，人工抽查无 Inter 字体/紫渐变/generic shadow 等 slop 特征
（可写脚本 grep HTML 检查禁用项，作为自动验收）。

### T08b 可选·opendesign 子集抽取（参考合约 + 营销创意 + 高级动效）— 建议放到下一个 checkpoint
**内容**：从 `https://github.com/nexu-io/open-design`（skill + HTML 模板 monorepo，
head 700+ skill，绝大多数与 taste-skill 重叠）抽 4 类有价值的新增内容，
入 `skills-bundle/opendesign/`：

- `reference-design-contract` —— "参考图转 DESIGN.md"，对 ui-design.md 的 D
  节方向选择形成补充
- `design-brief` —— I-Lang 协议化 brief 解析，可喂 plan 阶段做"无歧义 brief"
- `emil-design-eng` / `emilkowalski-motion` / `impeccable-design-polish` —
  高级动效/收尾做工素材
- `competitive-ads-extractor` / `ad-creative` —— 营销与竞品素材，给 researcher
  用

**为什么不在 T08 一并落地**：T08 验收已经落在 4 美学方向 + 158 测试基线 + 自动
slop 校验，再扩 bundle 会冲掉验收成果；opendesign 是 monorepo（含 figma 插件、
apps、packages），需要单独写 import 脚本而不像 taste-skill 那样直接拷贝
SKILL.md。

**验收**：`skills-bundle/opendesign/` 落地 ≥ 4 个 SKILL.md，每条带 LICENSE
+ SOURCES.md 来源；`agents/ui-design.md` 的 STYLE MODULE 候选列表添加
opendesign 子集；`agents/researcher.md` 接入 `competitive-ads-extractor` 与
`ad-creative` 的提示词指引；全量测试仍 ≥ 158 passed。

### T09 visual reviewer：截图对照评审
**内容**：给 inner_loop 的 UI 任务接 browser-use（或 Playwright）执行器：起 dev server →
按 006-ui-spec 里的页面清单逐页截图 → 图 + spec 喂给 visual reviewer 打分（多模态），
截图存 `score-cards/task-{id}/screenshots/` 作 evidence。
**验收**：对一个故意配色跑偏的页面，visual reviewer 给出 blocker；对合格页面放行。
**坑点**：dev server 启动等待要健壮（探活轮询而非 sleep）；无头环境字体渲染差异不作为 blocker 依据。

### T10 ⚡ researcher 重写：强制复用决策表
**内容**：按 MASTER-PLAN P4 重写 `agents/researcher.md`：`gh search repos/code` + 包注册表 + deep-research skill，
产出含"复用决策表"（候选|成熟度|覆盖%|fork/port/wrap/弃|理由）。pipeline 校验 001-research 里存在该表才放行进 plan。
planner prompt 同步加一条：凡决策为 fork/wrap 的候选，plan 必须体现"在其上迭代"。
**验收**：用"做一个 markdown 笔记 app"跑 research，决策表非空且含真实 repo（抽查 URL 有效）。

### T11 ⚡ taskgen 升级：acceptance 字段 + E2E 场景
**内容**：task schema 加 `acceptance: []`（可执行验收标准，含用户流程步骤）和 `kind: ui|api|logic|infra`
（决定 reviewer 组合）。taskgen prompt 要求每个 task 必须有可被 browser-use/测试命令执行的 acceptance。
**验收**：schema 校验通过；test reviewer 能直接把 acceptance 转成执行步骤。

### T12 Linear 同步
**内容**：`linear_sync.py`：经 Linear MCP（优先 streamlinear，省 token）在 tasks 阶段建 project+issues（含依赖），
inner_loop 状态机同步（In Progress/Done+score card 摘要评论/Blocked+blockers 评论）。
无 `LINEAR_API_KEY` 时静默降级为本地模式（MASTER-PLAN P6）。进度链接在 pipeline 启动时打印。
**验收**：mock MCP 的单测 + 真实 sandbox 验证一次状态流转；降级路径有测试。

### T13 移动端/小程序测试适配（按 MASTER-PLAN P5 的分层）
**内容**：reviewers.yaml 加 `platform: web|miniprogram|mobile` 维度：
web→browser-use；mobile→Maestro flow（生成 YAML flow 模板 + 本地模拟器说明文档）；
miniprogram→macOS 上 miniprogram-automator 的接入脚本 + 业务逻辑纯函数化的 generator 约束
（写进 generator prompt：wx API 必须隔离在薄壳层）。
**验收**：文档 + 模板就位；miniprogram 的 automator 脚本在本机（macOS）对官方示例小程序跑通一次。
**注**：此任务偏调研+模板性质，允许交付"能跑的最小示例+文档"而非完整封装。

---

## M3 收尾

### T14 文档 + 自身质量达标
**内容**：重写 README（v2 架构、快速开始、路由表说明、Linear 接入、跨端测试矩阵）；
`docs/ADAPTER.md` 写清 opencode/codex 接入约定。全包测试覆盖 ≥80%，macOS+Linux CI（GitHub Actions）。
**验收**：MASTER-PLAN §6 全部 6 条勾完；CI 绿。

### T15 用真实项目做一次端到端验证
**内容**：选一个真实小项目（建议就用用户下一个想做的 idea），全流程走一遍，
记录：总 token 消耗按 tier 分布、architect 占比、gate 拦截次数、人工介入次数。产出 `docs/CASE-STUDY.md`。
**验收**：architect 档 token 占比 < 10%；人工介入 ≤ 3 次（brief/plan/UI/最终验收之外为 0）。

---

## 给执行模型的最后叮嘱

1. 不要合并任务、不要跳序、不要"顺手重构"清单外的东西。
2. 每个任务开工前把它拆成 TodoWrite 步骤，完成后跑验收再 commit。
3. 三次尝试解决不了同一个报错 → 停，把上下文写进 issue 问人，不要换路绕过验收。
4. Fable/Opus 档的调用只允许出现在 router 配置指定的位置；开发调试期一律用 worker 档模型自测。
