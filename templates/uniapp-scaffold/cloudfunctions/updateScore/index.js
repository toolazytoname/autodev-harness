// 云函数 updateScore — 成绩写入 / 更正 / 删除(v2 canonical schema)
//
// 输入:{
//   studentId, termId, classId, eventKey,
//   scoreSec, scoreStatus, rawScore?, thresholdSec?, isQualified?,
//   deltaSec?, source?,
// }
//   recordKey? / _id?  存在 → 更新;不存在 → 新增(按 recordKey = termId#studentId#eventKey upsert)
// 输出:{ ok: true, _id, updated: boolean }
//
// v2 字段说明:
//   scoreStatus: 'measured' | 'missing' | 'invalid' | 'not_applicable'
//   thresholdSec: 该考试时 class.standards[eventKey].normalSec 快照(防转班改历史)
//   isQualified: 云函数按 scoreSec <= thresholdSec 重算
//   deltaSec: scoreSec - previousScoreSec(负数=进步)

const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()

function computeIsQualified(scoreSec, thresholdSec) {
  if (scoreSec == null || thresholdSec == null) return false
  return scoreSec <= thresholdSec
}

exports.main = async (event) => {
  const {
    studentId, termId, classId, eventKey,
    scoreSec, scoreStatus, rawScore = null,
    thresholdSec = null, isQualified = null,
    deltaSec = null, source = null,
  } = event || {}

  if (!studentId || !termId || !eventKey) {
    return { ok: false, error: 'studentId + termId + eventKey 必填' }
  }

  const now = Date.now()
  const recordKey = `${termId}#${studentId}#${eventKey}`
  const qualified = isQualified != null ? isQualified : computeIsQualified(scoreSec, thresholdSec)

  // 检查是否已存在
  const existing = await db
    .collection('score_records')
    .where({ recordKey })
    .limit(1)
    .get()

  if (existing.data && existing.data.length > 0) {
    const id = existing.data[0]._id
    await db.collection('score_records').doc(id).update({
      data: {
        scoreSec, scoreStatus, rawScore, thresholdSec,
        isQualified: qualified, deltaSec,
        classId, source,
        updatedAt: now,
        // v1 alias
        time: scoreSec,
        projectId: eventKey,
        judge: scoreStatusToJudge(scoreStatus),
      },
    })
    return { ok: true, _id: id, updated: true }
  }

  const _id = `r_${Date.now()}_${Math.floor(Math.random() * 1000)}`
  await db.collection('score_records').doc(_id).set({
    data: {
      recordKey,
      studentId, termId, classId, eventKey,
      scoreSec, scoreStatus, rawScore, thresholdSec,
      isQualified: qualified, deltaSec,
      source: source || {},
      createdAt: now,
      updatedAt: now,
      // v1 alias
      time: scoreSec,
      projectId: eventKey,
      judge: scoreStatusToJudge(scoreStatus),
    },
  })
  return { ok: true, _id, updated: false }
}

// 简易 scoreStatus → judge 映射(避免依赖 src/common/format.js 因为云函数没该文件)
function scoreStatusToJudge(scoreStatus) {
  if (scoreStatus === 'missing') return 'miss'
  if (scoreStatus === 'invalid') return 'invalid'
  if (scoreStatus === 'not_applicable') return 'na'
  // measured 由 isQualified 决定;云函数调用方应传 isQualified,这里给个保守值
  return 'measured'
}