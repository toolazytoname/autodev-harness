// 云函数 addStudent — 教练端新增学员(v2 canonical schema)
//
// 输入:{ name, classId, coachIds?, parentOpenids?, age?, birthYear?, firstTermId? }
// 输出:{ ok: true, _id }
//
// 权限:仅 coach / admin 可调 — 前端 role store 控制入口;
// 进阶做法是在云函数里再校验一次 OPENID 对应的 role。

const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()

exports.main = async (event) => {
  const {
    name, classId,
    coachIds = [], parentOpenids = [],
    age = null, birthYear = null, firstTermId = null,
  } = event || {}

  if (!name || !classId) {
    return { ok: false, error: 'name + classId 必填' }
  }
  // v2: business _id 用 classId + 短 hash 简化;生产建议用 uuid
  const _id = `s_${Date.now()}_${Math.floor(Math.random() * 1000)}`
  const now = Date.now()
  await db.collection('students').doc(_id).set({
    data: {
      name,
      nameNormalized: name.trim(),
      classId,
      coachIds,
      parentOpenids,
      age,
      birthYear,
      ageRaw: age != null ? String(age) : null,
      firstTermId,
      classHistory: [{ classId, fromTermId: firstTermId }],
      status: 'active',
      needsClassReview: false,
      sourceMeta: { importedFrom: { fileName: 'manual', sheetName: 'manual' } },
      createdAt: now,
      updatedAt: now,
      // v1 alias(暂留)
      coach: (coachIds && coachIds[0]) || '',
      firstTerm: firstTermId || '',
    },
  })
  return { ok: true, _id }
}