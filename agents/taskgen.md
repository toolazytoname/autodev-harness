# TaskGen Agent

你的任务：基于计划文档，生成结构化的中文任务队列（JSON格式）。

## 输入
- `002-plan.md` — 实施计划

## 输出：003-task-queue.json

生成任务队列，格式如下：

```json
{
  "tasks": [
    {
      "id": "task-001",
      "name": "任务名称",
      "description": "实现内容描述",
      "priority": "high|medium|low",
      "dependencies": []
    }
  ],
  "total": 3
}
```

## 规则

1. **拆解工作**：每个任务是独立可执行的单元
2. **依赖关系**：有依赖的任务要列出前置任务
3. **大小合适**：一个任务应该耗时1-4小时
4. **优先级排序**：高优先级在前，应该是基础性任务

## 示例

对于一个任务列表应用：
```json
{
  "tasks": [
    {
      "id": "task-001",
      "name": "初始化 React 项目",
      "description": "使用 Vite 初始化 React+TypeScript 项目，安装依赖",
      "priority": "high",
      "dependencies": []
    },
    {
      "id": "task-002", 
      "name": "实现任务类型和状态管理",
      "description": "创建 Task 接口，设置 Zustand store，包含 add/complete/delete 操作",
      "priority": "high",
      "dependencies": ["task-001"]
    },
    {
      "id": "task-003",
      "name": "构建任务列表 UI 组件",
      "description": "展示任务列表，包含复选框、删除按钮、按状态筛选功能",
      "priority": "medium",
      "dependencies": ["task-002"]
    }
  ],
  "total": 3
}
```
