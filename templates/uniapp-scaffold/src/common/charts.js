/**
 * src/common/charts.js — 图表(纯函数,无 uni.* / wx.*)
 *
 * 返回 SVG 字符串,供 page 里用 <rich-text :nodes="..." /> 渲染。
 *
 * 为什么不直接用 ECharts / F2?
 *   MVP 阶段数据量小(单学员 < 100 个成绩点),SVG 自绘足够,免去
 *   引入 ~300KB 的图表库;后期若图表变复杂,再切到
 *   `@antv/f2-for-uniapp` 或 `echarts-for-uniapp`。
 */

/**
 * 折线图(进步趋势)
 *
 * @param {Array<{x:string, y:number}>} points  数据点(x = 考期 label, y = 秒)
 * @param {number|null} line                   达标线参考线(秒,可选)
 * @param {object} opts
 * @param {number} opts.width   svg 宽度(默认 600)
 * @param {number} opts.height  svg 高度(默认 200)
 * @param {string} opts.stroke  折线颜色(默认 --aqua)
 * @returns {string} svg 字符串
 */
export function lineChart(points, line = null, opts = {}) {
  const { width = 600, height = 200, stroke = '#5BB5D8' } = opts
  if (!points || points.length === 0) {
    return `<svg width="${width}" height="${height}"><text x="50%" y="50%" text-anchor="middle" fill="#9AA5B1">暂无数据</text></svg>`
  }
  const padL = 40, padR = 20, padT = 20, padB = 40
  const innerW = width - padL - padR
  const innerH = height - padT - padB
  const ys = points.map((p) => p.y).filter((y) => y != null)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const yRange = yMax - yMin || 1
  const xs = points.length
  const xStep = xs > 1 ? innerW / (xs - 1) : 0
  const coords = points.map((p, i) => {
    if (p.y == null) return null
    const x = padL + i * xStep
    const y = padT + innerH - ((p.y - yMin) / yRange) * innerH
    return { x, y }
  })
  const polyline = coords
    .map((c) => (c == null ? '' : `${c.x},${c.y}`))
    .filter(Boolean)
    .join(' ')
  const dots = coords
    .map((c, i) =>
      c == null
        ? ''
        : `<circle cx="${c.x}" cy="${c.y}" r="4" fill="${stroke}" data-sig="point-${i}"/>`
    )
    .join('')
  // Y 轴标签(min / max)
  const yLabels = `<text x="${padL - 6}" y="${padT + 8}" text-anchor="end" fill="#6B7785" font-size="12">${yMax.toFixed(1)}</text>
                   <text x="${padL - 6}" y="${padT + innerH}" text-anchor="end" fill="#6B7785" font-size="12">${yMin.toFixed(1)}</text>`
  // X 轴标签
  const xLabels = points
    .map(
      (p, i) =>
        `<text x="${padL + i * xStep}" y="${height - padB + 16}" text-anchor="middle" fill="#6B7785" font-size="12">${p.x}</text>`
    )
    .join('')
  // 达标线参考
  let lineRef = ''
  if (line != null) {
    const y = padT + innerH - ((line - yMin) / yRange) * innerH
    lineRef = `<line x1="${padL}" y1="${y}" x2="${padL + innerW}" y2="${y}" stroke="#7BC97E" stroke-dasharray="4 4" data-sig="promo-line"/>
               <text x="${padL + innerW - 4}" y="${y - 4}" text-anchor="end" fill="#7BC97E" font-size="12">达标线 ${line}s</text>`
  }
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    ${lineRef}
    ${yLabels}
    ${xLabels}
    <polyline points="${polyline}" fill="none" stroke="${stroke}" stroke-width="2" data-sig="trend-line"/>
    ${dots}
  </svg>`
}

/**
 * 柱状图(各泳姿能力对比)
 *
 * @param {Array<{label:string, value:number|null, target:number}>} bars
 * @param {object} opts
 * @returns {string} svg 字符串
 */
export function barChart(bars, opts = {}) {
  const { width = 600, height = 200 } = opts
  if (!bars || bars.length === 0) {
    return `<svg width="${width}" height="${height}"><text x="50%" y="50%" text-anchor="middle" fill="#9AA5B1">暂无数据</text></svg>`
  }
  const padL = 40, padR = 20, padT = 20, padB = 40
  const innerW = width - padL - padR
  const innerH = height - padT - padB
  const yMax = Math.max(
    ...bars.flatMap((b) => [b.value || 0, b.target || 0]).filter((v) => v != null)
  )
  const yRange = yMax || 1
  const bw = innerW / bars.length
  const bars_ = bars
    .map((b, i) => {
      const x0 = padL + i * bw + bw * 0.15
      const w = bw * 0.35
      const hVal = b.value != null ? (b.value / yRange) * innerH : 0
      const hTar = (b.target / yRange) * innerH
      const yVal = padT + innerH - hVal
      const yTar = padT + innerH - hTar
      const color = b.value == null
        ? '#C9D1D9'
        : b.value <= b.target
          ? '#7BC97E'
          : b.value <= b.target * 1.05
            ? '#F2D05E'
            : '#9AA5B1'
      return `
        <rect x="${x0}" y="${yVal}" width="${w}" height="${hVal}" fill="${color}" data-sig="bar-${i}"/>
        <rect x="${x0 + w + 2}" y="${yTar}" width="${w * 0.6}" height="${hTar}" fill="#5BB5D8" data-sig="target-${i}"/>
        <text x="${x0 + w}" y="${height - padB + 16}" text-anchor="middle" fill="#6B7785" font-size="12">${b.label}</text>
      `
    })
    .join('')
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${bars_}</svg>`
}

/**
 * 环形图(达标进度)
 *
 * @param {number} passed   已达标项数
 * @param {number} required 总需达标项数
 * @param {object} opts
 * @returns {string} svg 字符串
 */
export function donut(passed, required, opts = {}) {
  const { size = 160, strokeWidth = 16 } = opts
  const r = (size - strokeWidth) / 2
  const cx = size / 2
  const cy = size / 2
  const circumference = 2 * Math.PI * r
  const ratio = required > 0 ? Math.min(passed / required, 1) : 0
  const filled = circumference * ratio
  const empty = circumference - filled
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#E5EAF0" stroke-width="${strokeWidth}"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#5BB5D8" stroke-width="${strokeWidth}"
            stroke-dasharray="${filled} ${empty}" stroke-linecap="round"
            transform="rotate(-90 ${cx} ${cy})" data-sig="donut-filled"/>
    <text x="${cx}" y="${cy + 4}" text-anchor="middle" fill="#2A323C" font-size="24" font-weight="600" data-sig="donut-text">${passed}/${required}</text>
  </svg>`
}