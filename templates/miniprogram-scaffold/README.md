# miniprogram-scaffold

微信小程序空壳,由 `autodev-harness` 在 `--design-draft` 模式下 fork 到目标项目根目录。

## 用法

generator agent 在第一个 task 中执行:

```bash
# 把整个 scaffold 拷到目标 miniprogram 目录(在 worktree 里)
cp -r templates/miniprogram-scaffold/* miniprogram/
```

如果目标 miniprogram 目录已有文件,generator 应该**先询问人类**是否覆盖,而不是默默覆盖。

## 目录结构

```
miniprogram-scaffold/
├── app.js              # App({...}),全局入口 — 允许 wx.*
├── app.json            # 5 page 路径 + tabBar 配置
├── app.wxss            # 全局样式,导入 shared/token.wxss
├── sitemap.json        # 微信 sitemap 配置
├── project.config.json # IDE 项目配置
├── README.md           # 本文件
├── shared/
│   ├── token.wxss     # OD 的 OKLCH design token 移植(hex 映射)
│   └── role.js        # 角色(教练/家长)持久化 — 唯一 wx.* 白名单
├── pages/
│   ├── index/              # 首页
│   ├── class-overview/     # 班级成绩
│   ├── students/           # 学员管理(同目录放 student-detail)
│   ├── students/student-detail/  # 学员详情
│   └── profile/            # 我的
├── utils/
│   ├── data.js      # STUDENTS / CLASSES / TERMS — 纯函数,无 wx.*
│   ├── format.js    # fmtTime / fmtDiff / judge — 纯函数
│   ├── charts.js    # lineChart / barChart / donut(SVG 字符串)— 纯函数
│   └── storage.js   # getRole / readScoreCorrections — 唯一允许 wx.* 的 utils
└── tests/
    └── automator/
        └── _smoke.spec.js   # 烟雾测试:launch + 5 page + 纯函数
```

## Reviewer 约束(miniprogram reviewer 5 大硬规则)

scaffold 模板已**预合规**,generator 第一个 task 不应破坏这些规则:

1. **每个 page 文件 ≤ ~30 行逻辑** — 当前每个 page 的 `index.js` 只含空骨架 `Page({data:{}, onLoad(){}})`,留 30 行 buffer 给 generator 填
2. **utils/data.js / format.js / charts.js 不含 `wx.*`** — `storage.js` 是 wx.* 白名单(reviewer 文档允许)
3. **`tests/automator/_smoke.spec.js` 已存在** — generator 不要删,后续 task 写自己的 `<task-id>.spec.js`
4. **`app.json` 含 5 page 路径** — generator 新增 page 时要同步更新 `app.json.pages` 数组
5. **acceptance 步骤** — 后续 task 的 acceptance 字符串用 "点击 xxx 看到 yyy" 这种中文 BROWSER 描述(`harness/acceptance.py` 自动识别)

## 跑通烟雾测试(macOS)

```bash
cd <your-project>
npm install --save-dev miniprogram-automator
# 1. 打开 WeChat DevTools,打开本项目
# 2. Settings → Security → Service Port → Enable
# 3. 跑测试
node tests/automator/_smoke.spec.js
```

跳过 runtime(Linux CI):

```bash
MINIPROGRAM_SKIP_RUNTIME=1 node tests/automator/_smoke.spec.js
```