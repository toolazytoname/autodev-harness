// AutoDevHarness — miniprogram scaffold
// utils/format.js — 纯函数:时间格式化、达标判定
// -------------------------------------------------------------------------
// Reviewer 约束(miniprogram reviewer §3):
//   **禁止 wx.*** —— 纯函数,可被测试直接 require。
// -------------------------------------------------------------------------

/** 时间格式:满 60s → 1:05.00,不满 60s → 55.00;缺测(null/NaN) → '—' */
function fmtTime(sec) {
  if (sec == null || isNaN(sec)) return '—';
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  if (m > 0) return m + ':' + s.toFixed(2).padStart(5, '0');
  return s.toFixed(2);
}

/** 差值格式化:正数加 + ,负数加 − */
function fmtDiff(sec) {
  return (sec >= 0 ? '+' : '−') + Math.abs(sec).toFixed(2);
}

/** 达标判定:实际 ≤ 线 → pass;差 ≤5% → near;否则 miss;无数据 → none;无线 → plain */
function judge(actual, line) {
  if (actual == null) return 'none';
  if (line == null) return 'plain';
  if (actual <= line) return 'pass';
  if (actual <= line * 1.05) return 'near';
  return 'miss';
}

module.exports = { fmtTime, fmtDiff, judge };