// AutoDevHarness — miniprogram scaffold smoke test
// 烟雾测试:验证 5 page 都能 launch + 纯函数模块不依赖 wx
// -------------------------------------------------------------------------
// 跑通(macOS):
//   1. 打开 WeChat DevTools,打开本项目,Settings → Security → Service Port → Enable
//   2. node tests/automator/_smoke.spec.js
//
// 跳过 runtime(Linux CI):
//   MINIPROGRAM_SKIP_RUNTIME=1 node tests/automator/_smoke.spec.js
//
// 这只是烟雾测试 — 真正的 acceptance 测试由 generator 在每个 task 写自己的
// <task-id>.spec.js。
// -------------------------------------------------------------------------

const path = require('path');
const automator = require('miniprogram-automator');

const SKIP_RUNTIME = !!process.env.MINIPROGRAM_SKIP_RUNTIME;
const PROJECT_PATH = path.resolve(__dirname, '..', '..');

const PAGES = [
  { path: '/pages/index/index', label: '首页' },
  { path: '/pages/students/students', label: '学员' },
  { path: '/pages/class-overview/class-overview', label: '成绩' },
  { path: '/pages/students/student-detail', label: '学员详情' },
  { path: '/pages/profile/profile', label: '我的' },
];

describe('scaffold smoke', () => {
  let miniProgram;

  beforeAll(async () => {
    if (SKIP_RUNTIME) return;
    miniProgram = await automator.launch({
      projectPath: PROJECT_PATH,
      cliPath: '/Applications/wechatwebdevtools.app/Contents/MacOS/cli',
    });
  });

  afterAll(async () => {
    if (miniProgram) await miniProgram.close();
  });

  // 每个 page 都能 launch + reLaunch
  PAGES.forEach(({ path: p, label }) => {
    it(`launches ${label} page`, async () => {
      if (SKIP_RUNTIME) return;
      const page = await miniProgram.reLaunch(p);
      expect(page).not.toBeNull();
      const title = await page.title();
      expect(typeof title).toBe('string');
    });
  });

  // 纯函数模块不依赖 wx(可以直接 require 测试)
  describe('pure functions', () => {
    it('format.fmtTime handles null / NaN / <60s / >=60s', () => {
      const { fmtTime } = require('../../utils/format.js');
      expect(fmtTime(null)).toBe('—');
      expect(fmtTime(NaN)).toBe('—');
      expect(fmtTime(55.0)).toBe('55.00');
      expect(fmtTime(65.0)).toBe('1:05.00');
    });

    it('format.fmtDiff prefixes + or −', () => {
      const { fmtDiff } = require('../../utils/format.js');
      expect(fmtDiff(2.5)).toBe('+2.50');
      expect(fmtDiff(-2.5)).toBe('−2.50');
      expect(fmtDiff(0)).toBe('+0.00');
    });

    it('format.judge classifies pass / near / miss / none / plain', () => {
      const { judge } = require('../../utils/format.js');
      expect(judge(50, 60)).toBe('pass');
      expect(judge(62, 60)).toBe('near');
      expect(judge(70, 60)).toBe('miss');
      expect(judge(null, 60)).toBe('none');
      expect(judge(50, null)).toBe('plain');
    });
  });
});