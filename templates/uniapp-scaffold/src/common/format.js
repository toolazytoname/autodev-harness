/**
 * src/common/format.js — 格式化 + 判定(纯函数,无 uni.* / wx.*)
 *
 * v2 兼容:同时支持 scoreStatus(canonical)和 judge(v1 alias)两种字段。
 * UI 层 judge 仍可显示色阶;MVP 短期双读,V3 移除 judge 字段。
 */

/**
 * 把 scoreStatus(canonical) 映射为 judge(v1 alias)供 UI 色阶用。
 *
 * @param {'measured'|'missing'|'invalid'|'not_applicable'} scoreStatus
 * @param {number} [scoreSec]   measured 时用于判定 pass/warn/fail
 * @param {number} [thresholdSec]  达标线
 * @returns {'pass'|'warn'|'fail'|'miss'|'invalid'|'na'}
 */
export function scoreStatusToJudge(scoreStatus, scoreSec, thresholdSec) {
  if (scoreStatus === 'missing') return 'miss'
  if (scoreStatus === 'invalid') return 'invalid'
  if (scoreStatus === 'not_applicable') return 'na'
  if (scoreStatus === 'measured') {
    if (scoreSec == null || thresholdSec == null) return 'fail'
    return judge(scoreSec, thresholdSec)
  }
  return 'miss'
}

/**
 * 把 judge(v1 alias) 映射为 CSS 类名(供 .pass .warn .fail .miss .invalid .na 样式用)。
 *
 * @param {string} judgeResult
 * @returns {string}
 */
export function judgeClass(judgeResult) {
  const valid = ['pass', 'warn', 'fail', 'miss', 'invalid', 'na']
  const safe = valid.includes(judgeResult) ? judgeResult : 'miss'
  return `cell-${safe}`
}

/**
 * 从 score_records(读库后) 拿 scoreStatus/judge/UI class。兼容 v1+v2。
 *
 * @param {object} record   score_records 的一条记录
 * @returns {string}  'cell-pass' | 'cell-warn' | ...
 */
export function scoreCellClass(record) {
  // v2 path
  if (record.scoreStatus) {
    const j = scoreStatusToJudge(record.scoreStatus, record.scoreSec, record.thresholdSec)
    return judgeClass(j)
  }
  // v1 fallback
  return judgeClass(record.judge || 'miss')
}

/**
 * 把秒数格式化为展示字符串。
 *   - null / undefined / NaN / 负数 → "—"
 *   - < 60             → "55.00"
 *   - >= 60            → "1:05.00"
 *   - 超过 60 分钟     → "60:00.00"(理论上不会,防御性返回)
 *
 * @param {number|null|undefined} sec
 * @returns {string}
 */
export function fmtTime(sec) {
  if (sec == null || typeof sec !== 'number' || isNaN(sec) || sec < 0) return '—'
  if (sec < 60) return sec.toFixed(2)
  const totalSec = Math.min(sec, 3600) // 防御:不超过 60 分钟
  const m = Math.floor(totalSec / 60)
  const s = (totalSec - m * 60).toFixed(2)
  return `${m}:${s.padStart(5, '0')}`
}

/**
 * 计算 a - b(秒),并格式化为带正负号的字符串。
 *   正值表示 b 更快(进步);负值表示 a 更快(退步);0 显示 ±。
 *   任何一侧缺测 → "—"
 *
 * @param {number|null|undefined} a  本次成绩
 * @param {number|null|undefined} b  上次成绩
 * @returns {string}
 */
export function fmtDiff(a, b) {
  if (a == null || b == null || isNaN(a) || isNaN(b)) return '—'
  const d = a - b
  if (Math.abs(d) < 0.005) return '±0.00'
  const sign = d > 0 ? '+' : '−'
  return `${sign}${fmtTime(Math.abs(d))}`
}

/**
 * 根据达标线判定成绩等级。
 *   - time == null / 非数字 / 负数 → 'miss'(缺测或非法)
 *   - line <= 0(没达标线)         → 'miss'(防御:无效配置)
 *   - time <= line                → 'pass'(达标)
 *   - time <= line * 1.05         → 'warn'(接近,5% 阈值)
 *   - else                        → 'fail'(未达)
 *
 * @param {number|null|undefined} time  实际成绩(秒)
 * @param {number} line                  达标线(秒)
 * @returns {'pass'|'warn'|'fail'|'miss'}
 */
export function judge(time, line) {
  if (time == null || typeof time !== 'number' || isNaN(time) || time < 0) return 'miss'
  if (line == null || typeof line !== 'number' || isNaN(line) || line <= 0) return 'miss'
  if (time <= line) return 'pass'
  if (time <= line * 1.05) return 'warn'
  return 'fail'
}

/**
 * 根据已达标项数 / 需达标项数生成进度文案。
 *   - passed >= required  → "已达 X/Y 项,可升入{nextClass}!"
 *   - passed == 0         → "已达 0/Y 项,再达标 Y 项即可升入{nextClass}"
 *   - passed > required   → 防御:按 required 上限截断(防止超达标文案错乱)
 *   - required <= 0       → 防御:返回"无需达标项"(配置错误)
 *
 * @param {number} passed     已达标项数(可能 > required,截断)
 * @param {number} required   需达标项数
 * @param {string} nextClass  下一班名(如 "旗鱼班")
 * @returns {string}
 */
export function promoProgress(passed, required, nextClass) {
  const p = Math.max(0, Math.min(passed, required)) // 截断
  const r = Math.max(0, required)
  if (r === 0) return `无需达标项,可升入${nextClass}`
  if (p >= r) return `已达 ${p}/${r} 项,可升入${nextClass}!`
  const remain = r - p
  return `已达标 ${p}/${r} 项,再达标 ${remain} 项即可升入${nextClass}`
}

/**
 * 把差值(秒)格式化为 "差 N.NN 秒"。
 *   缺测 / 非数字 → "—"
 *
 * @param {number|null|undefined} diffSec
 * @returns {string}
 */
export function diffSecText(diffSec) {
  if (diffSec == null || typeof diffSec !== 'number' || isNaN(diffSec)) return '—'
  return `差 ${diffSec.toFixed(2)} 秒`
}

/**
 * 统计学员在指定班级项目集中已达标项数。
 * 用于单人详情 / 班级总览。
 *
 * v2 兼容:同时读 v2 字段(eventKey/scoreSec/scoreStatus/thresholdSec)和 v1 alias
 * (projectId/time/judge)。优先 v2。
 *
 * 规则:
 *   - 只统计传入 projectIds 列表里的项目
 *   - 同项目多次成绩取 records 数组的最后一条(调用方保证时间正序)
 *   - 缺测(scoreStatus='missing' 或 judge='miss')不计
 *   - 未测(invalid/na)不计
 *
 * @param {Array<object>} records  学员成绩数组
 * @param {string[]} projectIds   班级项目 ID 列表
 * @returns {{ passed: number, required: number, projectResults: Array<{eventKey: string, judge: string}> }}
 */
export function summarizePass(records, projectIds) {
  const projectResults = projectIds.map((pid) => {
    // 取该项目最后一次记录
    let lastJudge = 'miss'
    for (const r of records) {
      const key = r.eventKey || r.projectId
      if (key !== pid) continue
      // v2 path
      if (r.scoreStatus) {
        lastJudge = scoreStatusToJudge(r.scoreStatus, r.scoreSec, r.thresholdSec)
      } else {
        // v1 fallback
        lastJudge = r.judge || 'miss'
      }
    }
    return { eventKey: pid, judge: lastJudge }
  })
  const passed = projectResults.filter((r) => r.judge === 'pass').length
  return { passed, required: projectIds.length, projectResults }
}