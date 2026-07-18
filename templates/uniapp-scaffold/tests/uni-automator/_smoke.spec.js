/**
 * tests/uni-automator/_smoke.spec.js — 烟雾测试
 *
 * 这个 spec 是 **基线**,每个 generator task 完成后,它的
 * 任务级 spec.js 应覆盖对应 acceptance 步骤,但 _smoke.spec.js
 * 永远跑 — 验证 uni-app 项目结构本身没坏。
 *
 * 跑法:
 *   - macOS + 微信开发者工具:npx uni-automator tests/uni-automator/_smoke.spec.js
 *   - skip runtime(纯 lint / require 检查):
 *     UNI_AUTOMATOR_SKIP_RUNTIME=1 node tests/uni-automator/_smoke.spec.js
 */

const path = require('path')

const SKIP_RUNTIME = process.env.UNI_AUTOMATOR_SKIP_RUNTIME === '1'

if (!SKIP_RUNTIME) {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const automator = require('@dcloudio/uni-automator')
  // 初始化 uni-app debug bridge(platform='mp-weixin' 需微信开发者工具运行)
  const platform = process.env.UNI_AUTOMATOR_PLATFORM || 'mp-weixin'
  const projectPath = path.resolve(__dirname, '../..')
  // Note: actual init() call below is wrapped in a function so the
  // smoke spec can be loaded without runtime present (uni-automator
  // throws when DevTools is not running).
  // eslint-disable-next-line no-unused-vars
  let program = null
  beforeAll(async () => {
    program = await automator.init({ platform, projectPath })
  }, 30000)
  afterAll(async () => {
    if (program) await program.close()
  })
}

describe('uni-app 项目结构', () => {
  it('package.json 存在', () => {
    const fs = require('fs')
    const p = path.resolve(__dirname, '../../package.json')
    expect(fs.existsSync(p)).toBe(true)
    const pkg = JSON.parse(fs.readFileSync(p, 'utf-8'))
    expect(pkg.dependencies).toHaveProperty('@dcloudio/uni-app')
    expect(pkg.dependencies).toHaveProperty('vue')
  })

  it('pages.json 包含 5 个 page', () => {
    const fs = require('fs')
    const p = path.resolve(__dirname, '../../src/pages.json')
    expect(fs.existsSync(p)).toBe(true)
    const cfg = JSON.parse(fs.readFileSync(p, 'utf-8'))
    expect(cfg.pages).toHaveLength(5)
    const paths = cfg.pages.map((pg) => pg.path)
    expect(paths).toContain('pages/index/index')
    expect(paths).toContain('pages/class-overview/class-overview')
    expect(paths).toContain('pages/students/students')
    expect(paths).toContain('pages/students/student-detail')
    expect(paths).toContain('pages/profile/profile')
  })

  it('manifest.json 配置 mp-weixin appid', () => {
    const fs = require('fs')
    const p = path.resolve(__dirname, '../../src/manifest.json')
    expect(fs.existsSync(p)).toBe(true)
    const cfg = JSON.parse(fs.readFileSync(p, 'utf-8'))
    expect(cfg['mp-weixin']).toBeDefined()
    expect(cfg['mp-weixin'].appid).toBeDefined()
    expect(cfg.vueVersion).toBe('3')
  })

  it('5 个 page .vue 存在', () => {
    const fs = require('fs')
    const pages = [
      'src/pages/index/index.vue',
      'src/pages/class-overview/class-overview.vue',
      'src/pages/students/students.vue',
      'src/pages/students/student-detail.vue',
      'src/pages/profile/profile.vue',
    ]
    pages.forEach((rel) => {
      const p = path.resolve(__dirname, '../..', rel)
      expect(fs.existsSync(p)).toBe(true)
    })
  })

  it('common/ 5 个文件齐全(data/format/charts/storage/cloud)', () => {
    const fs = require('fs')
    const files = ['data.js', 'format.js', 'charts.js', 'storage.js', 'cloud.js']
    files.forEach((f) => {
      const p = path.resolve(__dirname, '../../src/common', f)
      expect(fs.existsSync(p)).toBe(true)
    })
  })

  it('cloudfunctions/ 至少 2 个云函数(login + seedStudents)', () => {
    const fs = require('fs')
    const fns = ['login', 'seedStudents']
    fns.forEach((fn) => {
      const idx = path.resolve(__dirname, '../../cloudfunctions', fn, 'index.js')
      const pkg = path.resolve(__dirname, '../../cloudfunctions', fn, 'package.json')
      expect(fs.existsSync(idx)).toBe(true)
      expect(fs.existsSync(pkg)).toBe(true)
    })
  })
})

describe('pure functions — src/common/{data,format,charts}.js', () => {
  // 纯函数必须不依赖 uni.* / wx.* — 直接 require 即可跑
  const data = require('../../src/common/data.js')
  const format = require('../../src/common/format.js')
  const charts = require('../../src/common/charts.js')

  it('data.STUDENTS 长度 > 0', () => {
    expect(data.STUDENTS.length).toBeGreaterThan(0)
  })

  it('format.fmtTime 格式化 < 60s', () => {
    expect(format.fmtTime(55)).toBe('55.00')
    expect(format.fmtTime(55.5)).toBe('55.50')
  })

  it('format.fmtTime 格式化 ≥ 60s', () => {
    expect(format.fmtTime(65)).toBe('1:05.00')
    expect(format.fmtTime(125.5)).toBe('2:05.50')
  })

  it('format.fmtTime null/NaN → "—"', () => {
    expect(format.fmtTime(null)).toBe('—')
    expect(format.fmtTime(undefined)).toBe('—')
    expect(format.fmtTime(NaN)).toBe('—')
  })

  it('format.judge 判定达标等级', () => {
    expect(format.judge(null, 60)).toBe('miss')
    expect(format.judge(50, 60)).toBe('pass')
    expect(format.judge(62, 60)).toBe('warn')
    expect(format.judge(70, 60)).toBe('fail')
  })

  it('format.promoProgress 进度文案', () => {
    expect(format.promoProgress(3, 3, '旗鱼班')).toContain('可升入')
    expect(format.promoProgress(1, 3, '旗鱼班')).toContain('再达标 2 项')
  })

  it('charts.lineChart 空数据 → 提示文本', () => {
    const svg = charts.lineChart([])
    expect(svg).toContain('svg')
    expect(svg).toContain('暂无数据')
  })

  it('charts.lineChart 有数据 → 含 polyline', () => {
    const svg = charts.lineChart([
      { x: '25-10', y: 50 },
      { x: '25-11', y: 48 },
      { x: '26-04', y: 46 },
    ], 45)
    expect(svg).toContain('polyline')
    expect(svg).toContain('trend-line')
    expect(svg).toContain('promo-line')
  })

  it('charts.barChart 含柱状矩形', () => {
    const svg = charts.barChart([
      { label: '蝶', value: 50, target: 55 },
      { label: '仰', value: 60, target: 55 },
    ])
    expect(svg).toContain('rect')
  })

  it('charts.donut 渲染达标进度', () => {
    const svg = charts.donut(2, 3)
    expect(svg).toContain('donut-filled')
    expect(svg).toContain('2/3')
  })
})

if (!SKIP_RUNTIME) {
  describe('运行时 — uni-automator 跑通 5 page', () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const automator = require('@dcloudio/uni-automator')
    it('首页加载并显示 Logo', async () => {
      const page = await automator.program.currentPage()
      await page.waitFor(500)
      const html = await page.html()
      expect(html).toContain('鱼跃 YuYue')
    }, 10000)

    it('切到学员页', async () => {
      const page = await automator.program.currentPage()
      await page.callMethod('navigateTo', { url: '/pages/students/students' })
      await page.waitFor(500)
      const html = await page.html()
      expect(html).toContain('学员')
    }, 10000)
  })
}