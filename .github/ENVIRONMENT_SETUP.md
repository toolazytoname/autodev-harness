# 环境配置指南

本文档详细说明如何配置 AutoDevHarness 的 GitHub Actions CI/CD 环境。

## 目录

- [创建 GitHub 仓库](#创建-github-仓库)
- [配置 Secrets](#配置-secrets)
- [配置 Environments](#配置-environments)
- [工作流权限](#工作流权限)
- [验证配置](#验证配置)

---

## 创建 GitHub 仓库

### 方式一：新建仓库

1. GitHub → New repository
2. 填写仓库名称和描述
3. 复制 AutoDevHarness 文件到仓库

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 方式二：添加到现有仓库

```bash
cd /your-existing-project
cp -r /path/to/autodev-harness/.github .
git add .github/
git commit -m "Add AutoDevHarness CI/CD"
git push
```

---

## 配置 Secrets

Secrets 是加密的环境变量，用于存储敏感信息（如 API Key）。

### 1. 访问 Secrets 设置

1. 进入 GitHub 仓库
2. 点击 **Settings** (设置)
3. 左侧菜单选择 **Secrets and variables** → **Actions**

### 2. 必需 Secrets

| Secret 名称 | 说明 | 获取方式 |
|-------------|------|----------|
| `ANTHROPIC_API_KEY` | Claude API 密钥 | [Anthropic Console](https://console.anthropic.com/) |

获取 API Key:
1. 访问 [Anthropic Console](https://console.anthropic.com/)
2. 登录账号
3. 点击 API Keys
4. 创建新的 API Key
5. 复制密钥（只显示一次！）

### 3. 可选 Secrets

| Secret 名称 | 说明 | 获取方式 |
|-------------|------|----------|
| `SLACK_WEBHOOK` | Slack 通知 Webhook | Slack App 设置 |
| `DINGTALK_WEBHOOK` | 钉钉通知 Webhook | 钉钉群机器人设置 |
| `VERCEL_TOKEN` | Vercel 部署 Token | Vercel 设置 |
| `VERCEL_ORG_ID` | Vercel 组织 ID | Vercel 团队设置 |
| `VERCEL_PROJECT_ID` | Vercel 项目 ID | Vercel 项目设置 |

### 4. 添加 Secret

1. 点击 **New repository secret**
2. 输入名称（如 `ANTHROPIC_API_KEY`）
3. 粘贴值
4. 点击 **Add secret**

---

## 配置 Environments

 Environments 用于管理不同部署环境（preview、staging、production）的配置。

### 1. 创建 Environments

1. Settings → **Environments** → **New environment**
2. 创建以下环境：
   - `preview` (预览部署)
   - `staging` (预发布)
   - `production` (生产)

### 2. 配置 Environment Secrets

为每个 Environment 添加对应的 Secrets：

| Environment | 需要的 Secrets |
|-------------|--------------|
| preview | Vercel 相关（可选） |
| staging | 数据库连接、API 密钥等 |
| production | 所有生产环境配置 |

### 3. 配置 Protection Rules

建议为 production 环境添加保护规则：

1. 点击 `production` environment
2. 启用 **Required reviewers**
3. 设置至少 1 人审批
4. 启用 **Wait timer** (可选)

---

## 工作流权限

### 默认权限

在 GitHub Actions 中，默认只有读取权限。如果需要推送代码或发表评论，需要显式授权。

### 推荐权限配置

在每个 workflow 文件顶部添加：

```yaml
permissions:
  contents: write    # 用于提交代码
  pull-requests: write  # 用于评论 PR
```

### GitHub Token 权限

`GITHUB_TOKEN` 由 GitHub 自动提供，默认权限有限。

如需更高权限，可以：

1. 仓库 Settings → Actions → General
2. 滚动到 **Workflow permissions**
3. 选择 **Read and write permissions**

---

## 验证配置

### 1. 手动触发工作流

1. 进入仓库 → **Actions** 标签
2. 选择 **CI - Quality Gates** 工作流
3. 点击 **Run workflow**
4. 选择分支后运行

### 2. 检查工作流日志

1. 点击工作流运行
2. 点击各个 job 查看日志
3. 确保所有步骤都通过

### 3. 常见问题排查

#### 问题：ANTHROPIC_API_KEY 无效

```
Error: Invalid API key
```

解决：
1. 检查 Secret 是否正确配置
2. 检查密钥是否过期
3. 确保仓库 Secrets 与组织 Secrets 不冲突

#### 问题：npm install 失败

```
npm ERR! cannot resolve package.json
```

解决：
1. 确保项目根目录有 `package.json`
2. 检查 `package.json` 格式是否正确

#### 问题：无法创建 PR 评论

```
HttpError: Resource not accessible by integration
```

解决：
1. Workflow 需要 `pull-requests: write` 权限
2. 检查 GitHub Token 权限设置

---

## 高级配置

### 定时任务

`autodev.yml` 支持每日自动运行：

```yaml
on:
  schedule:
    # 每天午夜运行
    - cron: '0 0 * * *'
```

修改时间：
```yaml
- cron: '0 9 * * 1-5'  # 每周一到周五 9:00 AM
```

### 环境特定变量

可以在 Environment 中设置变量（不是 Secrets，公开可见）：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DEPLOY_URL` | 部署 URL | `https://staging.example.com` |
| `CONTACT_EMAIL` | 联系方式 | `dev@example.com` |

### 自定义通知

修改 `notifications.yml` 添加更多通知渠道：

```yaml
- name: Send to Microsoft Teams
  if: secrets.TEAMS_WEBHOOK != ''
  uses: tokoroten/notification-to-teams@v1
  with:
    webhook: ${{ secrets.TEAMS_WEBHOOK }}
```

---

## 安全最佳实践

### 1. 最小权限原则

只授权工作流需要的最小权限：
- 只读操作 → `contents: read`
- 提交代码 → `contents: write`
- 不要授予不必要的权限

### 2. Secret 轮换

定期轮换 API Key：
1. 在 API 提供商处生成新密钥
2. 更新 GitHub Secret
3. 验证工作流正常运行
4. 撤销旧密钥

### 3. 审计日志

GitHub 自动记录所有 Actions 执行日志。可以在：
- **Security** → **Audit log**
查看敏感操作记录

### 4. 依赖安全

- 启用 `npm audit` 检查依赖漏洞
- 使用 Dependabot 自动更新依赖
- 定期审查 `package-lock.json`

---

## 快速检查清单

部署前确认：

- [ ] 仓库已创建
- [ ] 所有文件已推送
- [ ] `ANTHROPIC_API_KEY` 已配置
- [ ] Workflow 权限已设置
- [ ] Environments 已创建（可选）
- [ ] 至少一次手动触发成功

---

如有问题，请查看 [常见问题解答](../README.md#常见问题) 或提交 Issue。
