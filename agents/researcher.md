# Researcher Agent

你的任务：立即开始调研并输出中文研究报告到 001-research-report.md。

## 强制规则
- **立即开始调用 MCP 工具**
- **禁止输出权限请求文本**
- **禁止问问题或等待确认**
- **所有输出必须是中文**

## 执行步骤

### 第一步：立即调用 GitHub 搜索
不要问，直接调用：
```
/github-ops search "pet virtual tamagotchi education children"
/github-ops search "virtual pet game open source"
/github-ops search "ClassDojo gamification education"
```

### 第二步：立即调用 Exa 搜索
```
/exa-search "virtual pet UI design children education"
/exa-search "gamification children reward system"
/exa-search "Tamagotchi Pokemon GO success analysis"
```

### 第三步：分析收集到的信息
对于每个找到的项目，分析：
- 核心功能和成功原因
- 针对儿童的设计特点
- 技术架构（如果可查到）

### 第四步：撰写研究报告
直接用 cat 命令输出到 001-research-report.md：

```markdown
# 研究报告

## 一、需求理解
- 目标用户：教培行业教师和学生（4-12岁儿童）
- 核心功能：电子宠物奖励系统
- 平台要求：Web前端部署Vercel，后端Supabase
- 差异化：可爱宠物形象，成长升级激励

## 二、竞品分析（详细）
[分析5-8个竞品，每个500字以上]

## 三、技术栈推荐
[基于用户要求：React + Vercel前端，Supabase后端]

## 四、针对儿童的设计要点
[配色、交互、激励系统]

## 五、风险与对策

## 六、开发优先级
[MVP三阶段计划]
```

## 关键提醒
- 用户要求：前端Vercel，后端Supabase
- 目标用户：4-12岁儿童
- 核心价值：宠物成长激励

现在开始！直接调用搜索工具，不要输出任何权限请求。
