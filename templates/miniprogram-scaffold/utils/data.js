// AutoDevHarness — miniprogram scaffold
// utils/data.js — 学员/班级/考期数据
// -------------------------------------------------------------------------
// Reviewer 约束(miniprogram reviewer §3):
//   **禁止 wx.*** —— 这是纯函数模块,可被测试直接 require。
//   数据是真实名册的脱敏版(保留姓氏、改写名字/模糊年龄)。
//
// generator 在 task-3+ 填充完整数据时,从 OD 项目的 shared.js 翻译过来:
//   STUDENTS / CLASSES / TERMS / CLASS_BY_ID / STUDENT_BY_ID
// 这里仅放最简骨架让 generator 知道数据 schema。
// -------------------------------------------------------------------------

/** 班级阶梯定义(低 → 高) */
const CLASSES = [
  // TODO(g-3): 从 OD shared.js 翻译,完整 5 个班级(jinyu / haitun / qiyu / jiaolong / jingxun)
];

/** 考期定义 */
const TERMS = [
  // TODO(g-3): 6 个考期定义(id / label / date)
];

/** 学员列表 — 真实名册脱敏版 */
const STUDENTS = [
  // TODO(g-3): 21 个脱敏学员(OD shared.js 里)
];

/** 派生索引 */
const CLASS_BY_ID = Object.fromEntries(CLASSES.map(c => [c.id, c]));
const STUDENT_BY_ID = Object.fromEntries(STUDENTS.map(s => [s.id, s]));

module.exports = {
  CLASSES,
  CLASS_BY_ID,
  TERMS,
  STUDENTS,
  STUDENT_BY_ID,
};