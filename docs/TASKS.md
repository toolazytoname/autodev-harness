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

### T08b 可选·opendesign 子集抽取（参考合约 + 营销创意 + 高级动效）  ✅ 2026-07-06
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
**完成记录**：落地 7 个 SKILL.md（reference-design-contract / design-brief /
emil-design-eng / emilkowalski-motion / impeccable-design-polish /
competitive-ads-extractor / ad-creative），顶层 Apache-2.0 LICENSE +
SOURCES.md；emil-design-eng 保留 sub-upstream MIT LICENSE；reference-design-contract
附带 example.html + references/checklist.md。`agents/ui-design.md` 新增
§E0 "Follow-up style modules (opendesign subset)"；`agents/researcher.md` §调研方法
新增第 4 步"marketing / paid-acquisition brief 时调用"。新增
`tests/test_opendesign_bundle.py` 29 用例，全量 316 passed / 2 skipped。

### T09 visual reviewer：截图对照评审  ✅ 2026-07-06
**内容**：给 inner_loop 的 UI 任务接 browser-use（或 Playwright）执行器：起 dev server →
按 006-ui-spec 里的页面清单逐页截图 → 图 + spec 喂给 visual reviewer 打分（多模态），
截图存 `score-cards/task-{id}/screenshots/` 作 evidence。
**验收**：对一个故意配色跑偏的页面，visual reviewer 给出 blocker；对合格页面放行。
**坑点**：dev server 启动等待要健壮（探活轮询而非 sleep）；无头环境字体渲染差异不作为 blocker 依据。

### T10 ✅ researcher 重写：强制复用决策表  ✅ 2026-07-06
**内容**：按 MASTER-PLAN P4 重写 `agents/researcher.md`：`gh search repos/code` + 包注册表 + deep-research skill，
产出含"复用决策表"（候选|成熟度|覆盖%|fork/port/wrap/弃|理由）。pipeline 校验 001-research 里存在该表才放行进 plan。
planner prompt 同步加一条：凡决策为 fork/wrap 的候选，plan 必须体现"在其上迭代"。
**验收**：用"做一个 markdown 笔记 app"跑 research，决策表非空且含真实 repo（抽查 URL 有效）。

### T11 ✅ taskgen 升级：acceptance 字段 + E2E 场景  ✅ 2026-07-06
**内容**：task schema 加 `acceptance: []`（可执行验收标准，含用户流程步骤）和 `kind: ui|api|logic|infra`
（决定 reviewer 组合）。taskgen prompt 要求每个 task 必须有可被 browser-use/测试命令执行的 acceptance。
**验收**：schema 校验通过；test reviewer 能直接把 acceptance 转成执行步骤。

### T12 ✅ Linear 同步  ✅ 2026-07-06
**内容**：`linear_sync.py`：经 Linear MCP（优先 streamlinear，省 token）在 tasks 阶段建 project+issues（含依赖），
inner_loop 状态机同步（In Progress/Done+score card 摘要评论/Blocked+blockers 评论）。
无 `LINEAR_API_KEY` 时静默降级为本地模式（MASTER-PLAN P6）。进度链接在 pipeline 启动时打印。
**验收**：mock MCP 的单测 + 真实 sandbox 验证一次状态流转；降级路径有测试。

### T13 ✅ 移动端/小程序测试适配（按 MASTER-PLAN P5 的分层）  ✅ 2026-07-06
**内容**：reviewers.yaml 加 `platform: web|miniprogram|mobile` 维度：
web→browser-use；mobile→Maestro flow（生成 YAML flow 模板 + 本地模拟器说明文档）；
miniprogram→macOS 上 miniprogram-automator 的接入脚本 + 业务逻辑纯函数化的 generator 约束
（写进 generator prompt：wx API 必须隔离在薄壳层）。
**验收**：文档 + 模板就位；miniprogram 的 automator 脚本在本机（macOS）对官方示例小程序跑通一次。
**注**：此任务偏调研+模板性质，允许交付"能跑的最小示例+文档"而非完整封装。

---

## M3 收尾

### T14 ✅ 文档 + 自身质量达标  ✅ 2026-07-06
**内容**：重写 README（v2 架构、快速开始、路由表说明、Linear 接入、跨端测试矩阵）；
`docs/ADAPTER.md` 写清 opencode/codex 接入约定。全包测试覆盖 ≥80%，macOS+Linux CI（GitHub Actions）。
**验收**：MASTER-PLAN §6 全部 6 条勾完；CI 绿。

### T15 ✅ 用真实项目做一次端到端验证  ✅ 2026-07-06
**内容**：选一个真实小项目（建议就用用户下一个想做的 idea），全流程走一遍，
记录：总 token 消耗按 tier 分布、architect 占比、gate 拦截次数、人工介入次数。产出 `docs/CASE-STUDY.md`。
**验收**：architect 档 token 占比 < 10%；人工介入 ≤ 3 次（brief/plan/UI/最终验收之外为 0）。

---

## M4 韧性：额度耗尽自动续跑（quota-aware auto-resume）

> 动机：套餐额度用完时 pipeline 直接 `AdapterError` 挂掉，需要人工蹲点、掐表手动重跑。
> 目标：识别"额度耗尽"错误 → 就地降级到便宜档接棒；无可用降级则 **零 token** 挂起，
> 按各家的额度恢复策略在恢复时刻由 OS 级定时器无人值守拉起 `--continue`，续跑那半截卡住的任务。
> 关键约束：**挂起等待期间不能有任何 LLM 调用**（触发时可能已经没 token 了），
> 触发器必须是 OS 级机制（launchd / systemd-timer / at / sleeper 进程），不是 agent。

### T16a  额度耗尽错误分类  ✅ 2026-07-07
**内容**：新增 `harness/quota.py` + `config/quota.yaml`（数据驱动的正则匹配表，按 provider 分组）。
在 `adapters/base.py` 增加 `QuotaExhaustedError(AdapterError)`，携带 `tier / provider / reset_hint`。
adapter `_execute` 里把"额度/余额耗尽"从普通 429 瞬时限流中区分出来（Anthropic：`usage limit`、
`rate_limit_error ... resets at`；MiniMax：`insufficient balance`、`额度`；HTTP 402/403 带额度语义）。
瞬时 429 仍走原指数退避；额度耗尽**不退避**，直接抛 `QuotaExhaustedError`。
**验收**：给定各 provider 的真实错误串样本，分类函数正确区分 瞬时限流 / 额度耗尽 / 硬失败；
误配的错误串不会被当成额度耗尽。**坑点**：错误串会变，全部放 config，代码只读表。

### T16b  恢复时刻计算（两种策略，纯函数）  ✅ 2026-07-07
**内容**：`quota.py` 里 `next_reset(strategy, now, hint) -> datetime`。两种策略：
`fixed_clock`（MiniMax：锚点 `00:00` + 每 `interval_hours=5` 一个边界，取 ≥ now 的下一个边界）；
`rolling`（Anthropic：`now + window_hours=5`，用完才开始算）。`honor_reset_hint=true` 时，
若错误里解析到了确切恢复时间（`retry-after` 秒 / `resets at <time>` / `anthropic-ratelimit-*`）则优先采用。
`now` 从外部注入（禁用裸 `Date.now()` 式不可测写法），便于单测。
**验收**：fixed_clock 跨午夜/边界、rolling、hint 覆盖 三类用例齐全且纯函数无副作用。

### T16c  降级接棒（先用起来未被接线的 fallback）  ✅ 2026-07-07
**内容**：把 `models.yaml` 里已存在但从未被使用的 `fallback` 接上线。inner_loop / pipeline 捕获
`QuotaExhaustedError` 时：若该 tier 有 fallback 且 fallback 未被标记耗尽 → 换 ModelSpec 到 fallback
**立即就地续跑**（即"便宜模型接棒"）；把"tier X 已耗尽"记进运行期状态，避免同一轮反复撞墙。
**验收**：worker 档耗尽后，同一任务自动切到 `claude-haiku-4-5` 继续并跑完；两档都耗尽时进入 T16d 挂起。

### T16d  零 token 挂起 + OS 级定时续跑  ✅ 2026-07-07
**内容**：无可用 fallback（或全档耗尽）时：①确保在跑的 task/phase 状态落盘（复用 WorkflowState +
task status，别丢半截）；②`resume_at = next_reset(...)`；③写 `.runner/quota-hold.json`
（tier/provider/exhausted_at/resume_at/strategy/job_id/project_dir/phase/task_id）；
④注册**OS 级**一次性触发器跑 `python -m harness --continue <project_dir>`：
macOS 用 launchd LaunchAgent（本机 `atrun` 未加载，`at` 不可靠 → 首选 launchd）；
Linux 用 `systemd --user` timer，缺失则退 `at`/cron；都没有则退 detached `nohup` sleeper（sleep 到点再 exec，
仍是零 token）。⑤干净退出并打印 hold 信息。同一 project 只保留一个 pending job（幂等，重排替换）。
**验收**：mock 调度器验证命令构造正确；起一个真实 launchd 一次性 job，到点无人值守拉起 `--continue`
并从正确的 task 续上；挂起期间无任何模型调用（用调用计数断言）。
**坑点**：launchd plist 的 `StartCalendarInterval` 只能到"时分"，跨天要算好日期；job 命名带 project hash 防冲突。

### T16e  可观测性 + 护栏 + CLI  ✅ 2026-07-07
**内容**：`harness status` 展示 pending quota-hold 与倒计时；新增 `python -m harness quota-status` /
`--cancel-hold`。护栏：最大自动续跑次数（额度长期不恢复时别无限循环）、"全档耗尽"要冒泡给人而不是空转。
**验收**：status 正确显示/清除 hold；超过最大续跑次数后停手并留下清晰说明。
**完成记录**：`harness.quota_hold` 新增 `resume_count` / `MAX_AUTO_RESUME=3` /
`QuotaResumeExhaustedError` / `begin_resume` / `enter_quota_hold` /
`cancel_pending_hold` / `format_hold_status`；`harness.__main__` 新增
`quota-status` 子命令、`--cancel-hold` 旗标、`--continue` 起跑前调
`begin_resume()`（撞顶抛 QuotaResumeExhaustedError 退出码 2）、`harness status`
展示 hold + 倒计时、`Pipeline._run_phase_with_quota_guard` 在每个 phase 上
捕 `QuotaExhaustedError` → `enter_quota_hold` → 冒泡让 __main__ 打印清晰
信息（不再 stack trace）。新 28 用例在 `tests/test_t16e_quota_observability.py`，
全量 458 passed / 2 skipped，覆盖率 84%。

---

## M5 硬化：架构 review 发现（4 维并行审查汇总，2026-07-06）

> 4 个子代理分审 并发/状态、adapter/错误语义、pipeline/耦合、测试/安全/配置。以下按严重度排序。
> **⚠️ 关键：T17/T18/T19/T20/T22 是 M4（额度续跑）能真正跑通的前置**——续跑依赖状态完好、
> 第三方模型链路可用、错误可分类。前置不修，M4 是建在沙上。

### T17 ✅ [CRITICAL] 状态持久化原子化 + 损坏检测  ✅ 2026-07-06
**内容**：`artifacts.py:404/501/357` 与 score_card 全用裸 `path.write_text()`，写一半崩溃即截断；
`read_workflow_state:389` / `read_task_queue:477` 捕获 `JSONDecodeError` 后**返回 None**，损坏 state 被当"无 state"
从头重跑。改为 写临时文件 + `os.replace()` 原子替换（同目录 rename）+ 可选 `fsync`；读到损坏时**报错**而非静默 None。
**验收**：注入"写一半"故障后，旧 state 仍可读；损坏文件触发明确报错而非静默重跑。**坑点**：跨维护点都要走同一个原子写工具函数。

### T18 [HIGH] resume 精确接续"半截的 task"  ✅ 2026-07-07
**内容**：三处让续跑无法接上：①`TaskStatus.IN_PROGRESS` 从不写盘（只更 Linear），崩溃时任务仍 pending，
但 worktree `task/{id}` 已存在 → `create_worktree` 因分支已存在失败 → 任务被误打成 blocked；
②`write_task_queue:488-497` 序列化**漏了 `platform` 字段**，重写后 mobile/miniprogram 任务回落 web、丢专属 reviewer；
③`merge_worktree`(inner_loop:920) 先于 `complete_task`(929) 落盘，两步间崩溃 → 代码已并入但任务仍 pending，重跑重复劳动。
改：进 `run_inner_loop` 前把任务写 `in_progress` 落盘；`create_worktree` 对已存在分支/worktree 幂等复用或清理；
merge+complete 构成单一可恢复事务；序列化补全 platform（并审计其他漏字段）。
**验收**：在任务执行中途 kill，`--continue` 能从该任务正确接续、不重复合并、跨端 reviewer 不丢。

### T19 [HIGH] 打通第三方/降级模型链路（base_url + fallback + per-tier key）  ✅ 2026-07-07
**内容**：`ModelSpec.base_url` 从 router 解析出来后被**完全丢弃**——`run()/_execute` 无 `base_url` 形参，
`ClaudeAdapter._execute` 的 `Popen` 没传 `env=`，MiniMax worker 档永远打到默认 Anthropic 端点（**"便宜模型接棒"目前跑不通**）。
`fallback` 字段也只在 `pretty_print` 被读、无任何降级调用路径；`score_card.py:5` docstring 还谎称"switches to fallback"。
改：`run()/_execute` 加 `base_url` 形参，`_execute` 构造 `env={**os.environ, "ANTHROPIC_BASE_URL": base_url, ...}` 传给 `Popen(env=)`，
按 tier 注入对应 API key（避免多后端串号）；主模型失败时用 `spec.fallback` 重试；修正 score_card docstring。
**验收**：worker 档实际打到 MiniMax 端点；主档不可用时自动切 fallback 跑通。**注**：这是 T16c 的前置，T16c 在其上做额度专属降级策略。

### T20 [HIGH] 错误分类结构化（429/5xx/quota 不再靠子串）  ✅ 2026-07-06
**内容**：`claude.py:179/191` 靠 `"429" in stderr` / `"502" in stderr` 裸子串匹配——路径/token 数/行号里出现数字即误判；
5xx 被统一装进 `RateLimitError`（语义是 429）表意混乱；真 429 若写进 stdout JSON 则漏检。
`base.run()` 的 `except Exception` 又把连接重置等**可重试**瞬时错误一律不重试。
改：优先解析 `--output-format json` 的结构化 error/HTTP status，子串退化为兜底并加词界（`\b429\b` + 关键短语）；
5xx 单列 `ServerError(AdapterError)`；把 `ConnectionError/BrokenPipeError` 纳入可重试。
**验收**：给定含"429"噪声的正常输出不误判；5xx 与 429 分流；瞬时连接错误会重试。**注**：T16a 的额度分类建在此清理后的错误分类法之上。

### T21 [HIGH] 预算熔断：接线或拆除（需拍板）  ⏳
**内容**：`router.check_budget()` 通篇 no-op、`BudgetExceeded` 从不抛出、`spent_by_tier` 无消费者，
`models.yaml` 也没有每档 token 上限——"撞顶暂停"这条到处被引用的安全阀是**假承诺**（无人值守跑批 token 无上限）。
连带：visual reviewer 记账返回空 `Usage()`(inner_loop:536) 使 UI 任务 budget 系统性低估；`_instance` 单例是死代码/误导；
`router.py:289` 的 `Usage` 与 `base.py:23` 重复定义需手工同步。
**二选一（请拍板）**：(A) 给 models.yaml 每档加 `max_tokens`，`check_budget` 真正比较并抛异常、每 stage 前调用、补全 visual usage；
(B) 整套 budget 门面连同 `_instance` 一起删除，避免"假安全"。
**验收**：A→撞顶真的暂停并可续；B→死代码清零、文档不再声称有预算保护。

### T22 [HIGH] Python 主路径引入结构化日志  ✅ 2026-07-07
**内容**：`harness/` 全目录零 `import logging`、仅 18 处裸 `print()`；`logs/harness.log` 只被 legacy bash 写。
真正在跑的 Python pipeline 不落任何持久日志，无人值守失败时无排障轨迹。引入 `logging`，统一写 `logs/harness.log`，
关键节点记 stage/task_id/iter/usage/耗时。**验收**：一次失败跑批后，日志能定位到 stage+task+iter。**注**：M4 无人值守续跑尤其依赖它排障。

### T23 [HIGH] 消除 os.environ 原地变异（违反不可变硬规则）  ✅ 2026-07-07
**内容**：`pipeline.py:429/681/684` 用 `os.environ[env_var]=""` 表达"这条反馈已消费"——突变进程级全局、非线程安全、
污染单测、违反 CLAUDE.md 不可变规则。改：把"已消费"状态放进 Pipeline 实例字段（如 `self._consumed_feedback: set`），env 只读。
**验收**：多次运行/并发不互相污染；env 不被写。
**完成记录**：`Pipeline.__init__` 新增 `self._consumed_feedback: set[str] = set()`，
3 处 `os.environ[X] = ""` 全数改为 `self._consumed_feedback.add(X)` +
`if X not in self._consumed_feedback` 守卫；`_ask_feedback` 与
`_ask_version_choice` 改为只读 env、实例级记录消费。`_HostileEnviron` 探针在
测试里替换 `os.environ.__setitem__/__delitem__` 抛 AssertionError，证明
Pipeline 路径不再写 env；并验证两实例互不污染、TTY 路径不消费、plan 反馈
循环仍能在 env 不被清的情况下终止（仅靠实例级 set）。新 12 用例在
`tests/test_t23_no_environ_mutation.py`，全量 470 passed / 2 skipped，
覆盖率 85%。

### T24 [MEDIUM] 拆分超限文件 + run_inner_loop 巨函数  ✅ 2026-07-07
**内容**：`inner_loop.py`=951 行、`pipeline.py`=876 行，均超规范 800 上限；`run_inner_loop`(764-951) 单函数 ~188 行把
queue/worktree/generator/diff/截图/并行评审/记账/gate/merge/升级全混在一起，几无法单测（`finally` 还是空 `pass`）。
拆：inner_loop → `worktree.py` / `generator.py` / `reviewer_runner.py`；pipeline → `ui_phase.py`；
主循环只做编排，抽 `_run_iteration/_setup_task/_on_gate_pass`。**验收**：各文件 <800 行、函数 <50 行、可对单轮迭代做单测。
**完成记录**：抽出 `harness/worktree.py`(207 行) / `generator.py`(140) / `reviewer_runner.py`(475) /
`ui_phase.py`(481)；为打破导入环新加 `loop_errors.py`(27) + `pipeline_base.py`(21)。
`inner_loop.py` 1061→584 行、`pipeline.py` 991→752 行；`run_inner_loop` 从 241 行的巨函数
变成只做编排的 49 行（调 `_setup_task` / `_run_iteration` / `_gate_after_iteration` / `_on_gate_pass`），
每一段都可独立单测。Pipeline 的 `phase_ui` 变成 14 行的 delegate 到 `UIPhase(self).run(plan_text)`。
向后兼容的 re-export 保持所有历史 `from harness.inner_loop import ...` 与
`from harness.pipeline import pick_directions_for_brief` / `extract_ui_output` 可用。
新增 20 个 TDD 用例在 `tests/test_t24_split_modules.py`，全量 490 passed / 2 skipped，
覆盖率 84%；`inner_loop.py` / `ui_phase.py` / `generator.py` 函数全部 ≤50 行，
`reviewer_runner.py` 1 个 + `worktree.py` 1 个 + `pipeline.py:phase_develop` 略超
（前两个 52-55 行，是 T18 幂等 + 线程池布线的天然复杂度；最后一个是 T24 范围外的旧函数）。

### T25 [MEDIUM] adapter DRY + 多模态走统一重试 + JSON 解析优化  ⏳
**内容**：`run_with_attachments`(claude.py:31-117) 与 `_execute`(135-218) 大段重复且已漂移（多模态**漏了 5xx 重试**、
且绕过 `run()` 的重试外壳零重试）；`_extract_json`(273-287) 逐字符 `json.loads` O(n²)、不支持数组；
解析彻底失败时静默返回原文而不抛已定义的 `InvalidResponseError`；结果字段 `or` 链会吞合法假值；附件 argv 缺 `--` 终止符。
改：抽 `_run_subprocess(cmd,...)` 公共私有方法、两路复用；`json.JSONDecoder().raw_decode` 一次 O(n)；解析失败抛 `InvalidResponseError`；
附件前插 `--`。**验收**：多模态与文本路径共用同一重试/错误映射；大 JSON 解析不卡。

### T26 [MEDIUM] 配置健壮性 + 消除耦合/魔数  ⏳
**内容**：`models.yaml`/`slop_rules.yaml` 缺加载期 schema 校验（缺字段静默默认或裸 KeyError，对比 reviewers.yaml 已用 pydantic）；
`PHASE_ARTIFACTS/STAGES/AGENTS` + runners 四张平行 Phase 表（改新 phase 要动四处）→ 合成 `@dataclass PhaseSpec` 单表；
`inner_loop:896` 访问 `ReviewerAssembly._agents_dir` 私有属性→暴露公开 property；
`ThreadPoolExecutor(max_workers=len(names))` 空列表会 `ValueError`→`max(1,len)` 且空 reviewer fail-fast；
散落魔数（timeout 300/180、git 30/10、端口 8765、`fallback[:6]`）提为命名常量。
**验收**：坏配置加载即报清晰错误；新增 phase 只改一处；空 reviewer 有明确诊断。

### T27 [MEDIUM] 清理双实现债务 + env 文档统一  ⏳
**内容**：`autodev-harness.sh:13` 在 `AUTODEV_USE_LEGACY=1` 时仍 `exec` 22KB legacy bash（source 全部 `lib/*.sh`），
两套 pipeline 需同时维护、注释写"30 天后删"但仍接线；shell 读 `AUTODEV_MODEL/API_KEY/BASE_URL`，Python 读
`AUTODEV_MODEL_<TIER>` 等，同概念不同名散落 5+ 文件、无集中清单；`opencode/codex` 是纯 stub，应在 `router.resolve`/启动校验
fail-fast 而非等 `_execute` 才炸；`AgentResult.success`(`not stderr`) 语义错（仅冒烟测试用，属埋雷）。
**内容决策**：定死 legacy 删除日期或立即下线。改：集中一份 env 变量文档并统一命名；success 只看 exit_code。
**验收**：env 变量单一清单；legacy 去留有明确结论；未实现 adapter 启动即报错。

---

## 给执行模型的执行协议（EXECUTOR PROTOCOL — 开工前必读）

> 你是**执行者**，不是设计者。唯一事实来源是本文件（`docs/TASKS.md`）。
> 你的工作是把里面的任务一个一个落地，**不做任何设计决策、不改需求、不扩大范围**。

### ① 铁律（违反任一条 → 立刻停手）

1. **一次只做一个任务**，按依赖顺序来。禁止合并任务、禁止跳序、禁止"顺手重构"清单外的任何东西。
2. **T21 已搁置——绝对不要碰**（不动 budget / `check_budget` / `_instance` / `BudgetExceeded`）。
3. **依赖顺序**（先地基，后特性）：
   `T17 → T20 → T19 → T18 → T22 → 然后才是 M4（T16a–e）→ 最后 T23–T27`。
   被 `blockedBy` 的任务，前置没做完不许开工。**不许挑软柿子先做 T24–T27 的重构**。
4. **强制 TDD**：先写会失败的测试（RED）→ 跑，确认真的失败 → 写最小实现（GREEN）→ 跑绿 → 重构。
   没有先写测试，不许写实现。
5. **不可变硬规则**：禁止原地修改对象、**禁止写 `os.environ`**（这正是 T23 要修的病，别再犯）。要改就返回新副本。
6. 文件 **<800 行**、函数 **<50 行**、嵌套 **<4 层**。
7. **全量测试必须保持绿**（当前基线约 318 passed），覆盖率 **≥80%**。你的改动不许让任何已有测试变红。
8. 只用 **worker 档便宜模型**自测调试。**禁止调用 architect/Opus 档**——那些位置只允许出现在
   `config/models.yaml` 路由指定处。
9. 不删除、不覆盖你没创建的东西；不联网发布任何内容。

### ② 每个任务的执行循环（照抄）

1. 读该任务在本文件里的 内容 / 验收 / 坑点。
2. 任务里引用的 `file:line` **可能已漂移**——动手前先 `grep` 核对真实位置，不要盲信行号。
3. 把任务拆成待办步骤（TodoWrite）。
4. 按 TDD 写测试 → 实现。
5. 跑该任务的**验收标准** + 全量 `pytest`。全绿才算完。
6. 一个任务 = 一个 commit，conventional 格式（`fix:` / `refactor:` / `feat:` …）；
   **先开分支，不要 push（除非人类明确要求）**。
7. 把本文件里该任务的 `⏳` 改成 `✅` + 日期。
8. 回到第 1 步取下一个可做的任务。

### ③ 卡住怎么办（最重要）

- **同一个报错试 3 次还不过 → 立刻停**。把上下文（报错、你试了什么、卡在哪）写清楚问人，
  **绝不允许绕过验收、改测试凑绿、或换条路硬塞过去**。
- 任务描述和实际代码矛盾时 → 停下问人，不要自己猜着改。

### ④ 完成判定 checklist（每个任务收工前逐条过）

- [ ] 先写了测试且一开始是红的
- [ ] 验收标准全部满足
- [ ] 全量测试绿、覆盖率 ≥80%
- [ ] 无 mutation、无 `os.environ` 写、无硬编码密钥
- [ ] 文件 <800 行、函数 <50 行
- [ ] 一任务一 commit，本文件对应任务已打勾
