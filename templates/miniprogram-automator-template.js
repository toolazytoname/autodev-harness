// AutoDevHarness — miniprogram-automator spec template
//
// This is a starter template for the miniprogram reviewer. Copy this
// file to tests/automator/<task-id>.spec.js and edit the it() blocks
// to match the task's acceptance criteria.
//
// Setup (macOS only — see docs/CROSS-PLATFORM-TESTING.md):
//   1. Install WeChat DevTools
//      brew install --cask wechatwebdevtools
//   2. Open the IDE, open your miniprogram project, and enable
//      "Service Port" in Settings → Security.
//   3. npm install miniprogram-automator
//   4. Find the IDE's CLI path; pass it as the `cliPath` option below
//      (default: '/Applications/wechatwebdevtools.app/Contents/MacOS/cli')
//
// Run:  node tests/automator/<task-id>.spec.js
// Skip runtime (Linux CI, no DevTools):
//   MINIPROGRAM_SKIP_RUNTIME=1 node tests/automator/<task-id>.spec.js
//
// Docs: https://developers.weixin.qq.com/miniprogram/dev/devtools/auto/

const path = require('path');
const automator = require('miniprogram-automator');

const SKIP_RUNTIME = !!process.env.MINIPROGRAM_SKIP_RUNTIME;
const PROJECT_PATH = path.resolve(__dirname, '..', '..', 'miniprogram');

describe('<task-id> automator', () => {
  let miniProgram;
  let page;

  beforeAll(async () => {
    if (SKIP_RUNTIME) {
      // In CI on Linux we can't run the IDE; just verify the script
      // loads and the pure-function asserts pass.
      return;
    }
    miniProgram = await automator.launch({
      projectPath: PROJECT_PATH,
      // Adjust to your DevTools install:
      cliPath: '/Applications/wechatwebdevtools.app/Contents/MacOS/cli',
    });
    page = await miniProgram.reLaunch('/pages/index/index');
  });

  afterAll(async () => {
    if (miniProgram) {
      await miniProgram.close();
    }
  });

  // Acceptance step 1 — example of a UI assertion
  it('shows the welcome heading', async () => {
    if (SKIP_RUNTIME) return;
    const welcome = await page.$('.welcome');
    expect(welcome).not.toBeNull();
    const text = await welcome.text();
    expect(text).toContain('Welcome');
  });

  // Acceptance step 2 — example of an interaction
  it('adds a new item when the button is tapped', async () => {
    if (SKIP_RUNTIME) return;
    await page.tap('add-btn');
    const item = await page.$('.item:first-child');
    expect(item).not.toBeNull();
  });

  // Pure-function tests don't need the runtime at all — run on any
  // platform, including Linux CI.
  describe('pure functions', () => {
    it('validates email format', () => {
      const { isValidEmail } = require('../../miniprogram/utils/validators');
      expect(isValidEmail('foo@bar.com')).toBe(true);
      expect(isValidEmail('not-an-email')).toBe(false);
    });
  });
});
