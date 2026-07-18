// AutoDevHarness — miniprogram scaffold
// utils/storage.js — 成绩更正覆盖的持久化
// -------------------------------------------------------------------------
// Reviewer 约束(miniprogram reviewer §3):
//   这是 wx.* 白名单模块(reviewer 文档 §3 允许 services/* + app.js 之外的
//   业务适配层;此文件作为 storage 适配层,允许使用 wx.*)。
//
// 其他 utils 文件禁止 import wx;它们应该 require 这个 storage.js 后调封装函数。
// -------------------------------------------------------------------------

const SCORE_CORRECTIONS_KEY = 'yy_score_corrections_v1';

/** 读所有成绩更正覆盖 */
function readScoreCorrections() {
  try {
    const stored = wx.getStorageSync(SCORE_CORRECTIONS_KEY) || '[]';
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

/** 追加一条成绩更正 */
function appendScoreCorrection(correction) {
  const corrections = readScoreCorrections();
  corrections.push(correction);
  try {
    wx.setStorageSync(SCORE_CORRECTIONS_KEY, JSON.stringify(corrections));
    return true;
  } catch (e) {
    return false;
  }
}

/** 撤销某学员某项目某考期的最新一条更正 */
function revertLatestScoreCorrection(studentId, event, termId) {
  const corrections = readScoreCorrections();
  let targetIdx = -1;
  for (let i = corrections.length - 1; i >= 0; i--) {
    const c = corrections[i];
    if (c.studentId === studentId && c.event === event && c.termId === termId) {
      targetIdx = i;
      break;
    }
  }
  if (targetIdx < 0) return false;
  const next = corrections.filter((_, idx) => idx !== targetIdx);
  try {
    wx.setStorageSync(SCORE_CORRECTIONS_KEY, JSON.stringify(next));
    return true;
  } catch (e) {
    return false;
  }
}

module.exports = {
  readScoreCorrections,
  appendScoreCorrection,
  revertLatestScoreCorrection,
};