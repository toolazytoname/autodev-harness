// AutoDevHarness — miniprogram scaffold
// utils/charts.js — SVG 图表引擎(移植自 OD shared.js)
// -------------------------------------------------------------------------
// Reviewer 约束(miniprogram reviewer §3):
//   **禁止 wx.*** —— 纯函数,返回 SVG 字符串。
//   在 wxml 里用 <rich-text nodes="{{chart(data)}}" /> 渲染。
//
// 三个图表对应 OD 的折线(lineChart) / 柱状(barChart) / 环形(donut):
//   - 折线:学员历史成绩趋势,纵轴=时间(秒),向下=进步,叠加达标参考线
//   - 柱状:各泳姿能力对比,横轴=时间(秒),达标线虚线
//   - 环形:晋级达标进度,中心显示 done/need
//
// 当前是占位实现(返回 <svg data-placeholder="...">),generator 在 task-4
// 填充真正的实现。占位保留入参让 generator 看到接口约定。
// -------------------------------------------------------------------------

/** 进步趋势折线 — 占位实现,generator 在 task-4 替换 */
function lineChart(points, line) {
  const sig = JSON.stringify({ pointsLen: (points && points.length) || 0, line: line == null ? null : line });
  return `<svg data-placeholder="lineChart" data-sig='${sig}'></svg>`;
}

/** 各泳姿能力对比柱状 — 占位实现 */
function barChart(items) {
  const sig = JSON.stringify({ itemsLen: (items && items.length) || 0 });
  return `<svg data-placeholder="barChart" data-sig='${sig}'></svg>`;
}

/** 晋级达标环形 — 占位实现 */
function donut(done, need, label) {
  const sig = JSON.stringify({ done, need, label: label || null });
  return `<svg data-placeholder="donut" data-sig='${sig}'></svg>`;
}

module.exports = { lineChart, barChart, donut };