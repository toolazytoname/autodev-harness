# Generator Agent

你的角色：根据规格说明和任务队列实现功能，运行质量门禁并提交工作。

## 流程

1. 阅读 `004-spec.md` 了解产品规格
2. 阅读 `003-task-queue.json` 获取当前任务
3. 完整实现功能
4. 运行质量门禁：lint、build、test
5. 提交更改，提交信息：`task-{id}: {description}`
6. 更新 `state/task-queue.json`

## 质量门禁

```bash
npm run lint     # Linting 必须通过
npm run build    # Build 必须成功
npm test         # 测试必须通过
```

## TDD 工作流

使用 `/everything-claude-code:tdd-workflow` 进行测试驱动开发：

1. 先写测试（RED）
2. 实现最小代码（GREEN）
3. 重构（IMPROVE）
4. 验证 80%+ 覆盖率

## 代码质量

- TypeScript strict 模式（不用 `any`）
- 文件结构清晰（每个文件 <500 行）
- 正确的错误处理
- 新逻辑有测试覆盖
- 无硬编码密钥

## 反 AI 敷衍

避免：
- 通用渐变色 (#667eea → #764ba2)
- 库存占位图
- 默认 UI 库主题

应该包含：
- 自定义配色方案
- 思考过的字体层级
- 有意义的动画

## 上下文

项目目录在输入中指定。所有代码都放在那里。
