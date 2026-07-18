// 云函数 seedStudents — 从内嵌数据灌进 students + score_records + classes + terms 集合
// 一次性,部署后手动调一次(或在 App.vue.onLaunch 检测空表时调)
//
// 输入:{ force?: boolean }  force=true 时清空再灌
// 输出:{ inserted: { students, score_records, classes, terms }, total }

const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()

// === v2 canonical data ===
// 与 src/common/data.js 对齐 — 字段名为 v2 canonical + v1 alias(短期双读)

// 班级(v2:含 eventKeys/standards/promotionRule)
const CLASSES = [
  { _id: 'goldfish',    name: '金鱼班',   level: 1,
    eventKeys: ['50fly', '50back', '50brst', '50free', '50leg'],
    standards: {
      '50fly':  { normalSec: 60 }, '50back': { normalSec: 60 },
      '50brst': { normalSec: 70 }, '50free': { normalSec: 50 }, '50leg':  { normalSec: 55 },
    },
    promotionRule: { ruleVersion: 1, targetClassId: 'dolphin',
      groups: [{ id: 'tech', kind: 'manual', checkKey: '会 2 种泳姿并掌握合理技术' }] },
    coachIds: [], isActive: true,
    // v1 alias
    projectSet: '50basic',
    createdAt: 1700000000000, updatedAt: 1700000000000,
  },
  { _id: 'dolphin',     name: '海豚班',   level: 2,
    eventKeys: ['50fly', '50back', '50brst', '50free'],
    standards: {
      '50fly':  { normalSec: 55 }, '50back': { normalSec: 55 },
      '50brst': { normalSec: 60 }, '50free': { normalSec: 45 },
    },
    promotionRule: { ruleVersion: 1, targetClassId: 'sailfish',
      groups: [{ id: 'pass2', kind: 'count', eventKeys: ['50back', '50brst', '50free'], minCount: 2 }] },
    coachIds: [], isActive: true,
    projectSet: '50basic',
    createdAt: 1700000000000, updatedAt: 1700000000000,
  },
  { _id: 'sailfish',    name: '旗鱼班',   level: 3,
    eventKeys: ['50fly', '50back', '50brst', '50free'],
    standards: {
      '50fly':  { normalSec: 50 }, '50back': { normalSec: 50 },
      '50brst': { normalSec: 55 }, '50free': { normalSec: 40 },
    },
    promotionRule: { ruleVersion: 1, targetClassId: 'jiaolong',
      groups: [{ id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 }] },
    coachIds: [], isActive: true,
    projectSet: '50four',
    createdAt: 1700000000000, updatedAt: 1700000000000,
  },
  { _id: 'jiaolong',    name: '蛟龙班',   level: 4,
    eventKeys: ['50fly', '50back', '50brst', '50free', '100free', '100mix', '200free', '200mix', '400free', '400mix', '800free'],
    standards: {
      '50fly':  { normalSec: 45 }, '50back': { normalSec: 45 },
      '50brst': { normalSec: 50 }, '50free': { normalSec: 35 },
      '100free': { normalSec: 90 }, '100mix': { normalSec: 100 },
      '200free': { normalSec: 180 }, '200mix': { normalSec: 200 },
    },
    promotionRule: { ruleVersion: 1, targetClassId: 'competition',
      groups: [
        { id: 'tech4', kind: 'manual', checkKey: '4 姿技术正确' },
        { id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 },
        { id: 'long1', kind: 'count', eventKeys: ['100free', '100mix', '200free', '200mix'], minCount: 1 },
      ] },
    coachIds: [], isActive: true,
    projectSet: '50plus',
    createdAt: 1700000000000, updatedAt: 1700000000000,
  },
  { _id: 'competition', name: '蛟龙竞训队', level: 5,
    eventKeys: ['50fly', '50back', '50brst', '50free', '100free', '100mix', '200free', '200mix', '400free', '400mix', '800free'],
    standards: {
      '50fly':  { normalSec: 40, elite2Sec: 38, elite1Sec: 35 },
      '50back': { normalSec: 40, elite2Sec: 38, elite1Sec: 35 },
      '50brst': { normalSec: 45, elite2Sec: 42, elite1Sec: 40 },
      '50free': { normalSec: 32, elite2Sec: 30, elite1Sec: 28 },
      '100free': { normalSec: 75, elite2Sec: 70, elite1Sec: 65 },
      '100mix':  { normalSec: 85, elite2Sec: 80, elite1Sec: 75 },
      '200free': { normalSec: 160, elite2Sec: 150, elite1Sec: 140 },
      '200mix':  { normalSec: 180, elite2Sec: 170, elite1Sec: 160 },
      '400free': { normalSec: 360, elite2Sec: 340, elite1Sec: 320 },
      '400mix':  { normalSec: 400, elite2Sec: 380, elite1Sec: 360 },
      '800free': { normalSec: 800, elite2Sec: 760, elite1Sec: 720 },
    },
    promotionRule: { ruleVersion: 1, targetClassId: null,
      groups: [
        { id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 },
        { id: 'longAll', kind: 'count', eventKeys: ['100free', '200free'], minCount: 2, acceptedLevels: ['elite2', 'elite1'] },
      ] },
    coachIds: [], isActive: true,
    projectSet: '50plus',
    createdAt: 1700000000000, updatedAt: 1700000000000,
  },
]

// 考期
const TERMS = [
  { _id: '2025-10', termKey: '2025-10', year: 2025, month: 10, examDate: null, label: '2025 年 10 月', status: 'published', sourceFiles: [], createdAt: 1700000000000, updatedAt: 1700000000000 },
  { _id: '2025-11', termKey: '2025-11', year: 2025, month: 11, examDate: '2025-11-23', label: '2025 年 11 月', status: 'published', sourceFiles: [], createdAt: 1700000000000, updatedAt: 1700000000000 },
  { _id: '2026-04', termKey: '2026-04', year: 2026, month: 4,  examDate: '2026-04-11', label: '2026 年 4 月', status: 'published', sourceFiles: [], createdAt: 1700000000000, updatedAt: 1700000000000 },
]

// 学员(v2 canonical + v1 alias)
const STUDENTS = [
  { _id: 's001', name: '小鲤', nameNormalized: '小鲤', classId: 'goldfish', coachIds: [], parentOpenids: [], age: 7, birthYear: 2018, ageRaw: '7', firstTermId: '2025-10', classHistory: [{ classId: 'goldfish', fromTermId: '2025-10' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '王教练', firstTerm: '2025-10' },
  { _id: 's002', name: '小鲲', nameNormalized: '小鲲', classId: 'goldfish', coachIds: [], parentOpenids: [], age: 8, birthYear: 2017, ageRaw: '8', firstTermId: '2025-10', classHistory: [{ classId: 'goldfish', fromTermId: '2025-10' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '王教练', firstTerm: '2025-10' },
  { _id: 's003', name: '小澜', nameNormalized: '小澜', classId: 'dolphin', coachIds: [], parentOpenids: [], age: 9, birthYear: 2016, ageRaw: '9', firstTermId: '2025-10', classHistory: [{ classId: 'goldfish', fromTermId: '2025-10', toTermId: '2025-11', changedAt: 1730000000000, reason: '达标晋升' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '李教练', firstTerm: '2025-10' },
  { _id: 's004', name: '小川', nameNormalized: '小川', classId: 'dolphin', coachIds: [], parentOpenids: [], age: 10, birthYear: 2016, ageRaw: '10', firstTermId: '2025-11', classHistory: [{ classId: 'dolphin', fromTermId: '2025-11' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '李教练', firstTerm: '2025-11' },
  { _id: 's005', name: '小泽', nameNormalized: '小泽', classId: 'sailfish', coachIds: [], parentOpenids: [], age: 11, birthYear: 2015, ageRaw: '11', firstTermId: '2025-10', classHistory: [{ classId: 'sailfish', fromTermId: '2025-10' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '陈教练', firstTerm: '2025-10' },
  { _id: 's006', name: '小舟', nameNormalized: '小舟', classId: 'jiaolong', coachIds: [], parentOpenids: [], age: 12, birthYear: 2014, ageRaw: '12', firstTermId: '2025-11', classHistory: [{ classId: 'jiaolong', fromTermId: '2025-11' }], status: 'active', needsClassReview: false, sourceMeta: {}, createdAt: 1700000000000, updatedAt: 1700000000000, coach: '陈教练', firstTerm: '2025-11' },
]

// 成绩(v2 canonical + v1 alias,thresholdSec 用 class.standards 快照)
const SCORES = [
  // 小鲤 goldfish 2025-10
  { _id: 'r001', recordKey: '2025-10#s001#50fly',  studentId: 's001', termId: '2025-10', classId: 'goldfish', eventKey: '50fly',  scoreSec: 62.5, scoreStatus: 'measured', thresholdSec: 60, isQualified: false, deltaSec: null, rawScore: null, projectId: '50fly', time: 62.5, judge: 'fail' },
  { _id: 'r002', recordKey: '2025-10#s001#50back', studentId: 's001', termId: '2025-10', classId: 'goldfish', eventKey: '50back', scoreSec: 58.0, scoreStatus: 'measured', thresholdSec: 60, isQualified: true,  deltaSec: null, rawScore: null, projectId: '50back', time: 58.0, judge: 'pass' },
  { _id: 'r003', recordKey: '2025-10#s001#50brst', studentId: 's001', termId: '2025-10', classId: 'goldfish', eventKey: '50brst', scoreSec: 71.0, scoreStatus: 'measured', thresholdSec: 70, isQualified: false, deltaSec: null, rawScore: null, projectId: '50brst', time: 71.0, judge: 'fail' },
  { _id: 'r004', recordKey: '2025-10#s001#50free', studentId: 's001', termId: '2025-10', classId: 'goldfish', eventKey: '50free', scoreSec: 51.0, scoreStatus: 'measured', thresholdSec: 50, isQualified: false, deltaSec: null, rawScore: null, projectId: '50free', time: 51.0, judge: 'fail' },
  // 小鲲 goldfish 2025-10(含缺测)
  { _id: 'r005', recordKey: '2025-10#s002#50fly',  studentId: 's002', termId: '2025-10', classId: 'goldfish', eventKey: '50fly',  scoreSec: null,  scoreStatus: 'missing',  thresholdSec: 60, isQualified: false, deltaSec: null, rawScore: null, projectId: '50fly', time: null, judge: 'miss' },
  { _id: 'r006', recordKey: '2025-10#s002#50back', studentId: 's002', termId: '2025-10', classId: 'goldfish', eventKey: '50back', scoreSec: 56.5, scoreStatus: 'measured', thresholdSec: 60, isQualified: true,  deltaSec: null, rawScore: null, projectId: '50back', time: 56.5, judge: 'pass' },
  { _id: 'r007', recordKey: '2025-10#s002#50brst', studentId: 's002', termId: '2025-10', classId: 'goldfish', eventKey: '50brst', scoreSec: 67.5, scoreStatus: 'measured', thresholdSec: 70, isQualified: true,  deltaSec: null, rawScore: null, projectId: '50brst', time: 67.5, judge: 'pass' },
  { _id: 'r008', recordKey: '2025-10#s002#50free', studentId: 's002', termId: '2025-10', classId: 'goldfish', eventKey: '50free', scoreSec: 47.0, scoreStatus: 'measured', thresholdSec: 50, isQualified: true,  deltaSec: null, rawScore: null, projectId: '50free', time: 47.0, judge: 'pass' },
  // 小澜 dolphin 2025-10
  { _id: 'r009', recordKey: '2025-10#s003#50fly',  studentId: 's003', termId: '2025-10', classId: 'dolphin', eventKey: '50fly',  scoreSec: 53.0, scoreStatus: 'measured', thresholdSec: 55, isQualified: true, deltaSec: null, rawScore: null, projectId: '50fly', time: 53.0, judge: 'pass' },
  { _id: 'r010', recordKey: '2025-10#s003#50back', studentId: 's003', termId: '2025-10', classId: 'dolphin', eventKey: '50back', scoreSec: 50.0, scoreStatus: 'measured', thresholdSec: 55, isQualified: true, deltaSec: null, rawScore: null, projectId: '50back', time: 50.0, judge: 'pass' },
  { _id: 'r011', recordKey: '2025-10#s003#50brst', studentId: 's003', termId: '2025-10', classId: 'dolphin', eventKey: '50brst', scoreSec: 58.5, scoreStatus: 'measured', thresholdSec: 60, isQualified: true, deltaSec: null, rawScore: null, projectId: '50brst', time: 58.5, judge: 'pass' },
  { _id: 'r012', recordKey: '2025-10#s003#50free', studentId: 's003', termId: '2025-10', classId: 'dolphin', eventKey: '50free', scoreSec: 42.0, scoreStatus: 'measured', thresholdSec: 45, isQualified: true, deltaSec: null, rawScore: null, projectId: '50free', time: 42.0, judge: 'pass' },
]

async function wipeCollection(name) {
  const allRes = await db.collection(name).limit(1000).get()
  for (const item of allRes.data) {
    await db.collection(name).doc(item._id).remove()
  }
}

async function seedCollection(name, items, idField = '_id') {
  let inserted = 0
  for (const item of items) {
    try {
      // 用业务 id 当 _id(便于跨集合引用,如 students._id = score_records.studentId)
      const { [idField]: docId, ...data } = item
      await db.collection(name).doc(docId).set({ data })
      inserted++
    } catch (e) {
      console.warn(`[seedStudents] skip ${name}/${item[idField]}:`, e.message)
    }
  }
  return inserted
}

exports.main = async (event) => {
  if (event.force) {
    await wipeCollection('score_records')
    await wipeCollection('students')
    await wipeCollection('classes')
    await wipeCollection('terms')
  }

  const classes = await seedCollection('classes', CLASSES)
  const terms = await seedCollection('terms', TERMS)
  const students = await seedCollection('students', STUDENTS)
  const scoreRecords = await seedCollection('score_records', SCORES)

  return {
    inserted: { classes, terms, students, score_records: scoreRecords },
    total: { classes: CLASSES.length, terms: TERMS.length, students: STUDENTS.length, score_records: SCORES.length },
  }
}