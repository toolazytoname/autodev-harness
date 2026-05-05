# AI 编程 Agent 框架研究报告

## 研究日期
2026-05-05

## 目标
分析竞品 AI 编程 Agent 框架，为 AutoDevHarness 开发提供参考并识别最佳实践。

---

## 1. Cursor (cursor.com)

### 架构
- **Planner → Executor → Workers** 层级结构
- 根 planner 拥有完整范围，分派 sub-planners
- Workers 领取任务并自主驱动完成
- Executor 可为 workers 生成任务（线性扩展）

### 关键创新
1. **Agent-Computer Interface (ACI)**: 针对代码交互优化的自定义工具接口
2. **可观测性**: 所有 agent 消息、动作、命令都带时间戳记录，支持回放
3. **上下文管理**: 随着模型能力提升，动态发现上下文
4. **多模型路由**: 根据任务复杂度选择不同模型，困难问题使用竞速模式
5. **视频/截图验证**: Agent 直观展示工作成果

### 性能
- 峰值约 1,000 commits/hour，一周内超过 10M tool calls
- 使用前沿模型从零构建了一个网页浏览器

### 对 AutoDevHarness 的启示
- 执行前的规划阶段（对应我们的 Research → Plan 流程）
- 开发前的用户确认（对应我们的 confirm_plan）
- 可观测性至关重要 - 记录一切用于回放和分析
- 根据任务复杂度进行模型路由

---

## 2. SWE-agent (Princeton NLP)

### 架构
- 简单 agent 循环：read → edit → execute → verify
- Agent-Computer Interface 配备专用工具（文件导航、编辑、命令执行）
- SWE-bench 基准测试领先者（mini-SWE-agent 在 SWE-bench verified 上达到 74%+）

### 关键创新
1. **极简设计**: "100 行 AI agent" - 无需花哨依赖
2. **仅用 Bash 工具**: Agent 使用 shell 命令完成一切
3. **每种模型定制工具格式**: OpenAI 用 patch 格式，Anthropic 用字符串替换

### 性能
- SWE-bench verified 上 >74%
- 根据模型不同，成本约 $0.04-$0.73 per issue
- 启动速度极快

### 对 AutoDevHarness 的启示
- 简洁优于复杂
- 工具设计应匹配模型训练格式
- Token 效率影响成本控制

---

## 3. Devin (Cognition Labs)

### 架构
- **Brain (推理)** + **DevBox (执行)** 分离
- 子 agents: Code Editor, Command Line, Error Handler, Browser
- 沙盒 VM 配备 shell、代码编辑器、浏览器

### 关键创新
1. **交互式规划**: Scan → Plan → Review → Execute，需用户批准
2. **记忆层级**: 跨会话（知识库）、会话记忆、DeepWiki 自动索引
3. **动态重规划**: 用户改变方向时中途修订计划
4. **Error Handler Agent**: 使用 RAG 分析失败并触发迭代修复

### 性能（2025 年回顾）
- 67% PR 合并（发布时 34%）
- 最适合初级工程师需要 4-8 小时的任务
- 安全修复：20x 效率（1.5 分钟 vs 人工 30 分钟）

### 对 AutoDevHarness 的启示
- 执行前用户批准（对应我们的计划确认）
- 跨会话的内存和状态持久化
- 自主迭代的错误处理

---

## 4. AutoGen (Microsoft)

### 架构
- **事件驱动** 多 Agent 系统
- AgentChat API 适用于简单模式
- Core API 适用于复杂工作流

### 关键模式
1. **层级式**: Supervisor 协调 workers
2. **顺序式**: Agent 形成管道传递结果
3. **协作式**: Agent 动态协商

### 优势
- 原生多 Agent 协调
- 支持 Python 和 .NET
- 基于 Docker 的代码执行

### 对 AutoDevHarness 的启示
- 多种不同职责的 Agent 类型
- Agent 之间清晰的通信协议

---

## 5. LangChain Deep Agents

### 架构
- **ReAct 模式**: Reasoning + Acting 循环
- 任务分解的规划工具
- 子 Agent 隔离实现并行执行

### 关键特性
- 虚拟文件系统实现长期记忆
- 对话历史压缩
- 动态工具选择的中件间

### 对 AutoDevHarness 的启示
- 子 Agent 隔离实现并行工作
- 执行前任务分解
- 长时间运行任务的上下文管理

---

## 6. OpenDevin

### 架构
- **CodeAct**: 统一的代码动作空间
- 容器化的评估环境
- SWE-bench Lite 上达到 SOTA（21% vs SWE-agent 的 17%）

### 关键创新
- 倒计时机制，鼓励在固定交互次数内完成
- 简化的 bash 命令编写

### 对 AutoDevHarness 的启示
- 时间盒迭代防止无限循环
- 代码执行的沙盒隔离

---

## 关键模式汇总

| 模式 | 使用者 | AutoDevHarness 状态 |
|---------|------------|----------------------|
| 执行前规划 | Cursor, Devin, AutoGen | ✅ 已实现（Plan 阶段） |
| 用户确认 | Cursor, Devin | ✅ 已实现（confirm_plan） |
| 多 Agent 协调 | Cursor, AutoGen, LangChain | ⚠️ 基础（Generator + Evaluator） |
| 带重试的错误处理 | Devin, OpenDevin | ⚠️ 基础 |
| 可观测性/日志 | Cursor | ❌ 需要改进 |
| 状态持久化 | Devin | ⚠️ 基础（workflow-state.json） |
| 上下文管理 | Cursor, LangChain | ❌ 需要改进 |
| 模型路由 | Cursor | ❌ 未实现 |

---

## AutoDevHarness 建议

### 短期（当前框架）
1. **提升可观测性**: 为所有 agent 调用添加详细日志
2. **增强状态管理**: 在会话之间持久化更多上下文
3. **错误恢复**: 添加带退避的重试逻辑
4. **质量门禁**: 已实现但需要测试

### 中期（下次迭代）
1. **多模型支持**: 根据任务复杂度路由到不同模型
2. **并行任务执行**: 为独立任务生成多个 workers
3. **记忆系统**: 添加跨会话知识库

### 长期（未来特性）
1. **视频/截图验证**: 直观展示工作成果（像 Cursor 那样）
2. **交互式规划 UI**: 用于计划批准的 Web dashboard
3. **高级上下文压缩**: 高效处理更长对话

---

## 参考资料

- Cursor: Towards self-driving codebases (https://cursor.com/blog/self-driving-codebases)
- Cursor: Scaling long-running autonomous coding (https://cursor.com/blog/scaling-agents)
- SWE-agent: Agent Computer Interfaces (https://arxiv.org/abs/2405.15793)
- Devin: The AI Software Engineer (https://devin.ai/)
- AutoGen: Microsoft Multi-Agent Framework (https://microsoft.github.io/autogen/)
- OpenDevin: CodeAct 1.0 (https://xwang.dev/blog/2024/opendevin-codeact-1.0-swebench/)
- harness-orchestrator on PyPI (https://pypi.org/project/harness-orchestrator/)
