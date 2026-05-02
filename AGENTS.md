# Agent 系统说明

AutoDevHarness 使用三个专门的 Agent（AI 代理）来协作完成开发任务。

## 目录

- [概述](#概述)
- [Planner (规划师)](#planner-规划师)
- [Generator (开发者)](#generator-开发者)
- [Evaluator (评审官)](#evaluator-评审官)
- [协作流程](#协作流程)

---

## 概述

三个 Agent 各司其职：

| Agent | 角色 | 核心能力 |
|-------|------|----------|
| **Planner** | 产品经理 | 理解需求，分解任务 |
| **Generator** | 软件工程师 | 编写代码，实现功能 |
| **Evaluator** | QA/设计师 | 测试评审，保证质量 |

### 为什么需要三个 Agent？

单个 AI Agent 写代码时常见问题：
- **过度自信**：给自己的代码打高分
- **遗漏细节**：赶进度跳过边界情况
- **质量下滑**：长时间工作后注意力下降

分离后：
- Generator 专心写代码，不用操心评审
- Evaluator 保持严格，不会自我原谅
- 形成对抗，迫使 Generator 做得更好

---

## Planner (规划师)

### 角色定位

Planner 是产品经理 + 架构师的结合。

### 输入

- 用户的简单需求（如 "Build a Kanban board app"）
- 项目类型（fullstack/frontend/api/library）

### 输出

1. **SPEC.md** - 详细产品规格
2. **config/eval-rubric.md** - 评审标准
3. **state/task-queue.json** - 任务分解

### 规划原则

```
1. Be Ambitious (雄心勃勃)
   - 12-16 个功能点，不只是 5-6 个
   
2. Be Specific (具体明确)
   - 指定精确颜色 (#1a73e8)
   - 指定字体 (Inter, not "modern")
   - 指定布局 (3列网格, not "responsive")
   
3. Be Thorough (全面考虑)
   - 空状态设计
   - 错误状态设计
   - 加载状态设计
   
4. Be Practical (务实可行)
   - 依赖关系要合理
   - 任务大小要适中
```

### 示例规划

输入：
```
Build a task management app
```

Planner 输出（节选）：
```markdown
# TaskFlow

## Vision
一个简洁高效的任务管理应用，让用户轻松管理日常任务。

## Color Palette
- Primary: #6366f1 (Indigo)
- Secondary: #8b5cf6 (Purple)
- Background: #f8fafc
- Text: #1e293b
- Success: #22c55e
- Error: #ef4444

## Features

### Must-Have (Sprint 1-2)
1. **任务创建**: 用户可以创建带标题、描述、截止日期的任务
2. **任务列表**: 显示所有任务，支持筛选和排序
3. **任务编辑**: 修改任务内容
4. **任务删除**: 软删除，带确认对话框

### Should-Have (Sprint 3-4)
5. **标签系统**: 为任务添加标签分类
6. **搜索功能**: 按标题/描述搜索
7. **拖拽排序**: 调整任务顺序

### Nice-to-Have (Sprint 5+)
8. **AI 建议**: 根据上下文推荐任务
9. **团队协作**: 多人实时编辑
10. **数据导出**: CSV/JSON 导出
```

---

## Generator (开发者)

### 角色定位

Generator 是全栈软件工程师，负责实现功能。

### 输入

- `SPEC.md` - 产品规格
- `state/task-queue.json` - 当前任务
- 评审反馈（如有）

### 输出

- 实现的代码
- 通过质量门禁
- 提交到 git

### 开发规范

#### 代码风格
```typescript
// ✅ 好的例子
const calculateTotal = (items: CartItem[]): number => {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
};

// ❌ 避免的
let total = 0;
for (let i = 0; i < items.length; i++) {
  total += items[i].price * items[i].quantity;
}
```

#### 错误处理
```typescript
// ✅ 好的例子
try {
  const data = await fetchUserData(userId);
  return data;
} catch (error) {
  logger.error('Failed to fetch user', { userId, error });
  throw new UserFetchError(`Failed to fetch user ${userId}`);
}

// ❌ 避免的
try {
  const data = await fetchUserData(userId);
  return data;
} catch (error) {
  // 静默吞掉错误
}
```

#### 命名规范
```typescript
// ✅ 好的例子
const isLoading = ref(false);
const userProfile = reactive({});
const fetchUserById = async (id: string) => {};

// ❌ 避免的
const flag = ref(false);
const data = reactive({});
const get = async (id: string) => {};
```

### 质量门禁

Generator 必须通过以下门禁才能算完成任务：

| 门禁 | 说明 | 失败处理 |
|------|------|----------|
| lint | 代码风格检查 | 必须修复 |
| build | 生产构建 | 必须修复 |
| test | 单元测试 | 必须修复 |

### 提交规范

每个任务完成后需要提交：

```bash
git add .
git commit -m "feat(task-003): implement task editing

- Add edit modal component
- Integrate with API
- Add unit tests
- Pass lint and build"
```

---

## Evaluator (评审官)

### 角色定位

Evaluator 是严厉的 QA 工程师 + 设计批评家。

### 核心原则

> **Be ruthlessly strict.** (必须极其严格)
>
> 一个 7 分意味着真正的好作品，不是"对 AI 来说不错"。

### 输入

- `SPEC.md` - 产品规格
- `config/eval-rubric.md` - 评审标准
- 运行的应用程序 (http://localhost:3000)

### 输出

- 评分 (1-10)
- 问题列表（带修复建议）
- 是否通过

### 评分维度

#### Design Quality (设计质量) - 30%

| 分数 | 含义 |
|------|------|
| 1-3 | 通用模板风格，没有设计感 |
| 4-6 | 过得去但不惊艳 |
| 7-8 | 有统一的设计语言 |
| 9-10 | 专业设计师水准 |

**扣分点**：
- 通用渐变背景 (#667eea → #764ba2)
- 库存图片占位
- 默认 UI 库主题未定制
- 不一致的间距

#### Originality (原创性) - 20%

| 分数 | 含义 |
|------|------|
| 1-3 | 完全模板化 |
| 4-6 | 有些自定义但大部分雷同 |
| 7-8 | 有明显创意 |
| 9-10 | 令人惊喜的独特设计 |

**扣分点**：
- 照搬其他应用布局
- 没有自己的视觉标识
- 大量使用默认图标

#### Craft (工艺) - 30%

| 分数 | 含义 |
|------|------|
| 1-3 | 布局错乱，很多毛刺 |
| 4-6 | 基本对齐，有小问题 |
| 7-8 | 平滑流畅，细节到位 |
| 9-10 | 像素级完美 |

**扣分点**：
- 文字溢出
- 响应式断点问题
- 缺少 hover/focus 状态
- 动画卡顿

#### Functionality (功能) - 20%

| 分数 | 含义 |
|------|------|
| 1-3 | 核心功能完全不能用 |
| 4-6 | 主流程能用，边界情况有 bug |
| 7-8 | 所有功能正常工作 |
| 9-10 | 异常处理完善，体验完美 |

**扣分点**：
- 按钮点击没反应
- 表单提交失败没提示
- 空状态没有设计
- 错误提示不清楚

### 评审示例

```markdown
# Evaluation — Iteration 3

## Scores

| Criterion | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Design Quality | 7/10 | 0.3 | 2.1 |
| Originality | 6/10 | 0.2 | 1.2 |
| Craft | 8/10 | 0.3 | 2.4 |
| Functionality | 7/10 | 0.2 | 1.4 |
| **TOTAL** | | | **7.1/10** |

## Verdict: PASS ✓

---

## Critical Issues (must fix)

1. **[Design]** 渐变背景太通用
   → 替换为 SPEC 中指定的纯色 #f8fafc

2. **[Functionality]** 删除任务后列表没有刷新
   → 在 onSuccess 回调中调用 refetch()

---

## Suggestions (nice to fix)

1. 加载状态添加骨架屏而非 spinner
2. 错误提示增加图标区分类型
```

---

## 协作流程

### 正常流程

```
Planner ──▶ Generator ──▶ Evaluator
  │              │              │
  │              │              │
  │        "实现功能"      │
  │              │         │
  │              │    "评分 6.5"   │
  │              │         │
  │              │◀────────┘
  │              │   "需要改进..."
  │              │
  │        "修复问题"
  │              │
  │              ▼
  │         Evaluator
  │              │
  │              │ "评分 7.2 ✓"
  │              │
  ▼         通过
```

### 问题处理

如果连续 3 次迭代分数没有提升（高原期），系统会停止并提示人工介入。

---

## 自定义 Agent

### 修改 Planner

编辑 `agents/planner.md`，调整：
- 输出格式
- 规划原则
- 功能要求

### 修改 Evaluator

编辑 `agents/evaluator.md`，调整：
- 评分权重
- 评分标准
- 问题分类

### 新增 Agent

可以添加专门用途的 Agent：

- `agents/security-auditor.md` - 安全专家
- `agents/performance-auditor.md` - 性能专家
- `agents/accessibility-auditor.md` - 无障碍专家

然后在 `gan-loop.sh` 中集成。
