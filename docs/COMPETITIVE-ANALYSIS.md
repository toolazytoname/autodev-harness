# 竞品对照与差距分析（Competitive Analysis）

> 首次成文：2026-07-09。用于对照市面主流"自主/半自主编码 agent"方案，
> 判断本项目（AutoDevHarness v2）的定位、独有价值与差距。
> 结论会随竞品迭代过时，引用前先看日期。
>
> 一句话定位：本项目主张 **"结构 > 模型"**——质量来自
> `生成 → N 个独立 reviewer 并行 → 硬 gate → 合并`，靠便宜模型 + 分档路由，
> 而非靠贵模型。这条主张落在几个既有流派的交叉点上。

---

## 1. 定位坐标：本项目在赛道里的位置

按"和本项目架构像不像"排序（🟢 高度重合 / 🟡 部分重合 / 🔴 定位不同）：

| 竞品 | 流派 | 重合度 | 成熟度 |
|------|------|:------:|--------|
| **gpt-pilot / Pythagora** | spec→plan→tasks→code + reviewer + 人工三点介入 | 🟢 最像——几乎同一套外层流水线 + 人在环 | 商业化（VS Code 插件），有真实用户 |
| **MetaGPT** | 多角色扮演（PM/架构/工程/QA → PRD/设计/任务/代码） | 🟢 外层五阶段几乎一一对应 | 学术明星，社区庞大 |
| **Agentless (Princeton)** | 无 agent 的结构化流水线：定位→修复→验证 | 🟢 思想同源——"简单结构打败复杂 agent" | 论文 + SWE-bench 打榜 |
| **OpenHands (All-Hands)** | 沙箱化 agent 平台，事件流架构，microagents | 🟡 都做质量闭环，但它是 agentic 执行 | 开源标杆，SWE-bench 领先 |
| **Plandex** | 重量级自主 CLI，plan 文件 + 沙箱 + git 分支 | 🟡 外层 plan/checkpoint/多模型很像 | 成熟 TUI，可自托管 |
| **Aider** | git 原生结对编程，repo-map，多模型 | 🟡 多模型 + git 强，但无独立 gate | 采用量巨大 |
| **Claude Code / Codex CLI / Gemini CLI** | 通用编码 agent CLI（本项目 worker 层就在包它） | 🟡 subagent/plan mode/hooks 与本项目有重叠 | 商业成熟 |
| **Devin / Factory (Droids) / Cursor 后台 agent** | 商业全自主 / IDE 深度集成 / PR 级 | 🔴 定位不同（闭源、PR 级） | 商业成熟 |

---

## 2. 本项目的差异化亮点（多数竞品没有）

这些是想清楚了、而主流工具反而弱的地方，是相对竞品的**立身之本**：

1. **独立并行 reviewer + 硬 gate + score card 证据链**
   多数工具是"自我 review"或单遍生成；本项目是 N 个**互相看不见**的 reviewer
   各写各的评分卡，`test` reviewer 必须交出**真实命令输出**才放行。最接近的只有
   Agentless 的 validation 环节和 CI gate。**这是最有价值的设计。**

2. **成本分档路由（architect / reviewer / worker + fallback）**
   显式的多档经济学 + 便宜模型接棒。Aider/Plandex 支持多模型但要手动选；
   "贵模型只在 plan 出现、占比 < 10%"这种**主动成本工程**是它独有的。

3. **配额耗尽零 token 自动续跑（launchd / systemd OS 级唤醒）**
   在任何竞品里都没见过。无人值守跑批、额度用完就地挂起、恢复时刻靠操作系统
   定时器拉起 `--continue`——实打实的运维创新。

4. **品味注入 + 视觉 reviewer（Playwright 截图打分）**
   绝大多数编码 agent 完全无视美学；它把设计质量也纳入 gate。加上小程序/移动端
   reviewer 维度，是差异化的小众竞争力。

---

## 3. 差距分析（按严重度）

### 🔴 P0-1　没有任何标准 benchmark 分数——最致命
所有头部竞品都报 **SWE-bench Verified** 百分比（OpenHands / SWE-agent / Devin /
Agentless 都在榜上互比）。本项目**一个外部基准都没跑过**，连 CASE-STUDY 都是 mock。
后果：**没人能判断它的质量到底行不行**，包括作者自己。这是可信度硬伤，而它恰恰
最容易补——跑一遍 SWE-bench Lite，哪怕分数不高，也从"零证据"变成"有坐标"。

### 🔴 P0-2　执行深度是"一次性生成"，不是 agentic 循环
**架构代差。** 2025–2026 主流（OpenHands / Devin / Plandex / Claude Code 自己）是
**agent 在沙箱里用工具循环**：读文件 → 改 → 跑测试 → 看报错 → 自己改，直到自洽。
本项目的 generator 是**一次性 prompt 出码**，再丢给 reviewer；迭代要靠 reviewer
回灌 blocker 再重跑整轮——更慢、更贵，且 worker 没机会在提交前自证。
> 类比：竞品让工人自己会用锤子；本项目让工人闭眼砌墙，砌完叫质检来看。

### 🟡 P1-1　沙箱 / 运行时弱
OpenHands / Plandex / Devin 有 Docker 沙箱 + 持久运行时（shell / 浏览器 / 编辑器
都是 agent 的工具）。本项目靠 `claude -p` 每次起子进程 + git worktree 隔离，
**没有持久执行环境**，dev server / Playwright 是外挂而非一等公民。

### 🟡 P1-2　"多后端"是宣传，不是现实
Plandex / Aider / OpenHands 是**真·多模型**；本项目 opencode / codex 是
`NotImplementedError` stub，只有 claude 能跑。

### 🟡 P1-3　生态与采用为零
OpenHands / Aider / Plandex 都有庞大社区、真实用户、被踩过的坑与修过的 issue。
本项目是**单人项目、零用户、零外部验证**。成熟度不只是代码质量。

### 🟢 P2-1　交互体验落后一代
竞品有 TUI / IDE 插件 / Web UI、流式输出、会话管理；本项目是批处理 CLI + `input()`。

---

## 4. 缩差距的行动建议（按性价比）

1. **跑一次 SWE-bench Lite**（哪怕 300 题子集）——把"结构 > 模型"这个主张**用数字
   证明**。这是把项目从"看起来合理"变成"可被引用"的唯一途径，也直接回应"核心闭环
   从没真实验证"。→ 建议开为 **T40**。
2. **给 generator 加一层 agentic 自校验**——让 worker 在交给 reviewer 前能自己跑测试、
   修一轮，显著降低 reviewer 回灌成本，直接对齐主流架构。→ 建议开为 **T41**。
3. **收敛宣传口径**——别在"多后端 / Linear"上继续吹，把力气收到真正独特的三点：
   独立 reviewer gate、成本分档、配额自动续跑。硬拼 agentic 执行和生态短期赢不了。

> 一句话总结差距：**竞品在"证明自己能干活"（benchmark）和"让 agent 自己会干活"
> （agentic 循环）上领先一代；本项目在"用便宜模型 + 独立质检 + 无人值守把活干稳"
> 上有独到设计，但还停在纸面，缺一次真实数字的背书。**

---

## 5. 逐竞品速记（备查）

- **gpt-pilot / Pythagora** — 与本项目外层最像：spec→plan→tasks→code，reviewer +
  人工 checkpoint + 测试驱动。已商业化为 VS Code 插件。**可重点抄它的交互取舍。**
- **MetaGPT** — "软件公司装进盒子"，多角色产出全套文档。外层五阶段对标它。
- **Agentless** — 反 agent 派论文，证明简单结构化流水线在 SWE-bench 上能打赢复杂
  agent。**本项目的理论靠山，应引用它的方法论。**
- **OpenHands** — 开源标杆，事件流 + 沙箱运行时 + SWE-bench 领先。**执行深度的学习对象。**
- **Plandex** — 重量级自主 CLI，plan 文件 + Docker 沙箱 + git 分支 + 多模型。**沙箱与
  多模型的参考实现。**
- **Aider** — git 原生、repo-map 上下文管理、真多模型。**上下文管理可借鉴。**
- **Devin / Factory / Cursor 后台 agent** — 商业全自主 / PR 级；定位不同，看产品化即可。

---

## 6. 来源（Sources）

- OpenHands (All-Hands-AI)：<https://github.com/All-Hands-AI/OpenHands>
- OpenHands 论文（arXiv:2407.16741）：<https://arxiv.org/abs/2407.16741>
- OpenHands SWE-bench 评测：<https://github.com/All-Hands-AI/OpenHands-SWE-Bench-Evaluation>
- Plandex：<https://github.com/plandex-ai/plandex>
- Devin / Cognition：<https://www.cognition.ai/devin>
- （Agentless / SWE-agent / MetaGPT / gpt-pilot / Aider 见各自 GitHub / arXiv；本表
  基于截至 2026-01 的公开信息 + 2026-07 复核，具体分数以官方最新榜单为准。）
