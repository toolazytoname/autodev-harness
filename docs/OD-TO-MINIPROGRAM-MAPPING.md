# OD HTML → 微信小程序节点映射表

`autodev-harness` 的 generator-miniprogram 把 Open Design 导出的 HTML
原型翻译成微信小程序源码。这张表是**对照表** — 左列 OD 写法,
右列 miniprogram 写法,中间是翻译规则。

约定:
- OD HTML 用 `<div> / <button> / <input>`,miniprogram 用 `<view> /
  <button> / <input>`(只有 div 替换,其他标签多数直接对应)
- OD JS 是浏览器全局 + `localStorage`,miniprogram 是 `wx.*` +
  `wx.getStorageSync/setStorageSync`
- OD 路径写 `src="shared.css"`,miniprogram 通过 `@import` 或
  `app.wxss` 的全局 token(已在 scaffold 处理)

---

## 1. 顶层结构

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `<div class="stage">` | 不需要 | OD 用 stage 框定可视区域;小程序整个屏幕就是 page |
| `<div class="phone">` | `<page>` 容器 | 小程序的 page 自动包,无需手写 |
| `<div class="phone__island">` | `<view class="island">` | 灵动岛/状态栏模拟;可保留作装饰 |
| `<div id="statusbar">` | `<view class="statusbar">` | 内联到 page wxml 顶部 |
| `<div id="tabbar">` | `app.json.tabBar` | **不在 wxml 里**,必须迁到 app.json |
| `<div class="screen">` | page 根 `<view class="page">` | 滚动容器语义保留 |

---

## 2. 导航 / 顶部栏

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `<div class="appbar">` | `<view class="appbar">` | 直接对应 |
| `<div class="appbar__title">` | `<view class="appbar__title">` | |
| `<button class="appbar__act" onclick="openEdit()">添加</button>` | `<button class="appbar__act" bindtap="openEdit">添加</button>` | `onclick` → `bindtap` |
| `onclick="..."` (任何元素) | `bindtap="..."` | 全部替换 |
| `<nav class="tabbar">` + `TAB_ICONS` JS 常量 | `app.json.tabBar.list` 数组 | OD 的 tabbarHTML JS 函数翻译为 app.json 配置 |

**`app.json` 模板片段**:

```json
{
  "tabBar": {
    "color": "#8b95a3",
    "selectedColor": "#1d5da3",
    "backgroundColor": "#ffffff",
    "list": [
      {"pagePath": "pages/index/index", "text": "首页"},
      {"pagePath": "pages/students/students", "text": "学员"},
      {"pagePath": "pages/class-overview/class-overview", "text": "成绩"},
      {"pagePath": "pages/profile/profile", "text": "我的"}
    ]
  }
}
```

---

## 3. 表单控件

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `<input oninput="render()">` | `<input bindinput="onSearch" value="{{q}}">` | `oninput` → `bindinput`,值绑定到 data |
| `<input placeholder="搜索...">` | `<input placeholder="搜索...">` | 直接对应 |
| `<button onclick="x()">` | `<button bindtap="x">` | 同上 |
| `<select> / <option>` | `<picker>` | OD 没用 select,如有需要查 picker 文档 |

---

## 4. 列表 / 渲染

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `.map(cardHTML)` (JS 拼字符串) | `wx:for="{{list}}"` + `wx:key="id"` | OD 在 JS 里拼 HTML,小程序在 wxml 里循环 |
| `innerHTML = list.map(cardHTML).join('')` | `this.setData({list: data})` | 状态从 JS 字符串变成 data 字段 |
| `class="card" style="padding:14px 15px"` | `class="card" style="padding:14px 15px"` | 内联 style 可保留(但建议迁到 wxss) |
| `<a href="other.html">` | `<navigator url="/pages/other/other">` | 内部跳转 |
| `location.assign('other.html')` | `wx.navigateTo({url: '/pages/other/other'})` | JS 跳转迁到 page handler |

---

## 5. 弹层 / 模态

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `<div class="scrim" onclick="scrimBg(event)">` | `<view class="scrim" wx:if="{{editOpen}}" bindtap="closeScrim">` | `onclick` → `bindtap`,显示状态绑 data |
| `<div class="sheet">` | `<view class="sheet" catchtap="noop">` | `catchtap` 阻止冒泡(对应 `event.stopPropagation()`) |
| `el.classList.add('open')` | `this.setData({editOpen: true})` | 状态从 className 变成 boolean |
| `setTimeout(() => el.classList.remove('show'), 1800)` | `setTimeout(() => this.setData({toast: ''}), 1800)` | toast 同理 |

---

## 6. 角色门控

| OD HTML | miniprogram | 说明 |
|---|---|---|
| `document.body.setAttribute('data-role', r)` | `this.setData({role: r})` | data-role → data.role |
| `class="coach-only"` (CSS 隐显) | `wx:if="{{role==='coach'}}"` | 小程序没用 CSS 属性选择器 |
| `localStorage.getItem('yy_role')` | `wx.getStorageSync('yy_role')` (via `shared/role.js`) | 通过 `getRole()` 封装函数调用 |

**重要**:页面加载时必须 `onLoad` 调 `getRole()` 把 role 写到 data。OD 的 `initRole()` 是在 body 上设属性,小程序里没 body 概念。

---

## 7. SVG 图表(折线 / 柱状 / 环形)

OD 用内联 SVG(`<svg viewBox="...">...</svg>` 直接嵌入 HTML),小程序不支持内联 SVG。需要把 SVG 字符串生成逻辑翻译到 `miniprogram/utils/charts.js` 纯函数,然后用 `<rich-text nodes="{{chart(data)}}" />` 渲染。

| OD HTML | miniprogram |
|---|---|
| `<svg>...</svg>` 内联 | `<rich-text nodes="{{lineChart(points, line)}}" />` |
| `lineChart(points, line)` (OD shared.js) | `utils/charts.js` 导出同名函数,**纯函数,返回 SVG 字符串** |
| `var(--aqua)` 等 CSS 变量 | hex 映射(见 `shared/token.wxss`) |
| `<svg class="chart" viewBox="0 0 322 176">` | `<rich-text nodes="{{...}}" />` 自动保留 SVG 结构 |

**token 映射表**(OD OKLCH → 微信 wxss hex,见 `shared/token.wxss`):

| OD token | hex | 用途 |
|---|---|---|
| `var(--aqua)` | `#2a73c4` | 主色:泳池蓝 |
| `var(--aqua-600)` | `#1d5da3` | 主色深 |
| `var(--pass)` | `#4ba66c` | 达标:绿 |
| `var(--pass-tint)` | `#d4f0dd` | 达标背景 |
| `var(--near)` | `#d4b85a` | 接近:黄 |
| `var(--near-tint)` | `#f5edd0` | 接近背景 |
| `var(--miss)` | `#828b96` | 未达:灰 |
| `var(--ink)` | `#364152` | 文字主色 |
| `var(--muted)` | `#8b95a3` | 文字次要 |
| `var(--faint)` | `#b8c0cc` | 文字最浅 |
| `var(--surface)` | `#ffffff` | 卡片背景 |
| `var(--bg)` | `#f1f5f9` | 页面背景 |

**为什么用 hex 而不是 `oklch()`**:微信 wxss 对 `oklch()` 函数的支持参差不齐(部分 IDE 版本报错、部分忽略),hex 在所有版本都稳定。保留 token 名(`var(--aqua)` 在 wxml 里写)以维持 OD 设计语言,只在 wxss 文件里把 token 值定义为 hex。

---

## 8. 数据存储

| OD JS | miniprogram |
|---|---|
| `const STUDENTS = [...]` (顶层 const) | `utils/data.js` 用 `module.exports = {STUDENTS, ...}` |
| `localStorage.getItem(key)` | `wx.getStorageSync(key)` (via `utils/storage.js` 或 `shared/role.js`) |
| `localStorage.setItem(key, val)` | `wx.setStorageSync(key, val)` |
| `localStorage.getItem('yy_role') \|\| 'coach'` | `getRole()` (封装在 `shared/role.js`) |

**约束**:`utils/data.js / format.js / charts.js` **禁止**调 wx.*(reviewer 强约束),所以这些模块不能直接调 storage。需要 storage 的函数都通过 `utils/storage.js` 或 `shared/role.js` 暴露的封装函数访问。

---

## 9. 业务算法翻译

OD 的 `promo(student)`(晋级达标计算)、`series(finalSec, dropPct, missMask)`(历史成绩生成)、`judge(actual, line)`(达标判定)等都是**纯函数**,1:1 翻译到 `utils/` 模块:

| OD JS 函数 | miniprogram 文件 | 备注 |
|---|---|---|
| `STUDENTS / CLASSES / TERMS` 数据 | `utils/data.js` | 直接 `module.exports` |
| `promo(stu)` 晋级计算 | `utils/data.js` 或独立 `utils/promo.js` | 纯函数,可加单元测试 |
| `series(final, drop, mask)` | `utils/data.js` | 同上 |
| `judge(actual, line)` | `utils/format.js`(已在 scaffold) | 已在 scaffold,无需翻译 |
| `fmtTime / fmtDiff` | `utils/format.js`(已在 scaffold) | 已在 scaffold |
| `getEffectiveScore` 等含 storage 的 | `utils/storage.js`(wx.* 白名单) | 通过 storage.js 调 wx.getStorageSync |

---

## 10. 自动化测试

| OD 测试 | miniprogram 测试 |
|---|---|
| 浏览器手动跑 + console.log | `tests/automator/<task-id>.spec.js` 用 `miniprogram-automator` |
| `<script>` 里写 `console.assert(x)` | `describe('pure functions', () => { it('...', () => { assert.strictEqual(...) }) })` |
| 浏览器 DevTools 截图 | `page.screenshot({path: ...})`(miniprogram-automator 暴露) |

**模板**:`tests/automator/_smoke.spec.js`(已在 scaffold)展示了
- 怎么 `automator.launch({projectPath, cliPath})`
- 怎么 `miniProgram.reLaunch('/pages/...')`
- 怎么 `require('../../miniprogram/utils/...')` 测纯函数
- 怎么用 `MINIPROGRAM_SKIP_RUNTIME=1` 在 Linux CI 跳过 runtime

generator 在每个 task 写自己的 `<task-id>.spec.js`,**继承** `_smoke.spec.js` 的 `beforeAll/afterAll` 模式,只换 `it(...)` 块。

---

## 11. 已知不做(留给未来 T-XX)

- **分包加载**(subpackages):OD 项目不分包,小程序可全量加载;以后真要分包再加
- **自定义组件**(`usingComponents`):OD 是 flat HTML,小程序也用 flat `<view>`;以后若有复用组件再抽
- **wxs / WXS**:OD 没用 WXS,纯 JS 工具函数够用
- **自定义 tabbar**(`custom-tab-bar`):OD 是普通 tabbar,小程序也用普通
- **Behaviors**(`wx.behaviors`):OD 没用 mixin,小程序也暂不引入
- **TypeScript**:WeChat IDE 不识别 .ts;纯 JS + JSDoc

如果 OD 项目未来扩展触发以上需求,这张表再加章节。