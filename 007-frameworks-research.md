# AI Coding Agent Framework Research Report

## Research Date
2026-05-05

## Objective
Analyze competitive AI coding agent frameworks to inform AutoDevHarness development and identify best practices.

---

## 1. Cursor (cursor.com)

### Architecture
- **Planner → Executor → Workers** hierarchy
- Root planner owns scope, spawns sub-planners
- Workers pick up tasks and drive completion autonomously
- Executor can spawn tasks for workers (linear scaling)

### Key Innovations
1. **Agent-Computer Interface (ACI)**: Custom tool interfaces optimized for code interaction
2. **Observability**: All agent messages, actions, commands logged with timestamps for replay
3. **Context management**: Dynamic context discovery as models improve
4. **Multi-model routing**: Different models for different subtasks, race pattern for difficult problems
5. **Video/screenshot verification**: Agents demonstrate work visually

### Performance
- Peaked at ~1,000 commits/hour across 10M tool calls over one week
- Built a web browser from scratch with frontier models

### Lessons for AutoDevHarness
- Planning phase before execution (matching our Research → Plan flow)
- User confirmation before development (matching our confirm_plan)
- Observability is critical - log everything for replay and analysis
- Model routing based on task complexity

---

## 2. SWE-agent (Princeton NLP)

### Architecture
- Simple agent loop: read → edit → execute → verify
- Agent-Computer Interface with specialized tools (file navigation, editing, command execution)
- SWE-bench benchmark leader (74%+ on SWE-bench verified with mini-SWE-agent)

### Key Innovations
1. **Minimal design**: "The 100 line AI agent" - no fancy dependencies
2. **Bash-only tools**: Agent uses shell commands to do everything
3. **Custom tool formats per model**: Patch-based for OpenAI, string replacement for Anthropic

### Performance
- >74% on SWE-bench verified
- Costs ~$0.04-$0.73 per issue depending on model
- Very fast startup time

### Lessons for AutoDevHarness
- Simplicity over complexity
- Tool design should match model training format
- Token efficiency matters for cost control

---

## 3. Devin (Cognition Labs)

### Architecture
- **Brain (reasoning)** + **DevBox (execution)** separation
- Sub-agents: Code Editor, Command Line, Error Handler, Browser
- Sandboxed VM with shell, code editor, browser

### Key Innovations
1. **Interactive planning**: Scan → Plan → Review → Execute with user approval
2. **Memory hierarchy**: Cross-session (knowledge base), Session memory, DeepWiki auto-indexing
3. **Dynamic replanning**: Revises plan mid-task if user changes direction
4. **Error Handler Agent**: Uses RAG to analyze failures and trigger iterative fixes

### Performance (2025 review)
- 67% PRs merged (up from 34% at launch)
- Best for tasks taking junior engineer 4-8 hours
- Security fixes: 20x efficiency (1.5 min vs 30 min human average)

### Lessons for AutoDevHarness
- User approval before execution (matching our plan confirmation)
- Memory and state persistence across sessions
- Error handler for autonomous iteration

---

## 4. AutoGen (Microsoft)

### Architecture
- **Event-driven** multi-agent system
- AgentChat API for simple patterns
- Core API for complex workflows

### Key Patterns
1. **Hierarchical**: Supervisor coordinates workers
2. **Sequential**: Pipeline where agents pass results
3. **Collaborative**: Agents negotiate dynamically

### Strengths
- Native multi-agent coordination
- Python and .NET support
- Docker-based code execution

### Lessons for AutoDevHarness
- Multiple agent types with different responsibilities
- Clear communication protocols between agents

---

## 5. LangChain Deep Agents

### Architecture
- **ReAct pattern**: Reasoning + Acting loop
- Planning tools for task decomposition
- Subagent isolation for parallel execution

### Key Features
- Virtual filesystem for long-term memory
- Context compression for conversation history
- Tool call middleware for dynamic tool selection

### Lessons for AutoDevHarness
- Subagent isolation for parallel work
- Task decomposition before execution
- Context management for long-running tasks

---

## 6. OpenDevin

### Architecture
- **CodeAct**: Unified code action space
- Containerized evaluation environment
- State-of-the-art on SWE-bench Lite (21% vs SWE-agent's 17%)

### Key Innovations
- Countdown mechanism to encourage completion in fixed interactions
- Simplified bash command writing

### Lessons for AutoDevHarness
- Time-boxed iteration to prevent infinite loops
- Sandbox isolation for code execution

---

## Key Patterns Summary

| Pattern | Where Used | AutoDevHarness Status |
|---------|------------|----------------------|
| Planning before execution | Cursor, Devin, AutoGen | Implemented (Plan phase) |
| User confirmation | Cursor, Devin | Implemented (confirm_plan) |
| Multi-agent coordination | Cursor, AutoGen, LangChain | Basic (Generator + Evaluator) |
| Error handling with retry | Devin, OpenDevin | Basic |
| Observability/logging | Cursor | Needs improvement |
| State persistence | Devin | Basic (workflow-state.json) |
| Context management | Cursor, LangChain | Needs improvement |
| Model routing | Cursor | Not implemented |

---

## Recommendations for AutoDevHarness

### Short-term (Current framework)
1. **Improve observability**: Add detailed logging to all agent calls
2. **Enhance state management**: Persist more context between sessions
3. **Error recovery**: Add retry logic with backoff
4. **Quality gates**: Already implemented but need testing

### Medium-term (Next iteration)
1. **Multi-model support**: Route tasks to different models based on complexity
2. **Parallel task execution**: Spawn multiple workers for independent tasks
3. **Memory system**: Add cross-session knowledge base

### Long-term (Future features)
1. **Video/screenshot verification**: Demonstrate work visually (like Cursor)
2. **Interactive planning UI**: Web dashboard for plan approval
3. **Advanced context compression**: Handle longer conversations efficiently

---

## References

- Cursor: Towards self-driving codebases (https://cursor.com/blog/self-driving-codebases)
- Cursor: Scaling long-running autonomous coding (https://cursor.com/blog/scaling-agents)
- SWE-agent: Agent Computer Interfaces (https://arxiv.org/abs/2405.15793)
- Devin: The AI Software Engineer (https://devin.ai/)
- AutoGen: Microsoft Multi-Agent Framework (https://microsoft.github.io/autogen/)
- OpenDevin: CodeAct 1.0 (https://xwang.dev/blog/2024/opendevin-codeact-1.0-swebench/)
- harness-orchestrator on PyPI (https://pypi.org/project/harness-orchestrator/)
