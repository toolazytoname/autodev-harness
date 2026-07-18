# OD HTML → uni-app 节点映射表

> OD HTML 翻译成 uni-app + Vue 3 单文件组件 (.vue) + 微信云开发的完整对照表。
>
> 本表是 `agents/generator-uniapp.md` 的 §A Input 拼接到 prompt 里的内容,也是 `agents/reviewers/uniapp.md` 校验代码的反查清单。

---

## 1. 总体项目结构

| OD HTML 原型 | uni-app 项目结构 | 说明 |
|---|---|---|
| `opendesign/*.html` (5 个独立页面) | `src/pages/<page>/<page>.vue` (5 个 .vue 单文件) | 每页一个目录,Vue SFC 容纳 template + script + style |
| `opendesign/shared.css` | `src/uni.scss` + `src/static/css/tokens.scss` | uni-app 全局样式入口,`uni.scss` 自动注入;颜色 / 间距 token 放 `tokens.scss` |
| `opendesign/shared.js`(顶层 const) | `src/common/data.js` + `src/store/index.js` | 静态数据(学生 / 班级 / 考期字典)放 `common/data.js`;运行时可变数据走 Pinia store |
| `opendesign/tabbar.html` 的 `.tabbar` 段 | `src/pages.json` 的 `tabBar` 字段 | uni-app 用配置而非模板生成 tabbar |
| `opendesign/*.html` 里的 inline `<script>` | `src/common/*.js` 纯函数 | 计算 / 格式化 / 图表等拆出 |

---

## 2. 标签翻译(HTML → uni-app)

uni-app 不是 HTML,**但跨端编译器会把 Vue 模板编译成各端对应语法**(小程序用 view, H5 用 div, nvue 用原生)。为了一致,**统一用 uni-app 跨端组件**:

| OD HTML | uni-app 模板 | 说明 |
|---|---|---|
| `<div>` | `<view>` | 跨端通用容器;在小程序端对应 `<view>`,在 H5 端编译成 `<div>` |
| `<span>` / `<p>` / `<text>`(内联) | `<text>` | 跨端通用文本;**不要用 `<span>`**(H5 编译后才转 div,小程序端会报错) |
| `<h1>` `<h2>` `<h3>` | `<text class="h1">` + 全局 CSS | uni-app 没有 h1~h6 概念,样式交给 `.h1` `.h2` class |
| `<button onclick="x">` | `<button @click="x">` | Vue 事件绑定 |
| `<button bindtap="x">`(误用) | **禁止** — `bindtap` 是原生小程序语法,uni-app 用 `@click` | reviewer 会报错 |
| `<input oninput="x">` | `<input @input="x" :value="v" />` | uni-app 是单向绑定;**不要**用 v-model 双向(底层不跨端) |
| `<img src="x">` | `<image src="x" mode="aspectFit" />` | uni-app 用 `<image>` 不是 `<img>`,有 `mode` 控制裁剪 |
| `<a href="x">` | `<navigator url="/pages/foo/foo" open-type="navigate">` 或 `@click="$nav.to(...)"` | 跨端路由;不要直接用 `<a>`(H5 编译后才生效) |
| `<select>` / `<option>` | `<picker :range="options" @change="onChange">` | 跨端用 picker 组件;**不要**用原生 select |
| `<input type="checkbox">` | `<checkbox :checked="v" @change="onChange">` 或 `<switch>` | checkbox / switch 都行,看场景 |
| `<ul>` `<li>` | `<view class="list">` + `<view class="item" v-for>` | uni-app 没有 ul/li,样式靠 class |
| `<dialog>` `<modal>` | uni-ui `<uni-modal>` 或自写 `.scrim + .sheet` | 弹层用 uni-ui 或自定义 |

---

## 3. 指令 / 表达式

| OD HTML(原生 JS) | uni-app 模板 | 说明 |
|---|---|---|
| `<div v-for="x in xs">{{x}}</div>` | `<view v-for="(x, i) in xs" :key="i">{{x}}</view>` | Vue 标准,**:key 必须有** |
| `<div v-if="cond">` | `<view v-if="cond">` | 标准 Vue 条件渲染 |
| `<div v-else-if>` / `v-else` | `<view v-else-if>` / `<view v-else>` | 链式条件 |
| `<div v-show="cond">` | `<view v-show="cond">` | 频繁切换用 v-show(不销毁) |
| `{{x}}` 内联 | 同样 `{{x}}` | mustache 语法保留 |
| `:attr="x"` 属性绑定 | 同样 `:attr="x"` | 保留 |
| `class="a {{x ? 'b' : ''}}"` | `:class="{b: x}"` | 不要字符串拼接,用对象语法 |
| `style="color: {{c}}"` | `:style="{color: c}"` | 同上 |

---

## 4. OD 公共组件 → uni-app 组件

| OD 原型组件 | uni-app 实现 | 说明 |
|---|---|---|
| `.appbar`(顶栏 + 返回 + 标题) | `src/components/AppBar.vue` + 注册全局 | 用 props 传 title / back |
| `.searchbar`(搜索框) | `src/components/SearchBar.vue` 或 uni-ui `<uni-search-bar>` | 优先 uni-ui(已封装) |
| `.filters`(筛选条) | `src/components/Filters.vue` 自定义 | OD 的 chip + popover 翻译成 picker |
| `.card`(信息卡片) | `src/components/Card.vue` + slot | 用 Vue slot 接收内容 |
| `.sheet`(底部弹出) | 自定义 `<view class="sheet" v-if="open">` + transition | uni-ui 没有原生 sheet,自写 |
| `.scrim`(遮罩) | `<view class="scrim" v-if="open" @click="close">` | 同上,自写 |
| `.tabbar`(底部导航) | **不要写模板**;在 `src/pages.json.tabBar.list` 配 | uni-app 原生支持 |
| SVG 折线/柱/环图 | `<rich-text :nodes="lineChart(data)" />` | 图表函数来自 `src/common/charts.js` |
| `<table>` (表格) | 自写 `<view class="table">` 网格 | uni-app 没有 table 组件;**慎用**(iOS 渲染不稳定) |

---

## 5. 状态管理

| OD 原型 | uni-app 实现 | 说明 |
|---|---|---|
| `localStorage.setItem('role', 'coach')` | `uni.setStorageSync('role', 'coach')` | 封装在 `src/common/storage.js` |
| `localStorage.getItem('role')` | `uni.getStorageSync('role')` | 同上 |
| 顶层 `let role = ...`(单例) | Pinia store `useRoleStore()` 或 `reactive()` | MVP 用 reactive,后期切 Pinia |
| `<div v-show="role==='coach'">` | `<view v-if="role==='coach'">` | 读 store 或 reactive 变量 |

---

## 6. 数据 / 业务函数

| OD 原型 | uni-app 位置 | 约束 |
|---|---|---|
| 顶层 `const STUDENTS = [...]` | `src/common/data.js` `export const STUDENTS = [...]` | 纯 ES module,无 uni.* |
| 顶层 `function fmtTime(s) {...}` | `src/common/format.js` `export function fmtTime(s) {...}` | 纯函数 |
| 顶层 `function judge(actual, line) {...}` | `src/common/format.js` 或 `judge.js` | 同上 |
| 顶层 `function lineChart(pts) {...}` | `src/common/charts.js` `export function lineChart(pts) {...}` | 返回 SVG 字符串 |
| 顶层 `function promo(student) {...}` | `src/common/promo.js`(业务规则) | 复杂业务规则单独拆文件 |
| `localStorage` 操作 | `src/common/storage.js`(uni.* 白名单) | **reviewer 唯一允许 uni.* 的 common 文件** |

---

## 7. 路由

| OD 原型 | uni-app 实现 | 说明 |
|---|---|---|
| `window.location.href = 'student-detail.html'` | `uni.navigateTo({url:'/pages/student-detail/student-detail?id='+id})` | 跨端统一 API |
| `<a href="x.html">` | `<navigator url="/pages/x/x">` 或 `@click="$nav.to(...)"` | 跨端链接 |
| tab 切换 | 在 `src/pages.json.tabBar` 配,无需手动调 | 编译器自动处理 |
| 返回上一页 | `uni.navigateBack({delta:1})` | 跨端统一 |

---

## 8. 样式 / Token

| OD 原型 | uni-app 位置 | 说明 |
|---|---|---|
| `shared.css` 里的 `--aqua: oklch(...)` | `src/uni.scss` `$aqua: #5BB5D8;`(oklch → hex 映射) | uni.scss 自动注入全局 |
| `--font: -apple-system, ...` | `$font: -apple-system, ...;` | 同上 |
| `--radius: 16px` | `$radius: 16px;` | 同上 |
| `px` 单位 | `rpx`(750rpx = 屏宽) | **全站统一 rpx**,跨端一致 |
| `rem` | 用 rpx 替代 | 跨端编译不识别 rem |
| `@media (max-width: 768px)` | uni-app 默认 mobile 优先,需要 H5 响应式才写 | H5 编译时才需要 |

### OKLCH → HEX 映射参考(鱼跃 YuYue 项目)

| OD token | OKLCH | 跨端 hex 近似 |
|---|---|---|
| `--aqua` | `oklch(72% 0.12 220)` | `#5BB5D8`(水蓝) |
| `--orange` | `oklch(78% 0.15 50)` | `#F5A86B`(浅橙) |
| `--pass` | `oklch(75% 0.18 145)` | `#7BC97E`(达标绿) |
| `--warn` | `oklch(80% 0.18 85)` | `#F2D05E`(接近黄) |
| `--fail` | `oklch(70% 0.05 250)` | `#9AA5B1`(未达灰) |
| `--ink` | `oklch(20% 0.02 250)` | `#2A323C`(主文字) |

**为什么改 hex**:uni-app 在小程序端 CSS 解析对 `oklch()` 支持不稳定(2024 测试过,部分基础库版本报错),保险用 hex。**保留 token 名字**,值改写即可,后期若编译器支持升级再回切 oklch。

---

## 9. 后端 / 数据流(微信云开发)

OD 是纯前端 mock,uni-app + wx.cloud 是真后端:

| OD 原型(纯前端) | uni-app + wx.cloud | 说明 |
|---|---|---|
| `STUDENTS = [{...}]` 内联 | 启动时 `wx.cloud.callFunction({name:'seedStudents'})` 灌进云数据库 `students` 集合 | `seedStudents` 云函数读 OD `data/*.xlsx` 灌数据 |
| `localStorage.setItem('corrections', ...)` | `wx.cloud.database().collection('score_records').add({data})` | 写操作走云数据库 |
| `localStorage.getItem('corrections')` | `wx.cloud.database().collection('score_records').where({studentId}).get()` | 读操作走云数据库 |
| 角色判断(写死 `'coach'`) | `App.vue.onLaunch` 调 `wx.cloud.callFunction({name:'login'})` → 返回 `role` 存 Pinia | 真实鉴权 |
| 批量导入 Excel(OD 假按钮) | 上传到云存储 `wx.cloud.uploadFile` → 云函数 `parseExcel` 解析 → 灌数据库 | MVP 阶段可先纯前端 xlsx 解析,后期接云函数 |
| 导出单人海报(OD 假按钮) | `<canvas>` + `uni.canvasToTempFilePath` → 保存到相册 | 真导出 |

---

## 10. 跨端差异 / 注意点

| 场景 | 微信小程序 | H5 | 建议 |
|---|---|---|---|
| 路由 | `wx.navigateTo` | `history.pushState` | 用 `uni.navigateTo` 跨端 |
| 存储 | `wx.setStorageSync` | `localStorage` | 用 `uni.setStorageSync` 跨端 |
| 网络 | `wx.request` | `fetch` | 用 `uni.request` 或直接 `fetch`(uni-app 抹平) |
| 分享 | `wx.showShareMenu` + `onShareAppMessage` | `navigator.share` 或复制链接 | uni-app 编译时自动注入 |
| 扫码 | `wx.scanCode` | 浏览器 BarcodeDetector | MVP 只在小程序端启用,`uni.scanCode` |
| 选择文件 | `wx.chooseMessageFile` | `<input type="file">` | `uni.chooseMessageFile`(小程序) / `uni.chooseImage`(H5) |
| 定位 | `wx.getLocation` | `navigator.geolocation` | `uni.getLocation` 跨端 |

**MVP 重点**:微信小程序端 + H5 预览。**iOS / Android 暂时不出包**(等核心流程跑通再考虑)。`vue.config.js` / `vite.config.js` 配 `process.env.UNI_PLATFORM` 分支即可。

---

## 11. 测试(uni-automator)

| 原生小程序测试 | uni-app 测试 | 说明 |
|---|---|---|
| `require('miniprogram-automator')` | `const {init, ...} = require('@dcloudio/uni-automator')` | runtime 不同 |
| `await automator.launch({cliPath, projectPath})` | `await init({platform:'mp-weixin', projectPath})` | platform 字符串 |
| `const page = await mini.currentPage()` | `const page = await program.currentPage()` | API 名不同 |
| `await page.waitFor(500)` | 同样 `await page.waitFor(500)` | 兼容 |
| `expect(await page.$('view.card')).toBeTruthy()` | 同样 | 选择器语法兼容 |

测试代码放 `tests/uni-automator/*.spec.js`,跑 `npx uni-automator tests/uni-automator/<id>.spec.js`。

---

## 12. 迁移速查(从原 miniprogram 方案迁来)

| 原 miniprogram-scaffold | uni-app scaffold |
|---|---|
| `miniprogram/app.js` | `src/main.js` + `src/App.vue` |
| `miniprogram/app.json` | `src/pages.json` + `src/manifest.json` |
| `miniprogram/app.wxss` | `src/uni.scss`(全局)+ 各 .vue `<style scoped>` |
| `miniprogram/pages/<p>/<p>.{wxml,wxss,json,js}` × 4 文件 | `src/pages/<p>/<p>.vue` × 1 文件 |
| `miniprogram/utils/{data,format,charts,storage}.js` | `src/common/{data,format,charts,storage}.js`(目录从 utils 改 common 是 uni-app 约定) |
| `miniprogram/shared/token.wxss` | `src/uni.scss`(变量定义) |
| `miniprogram/shared/role.js` | `src/store/role.js`(Pinia) 或 `src/common/role.js` |
| `tests/automator/_smoke.spec.js` | `tests/uni-automator/_smoke.spec.js` |
| (无) | `cloudfunctions/`(新增目录,装 wx.cloud 云函数) |

---

## 13. 反模式(reviewer 会报错)

| 反模式 | 原因 |
|---|---|
| 在 `<template>` 里直接写 `<div>` `<span>` | uni-app 跨端会编译失败,统一用 `<view>` `<text>` |
| 用 `bindtap` / `bindinput` | 原生小程序语法,uni-app 用 `@click` `@input` |
| 用 `wx:for` / `wx:if` | 原生小程序语法,uni-app 用 `v-for` / `v-if` |
| 把云函数调用写在 `src/common/*.js` | common 必须纯函数,云函数封装放 `src/common/cloud.js`(白名单) |
| 在 page `<script setup>` 里直接调 `wx.cloud.database()` | 应该先 import `cloud.js` 的封装 |
| 用 `localStorage` 直接读写 | 用 `uni.setStorageSync` / `uni.getStorageSync`,封装在 `src/common/storage.js` |
| 写 TS / 装 vue-tsc / .ts 后缀 | MVP 不需要,保持纯 JS + JSDoc |
| 装 Vant / Element UI / Ant Design Vue | uni-app 跨端只配 `@dcloudio/uni-ui`,其他 UI 库会编译失败 |
| 把所有页面写在一个 .vue 里 | 单文件组件每页一个 .vue,放 `src/pages/<p>/<p>.vue` |

---

## 14. 文件清单(MVP 落地时必备)

```
src/
├── main.js                      # Vue 入口(createSSRApp + Pinia)
├── App.vue                      # 根组件(onLaunch 调 wx.cloud.init + login)
├── manifest.json                # 跨端配置(appid / 编译目标 / 权限)
├── pages.json                   # 路由 + tabBar
├── uni.scss                     # 全局 SCSS 变量(颜色 / 间距 / 字号)
├── pages/
│   ├── index/index.vue          # 首页(导航卡)
│   ├── class-overview/class-overview.vue
│   ├── students/students.vue
│   ├── students/student-detail.vue  # 重点可视化页
│   └── profile/profile.vue
├── components/
│   ├── AppBar.vue
│   ├── Card.vue
│   ├── Filters.vue
│   └── Scrim.vue
├── common/
│   ├── data.js                  # STUDENTS / CLASSES / TERMS 字典
│   ├── format.js                # fmtTime / fmtDiff / judge
│   ├── charts.js                # lineChart / barChart / donut(返回 SVG)
│   ├── storage.js               # uni.setStorageSync 封装(白名单)
│   └── cloud.js                 # wx.cloud.callFunction 封装(白名单)
├── store/
│   ├── index.js                 # Pinia 入口
│   ├── role.js                  # 角色状态(教练 / 家长)
│   └── students.js              # 学员列表状态
└── static/
    ├── logo.png                 # 俱乐部 Logo
    └── css/tokens.scss          # CSS 变量(供 uni.scss 引用)

cloudfunctions/
├── login/                       # 鉴权(openid → 角色)
│   ├── index.js
│   └── package.json
├── seedStudents/                # 从 OD data/*.xlsx 灌数据
│   ├── index.js
│   └── package.json
├── addStudent/                  # 教练增删改查
├── updateScore/                 # 成绩写入 / 更正
└── getClassOverview/            # 班级总览查询

tests/
└── uni-automator/
    ├── _smoke.spec.js
    └── <task-id>.spec.js
```

---

## 参考资料

- uni-app 官方文档:https://uniapp.dcloud.net.cn/
- uni-ui 组件库:https://uniapp.dcloud.net.cn/component/uniui/uni-ui.html
- 微信云开发:https://developers.weixin.qq.com/miniprogram/dev/wxcloud/basis/getting-started.html
- uni-automator:https://uniapp.dcloud.net.cn/worktile/auto/h5-control.html
- Vue 3 文档:https://cn.vuejs.org/