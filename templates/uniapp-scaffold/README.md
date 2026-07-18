# uniapp-scaffold

uni-app + Vue 3 + Vite 跨端应用脚手架。一套代码同时输出 **微信小程序** + **H5** 预览(后期可扩 iOS/Android)。

后端:**微信云开发 wx.cloud**(云函数 + 云数据库 + openid 鉴权),无需自建服务器。

## 结构

```
src/
├── main.js                  # Vue 入口(createSSRApp + Pinia)
├── App.vue                  # 根组件(onLaunch 调 wx.cloud.init + login)
├── manifest.json            # 跨端配置(appid / 编译目标 / 权限)
├── pages.json               # 路由 + tabBar
├── uni.scss                 # 全局 SCSS 变量(颜色 / 间距 / 字号)
├── pages/                   # 5 个 page 单文件组件(Vue SFC)
│   ├── index/index.vue
│   ├── class-overview/class-overview.vue
│   ├── students/students.vue
│   ├── students/student-detail.vue
│   └── profile/profile.vue
├── common/
│   ├── data.js              # 静态数据(STUDENTS / CLASSES / TERMS)— 纯函数
│   ├── format.js            # fmtTime / fmtDiff / judge — 纯函数
│   ├── charts.js            # lineChart / barChart / donut(返回 SVG)— 纯函数
│   ├── storage.js           # uni.setStorageSync 封装 — uni.* 白名单
│   └── cloud.js             # wx.cloud.callFunction 封装 — wx.cloud.* 白名单
├── store/
│   ├── index.js             # Pinia 入口
│   └── role.js              # 角色状态(教练 / 家长)
└── static/
    ├── logo.png             # 俱乐部 Logo
    └── css/tokens.scss      # CSS 变量(供 uni.scss 引用)

cloudfunctions/
├── login/                   # 鉴权(openid → 角色)
├── seedStudents/            # 从 OD data/*.xlsx 灌数据
├── addStudent/              # 教练增删改查
└── updateScore/             # 成绩写入 / 更正

tests/
└── uni-automator/
    ├── _smoke.spec.js
    └── <task-id>.spec.js    # 每个 task 一个
```

## 使用

### 安装依赖

```bash
npm install
# 或
pnpm install
```

### 运行

```bash
# 微信小程序(开发模式)
npm run dev:mp-weixin

# H5 预览(开发模式)
npm run dev:h5

# 构建
npm run build:mp-weixin  # 产物在 dist/dev/mp-weixin
npm run build:h5         # 产物在 dist/build/h5
```

### 测试

```bash
# 跑全部 uni-automator 测试
npx uni-automator tests/uni-automator/_smoke.spec.js

# 跑某个 task 的测试
npx uni-automator tests/uni-automator/<task-id>.spec.js

# skip runtime(纯 lint / require 检查)
UNI_AUTOMATOR_SKIP_RUNTIME=1 node tests/uni-automator/_smoke.spec.js
```

### 微信开发者工具打开

把 `dist/dev/mp-weixin` 目录拖进微信开发者工具(导入项目,AppID 选「测试号」即可)。

## 评审硬规则(uni-app reviewer 5 条)

1. **`<task-id>.spec.js` 存在** — `test -f tests/uni-automator/<task-id>.spec.js`
2. **`src/common/*.js` 不含 `uni.*` / `wx.*`(除 storage.js / cloud.js)** — `grep -nE '\b(uni|wx)\.[A-Za-z_]' src/common/data.js src/common/format.js src/common/charts.js`
3. **page Vue SFC ≤ 100 行** — `wc -l src/pages/*/*.vue`
4. **`src/pages.json` 包含所有 page** — 新增 page 必须同步加
5. **acceptance 步骤 ↔ uni-automator it() 对应**

## 从 Open Design HTML 翻译

`agents/generator-uniapp.md` + `docs/OD-TO-UNIAPP-MAPPING.md` 提供完整翻译规则。

## 微信云开发

云函数目录 `cloudfunctions/`,部署到云端:

```bash
# 在微信开发者工具里右键 cloudfunctions/login → 上传并部署
# 部署后即可在小程序端通过 wx.cloud.callFunction({name:'login'}) 调用
```

数据库集合设计:
- `students` — 学员(教练增删改查,家长只读自己绑定的孩子)
- `classes` — 班级(金鱼/海豚/旗鱼/蛟龙/竞训)
- `terms` — 考期(2025-10 / 2025-11 / ...)
- `score_records` — 成绩记录(students × terms × 项目)
- `users` — 用户(按 openid 查 role)

MVP 阶段先用 OD `data/*.xlsx` 通过 `seedStudents` 云函数灌数据,后期改手工录入。