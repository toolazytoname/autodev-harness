# 微信小程序生态库选型指南

`autodev-harness` 的 generator-miniprogram 在翻译 OD HTML 时,需要选
UI baseline(组件库)和图表方案。这张表是**选型矩阵**,给 researcher
agent 在 §四 复用决策表里填写决策时用,也给 generator 在 task 里
实际引入时用。

---

## 候选库

### 1. Tencent/weui-wxss(微信官方设计语言)

- **仓库**:https://github.com/Tencent/weui-wxss
- **star**:~1.6k
- **依赖**:零(`@import 'weui.wxss'` 即用)
- **覆盖**:button / cell / dialog / toast / article / forms / grid / list / panel / preview
- **维护**:腾讯官方维护,稳定
- **何时选**:页面 ≤ 5、组件需求轻、追求"像微信"的原生观感
- **不选**:页面多 + 表单复杂 + 需要丰富交互(没有 modal drawer / sticky 等高级组件)

### 2. youzan/vant-weapp(有赞,生态最大)

- **仓库**:https://github.com/youzan/vant-weapp
- **star**:~18k(微信组件库最大)
- **依赖**:npm + 构建步骤(`npm i` 后 `dist/` 引入)
- **覆盖**:ActionSheet / Dialog / Dropdown / Loading / Notify / Picker / Popup / Search / Sidebar / Step / Sticky / SubmitBar / SwipeCell / Switch / Tab / Tag / Toast / TreeSelect ... (60+ 组件)
- **维护**:有赞官方 + 社区 PR,活跃
- **何时选**:业务复杂(电商/订单/营销场景)、表单/弹窗密集、组件需求多
- **不选**:页面极简、不想引入构建步骤

### 3. TDesignOfficial/Lin UI(腾讯 TDesign 微信版)

- **仓库**:https://github.com/TDesignOfficial/Lin UI
- **star**:~8k
- **依赖**:npm + 构建步骤
- **覆盖**:Avatar / Badge / Button / Card / Cell / Checkbox / Collapse / Divider / Empty / Form / Icon / Image / Input / Layout / Link / List / Loading / NoticeBar / Popup / Price / Progress / Radio / Search / Select / Skeleton / Stepper / Sticky / Switch / Tab / Tag / Toast / Transition ...
- **维护**:腾讯 TDesign 团队,2022 起持续更新
- **何时选**:已经用 TDesign 体系(web 端也是 TDesign)、需要统一设计语言
- **不选**:不想同时维护两套设计系统、或业务没有 TDesign 既有规范

### 4. wx-charts(老牌 SVG 图表)

- **仓库**:https://github.com/xiaolin3303/wx-charts
- **star**:~4k
- **依赖**:零(纯 JS)
- **覆盖**:line / column / pie / area / radar 等基础图表
- **维护**:半活跃(stale 风险,有 PR 但慢)
- **何时选**:真要用图表库
- **不选**:OD 项目自带 SVG(折线/柱/环,见 OD shared.js 的 lineChart/barChart/donut),`generator-miniprogram` 把这些 SVG 函数翻译到 `utils/charts.js` 就够用,优先用原生方案

---

## 选型矩阵

| 场景 | 推荐 | 备注 |
|---|---|---|
| 页面 ≤ 5 + 简单表单 | weui-wxss | 轻,零依赖,官方 |
| 页面 5-15 + 业务中等 | weui-wxss + 自写弹层 | 折中,基础组件靠 weui,弹层自写 |
| 页面 15+ + 电商/订单 | vant-weapp | 60+ 组件全覆盖 |
| 已有 TDesign web 端 | Lin UI | 设计语言一致 |
| 复杂图表需求 | 自写 `utils/charts.js` + 必要时 wx-charts | OD SVG 优先 |
| 角色系统(教练/家长) | 自写 `shared/role.js`(零依赖) | 不要让任何 UI 库替你管角色 |

---

## 选型时给 researcher agent 的具体动作

按 T-Bridge 规则,researcher 在 brief 含 miniprogram 信号时,§四 复用
决策表必须包含至少 2 项 miniprogram 库决策(可以全 drop 但**不允许**)，
参考上面矩阵写「理由」:

```markdown
| Tencent/weui-wxss | https://github.com/Tencent/weui-wxss | active | 70 | wrap | 5 page 都是 cell/list/button 标准组件,weui 覆盖 70%,剩余 30% 自写 |
| youzan/vant-weapp | https://github.com/youzan/vant-weapp | active | 90 | drop | 业务没有 60+ 组件需求,引入构建步骤不值 |
```

---

## generator-miniprogram 引用规则

当 §四 决策某项为 `wrap` 时,generator 在第一个 task 写:

```bash
# weui-wxss
cd miniprogram/
curl -L https://raw.githubusercontent.com/Tencent/weui-wxss/master/dist/style/weui.wxss -o weui.wxss
# 在 app.wxss 里加 @import './weui.wxss'
```

```bash
# vant-weapp
cd miniprogram/
npm init -y
npm i @vant/weapp -S --production
# 在 app.json 里:
#   "usingComponents": { "van-button": "@vant/weapp/button/index" }
```

不要**两个都引入**;选 baseline 的那个作为唯一 UI 框架,避免样式冲突。
OD 项目的 design token (`--aqua`, `--pass`, etc.) 通过 `shared/token.wxss`
覆盖库默认色 — 在 wxml 里仍然用 `var(--aqua)`,而 vant/weui 用
`--primary-color` 之类,需要 token 映射(参考
`docs/OD-TO-MINIPROGRAM-MAPPING.md` 第 7 节)。