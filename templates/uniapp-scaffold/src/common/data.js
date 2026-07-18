/**
 * src/common/data.js — 静态数据(纯函数模块,无平台 API 调用)
 *
 * 数据来源:从 OD `shared.js` 翻译,字段结构对等保留。
 * MVP 阶段这些数据通过 `seedStudents` 云函数灌进云数据库;
 * 这里保留为 fallback,方便离线 / H5 预览模式。
 */

// 班级(金鱼 → 海豚 → 旗鱼 → 蛟龙 → 蛟龙竞训队)
//
// v2 schema:
//   - id             : 业务主键,与云数据库 classes._id 对齐
//   - name           : 展示名
//   - level          : 1=提高 / 2=初级 / 3=中级 / 4=高级 / 5=竞技
//   - projectSet     : [v1 alias] 旧 projectSet,UI/旧代码兼容 — 新代码请用 eventKeys
//   - eventKeys      : [v2 canonical] 该班级考核项目 ID 列表(从全局 12 项含 50leg 中取子集)
//   - standards      : [v2 canonical] eventKey → { normalSec, elite2Sec?, elite1Sec? } 达标线
//                       注意:达标线不是 Excel "种子成绩"列!种子成绩来自配置或晋级标准图
//   - promotionRule  : [v2 canonical] 晋级规则(ruleVersion + groups[])
//   - coachIds       : [v2 canonical] 当前执教教练 users._id(空数组由 seedStudents 默认填 [])
//   - isActive       : [v2 canonical] true(默认),归档班级 false
//   - createdAt/updatedAt : epoch ms
export const CLASSES = [
  {
    id: 'goldfish',
    name: '金鱼班',
    level: 1,
    projectSet: '50basic',     // [v1 alias]
    eventKeys: ['50fly', '50back', '50brst', '50free', '50leg'],  // 5 项
    standards: {
      '50fly':  { normalSec: 60 },
      '50back': { normalSec: 60 },
      '50brst': { normalSec: 70 },
      '50free': { normalSec: 50 },
      '50leg':  { normalSec: 55 },
    },
    promotionRule: {
      ruleVersion: 1,
      targetClassId: 'dolphin',
      groups: [
        { id: 'tech',  kind: 'manual', checkKey: '会 2 种泳姿并掌握合理技术' },
      ],
    },
    coachIds: [],
    isActive: true,
    createdAt: 1700000000000,
    updatedAt: 1700000000000,
  },
  {
    id: 'dolphin',
    name: '海豚班',
    level: 2,
    projectSet: '50basic',     // 海豚和金鱼共用 50basic(但 standards 不同)
    eventKeys: ['50fly', '50back', '50brst', '50free'],  // 4 项(不含 50leg)
    standards: {
      '50fly':  { normalSec: 55 },
      '50back': { normalSec: 55 },
      '50brst': { normalSec: 60 },
      '50free': { normalSec: 45 },
    },
    promotionRule: {
      ruleVersion: 1,
      targetClassId: 'sailfish',
      groups: [
        { id: 'pass2', kind: 'count', eventKeys: ['50back', '50brst', '50free'], minCount: 2 },
      ],
    },
    coachIds: [],
    isActive: true,
    createdAt: 1700000000000,
    updatedAt: 1700000000000,
  },
  {
    id: 'sailfish',
    name: '旗鱼班',
    level: 3,
    projectSet: '50four',
    eventKeys: ['50fly', '50back', '50brst', '50free'],  // 4 项
    standards: {
      '50fly':  { normalSec: 50 },
      '50back': { normalSec: 50 },
      '50brst': { normalSec: 55 },
      '50free': { normalSec: 40 },
    },
    promotionRule: {
      ruleVersion: 1,
      targetClassId: 'jiaolong',
      groups: [
        { id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 },
      ],
    },
    coachIds: [],
    isActive: true,
    createdAt: 1700000000000,
    updatedAt: 1700000000000,
  },
  {
    id: 'jiaolong',
    name: '蛟龙班',
    level: 4,
    projectSet: '50plus',
    eventKeys: ['50fly', '50back', '50brst', '50free', '100free', '100mix', '200free', '200mix', '400free', '400mix', '800free'],  // 11 项
    standards: {
      '50fly':  { normalSec: 45 },
      '50back': { normalSec: 45 },
      '50brst': { normalSec: 50 },
      '50free': { normalSec: 35 },
      '100free': { normalSec: 90 },
      '100mix':  { normalSec: 100 },
      '200free': { normalSec: 180 },
      '200mix':  { normalSec: 200 },
      '400free': { normalSec: 360 },
      '400mix':  { normalSec: 400 },
      '800free': { normalSec: 800 },
    },
    promotionRule: {
      ruleVersion: 1,
      targetClassId: 'competition',
      groups: [
        { id: 'tech4', kind: 'manual', checkKey: '4 姿技术正确' },
        { id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 },
        { id: 'long1', kind: 'count', eventKeys: ['100free', '100mix', '200free', '200mix'], minCount: 1 },
      ],
    },
    coachIds: [],
    isActive: true,
    createdAt: 1700000000000,
    updatedAt: 1700000000000,
  },
  {
    id: 'competition',
    name: '蛟龙竞训队',
    level: 5,
    projectSet: '50plus',
    eventKeys: ['50fly', '50back', '50brst', '50free', '100free', '100mix', '200free', '200mix', '400free', '400mix', '800free'],  // 11 项
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
    promotionRule: {
      ruleVersion: 1,
      targetClassId: null,  // 终点班,无晋级
      groups: [
        { id: 'pass3', kind: 'count', eventKeys: ['50fly', '50back', '50brst', '50free'], minCount: 3 },
        { id: 'longAll', kind: 'count', eventKeys: ['100free', '200free'], minCount: 2, acceptedLevels: ['elite2', 'elite1'] },
      ],
    },
    coachIds: [],
    isActive: true,
    createdAt: 1700000000000,
    updatedAt: 1700000000000,
  },
]

export const CLASS_BY_ID = Object.fromEntries(CLASSES.map((c) => [c.id, c]))

// 考期(月份)
export const TERMS = [
  { id: '2025-10', label: '2025 年 10 月' },
  { id: '2025-11', label: '2025 年 11 月' },
  { id: '2026-04', label: '2026 年 4 月' },
]

// 考核项目(秒,越小越好)
export const PROJECTS = {
  '50basic': [
    { id: '50fly',  label: '50 蝶', distance: 50, stroke: 'fly' },
    { id: '50back', label: '50 仰', distance: 50, stroke: 'back' },
    { id: '50brst', label: '50 蛙', distance: 50, stroke: 'brst' },
    { id: '50free', label: '50 自', distance: 50, stroke: 'free' },
    { id: '50leg',  label: '50 自腿', distance: 50, stroke: 'free', isLeg: true },
  ],
  '50four': [
    { id: '50fly',  label: '50 蝶', distance: 50, stroke: 'fly' },
    { id: '50back', label: '50 仰', distance: 50, stroke: 'back' },
    { id: '50brst', label: '50 蛙', distance: 50, stroke: 'brst' },
    { id: '50free', label: '50 自', distance: 50, stroke: 'free' },
  ],
  '50plus': [
    { id: '50fly',  label: '50 蝶', distance: 50, stroke: 'fly' },
    { id: '50back', label: '50 仰', distance: 50, stroke: 'back' },
    { id: '50brst', label: '50 蛙', distance: 50, stroke: 'brst' },
    { id: '50free', label: '50 自', distance: 50, stroke: 'free' },
    { id: '100free', label: '100 自', distance: 100, stroke: 'free' },
    { id: '100mix',  label: '100 混', distance: 100, stroke: 'mix' },
    { id: '200free', label: '200 自', distance: 200, stroke: 'free' },
    { id: '200mix',  label: '200 混', distance: 200, stroke: 'mix' },
    { id: '400free', label: '400 自', distance: 400, stroke: 'free' },
    { id: '400mix',  label: '400 混', distance: 400, stroke: 'mix' },
    { id: '800free', label: '800 自', distance: 800, stroke: 'free' },
  ],
}

// 晋级达标线(秒) — [v1 alias]
// v2 推荐从 CLASS_BY_ID[id].standards[eventKey].normalSec 取
// 这里保留为快速访问 alias;V3 移除
export const PROMO_LINES = {
  goldfish:   { '50fly': 60, '50back': 60, '50brst': 70, '50free': 50, '50leg': 55 },
  dolphin:    { '50fly': 55, '50back': 55, '50brst': 60, '50free': 45 },
  sailfish:   { '50fly': 50, '50back': 50, '50brst': 55, '50free': 40 },
  jiaolong:   { '50fly': 45, '50back': 45, '50brst': 50, '50free': 35,
                '100free': 90, '100mix': 100, '200free': 180, '200mix': 200 },
  competition:{ '50fly': 40, '50back': 40, '50brst': 45, '50free': 32,
                '100free': 75, '100mix': 85, '200free': 160, '200mix': 180,
                '400free': 360, '400mix': 400, '800free': 800 },
}

// 晋级条件
export const PROMO_RULES = {
  'goldfish→dolphin':   { requires: 0, technique: '会 2 种泳姿并掌握合理技术' },
  'dolphin→sailfish':   { requires: 2, of: ['50back', '50brst', '50free'] },
  'sailfish→jiaolong':  { requires: 3, of: ['50fly', '50back', '50brst', '50free'] },
  'jiaolong→competition': {
    requires: 3,
    of: ['50fly', '50back', '50brst', '50free'],
    bonus: '50M 达标 ≥ 3 项 + 100M/200M 任 1 项达标',
  },
}

// 学员(脱敏示例数据 — 实际从云数据库 students 集合读)
//
// v2 canonical schema:
//   {
//     _id (业务主键 = s001/s002),
//     name, nameNormalized,
//     classId,                 // 当前班级
//     coachIds: string[],      // [v2 canonical] 执教教练 users._id 列表
//     parentOpenids: string[], // [v2 canonical] 关联家长 openid
//     age, birthYear, ageRaw,
//     firstTermId,             // [v2 canonical] 首次考期 → terms._id
//     classHistory: [{ classId, fromTermId, toTermId, changedAt, changedBy, reason }],
//     status: 'active' | 'archived',
//     needsClassReview: boolean, // 2025.10 第三表(旗鱼&蛟龙混合)导入后置 true
//     sourceMeta: { importedFrom: { fileName, sheetName, rowStart } },
//     createdAt, updatedAt, deletedAt,
//   }
//
// v1 alias 保留:`coach`(字符串,coachIds[0] 对应 users.name)/`firstTerm`(字符串,firstTermId 同值)
export const STUDENTS = [
  { id: 's001', name: '小鲤', nameNormalized: '小鲤',
    classId: 'goldfish', coachIds: [], parentOpenids: [],
    age: 7, birthYear: 2018, ageRaw: '7',
    firstTermId: '2025-10',
    classHistory: [{ classId: 'goldfish', fromTermId: '2025-10' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    // v1 alias
    coach: '王教练', firstTerm: '2025-10' },
  { id: 's002', name: '小鲲', nameNormalized: '小鲲',
    classId: 'goldfish', coachIds: [], parentOpenids: [],
    age: 8, birthYear: 2017, ageRaw: '8',
    firstTermId: '2025-10',
    classHistory: [{ classId: 'goldfish', fromTermId: '2025-10' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    coach: '王教练', firstTerm: '2025-10' },
  { id: 's003', name: '小澜', nameNormalized: '小澜',
    classId: 'dolphin', coachIds: [], parentOpenids: [],
    age: 9, birthYear: 2016, ageRaw: '9',
    firstTermId: '2025-10',
    classHistory: [{ classId: 'goldfish', fromTermId: '2025-10', toTermId: '2025-11', changedAt: 1730000000000, reason: '达标晋升' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    coach: '李教练', firstTerm: '2025-10' },
  { id: 's004', name: '小川', nameNormalized: '小川',
    classId: 'dolphin', coachIds: [], parentOpenids: [],
    age: 10, birthYear: 2016, ageRaw: '10',
    firstTermId: '2025-11',
    classHistory: [{ classId: 'dolphin', fromTermId: '2025-11' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    coach: '李教练', firstTerm: '2025-11' },
  { id: 's005', name: '小泽', nameNormalized: '小泽',
    classId: 'sailfish', coachIds: [], parentOpenids: [],
    age: 11, birthYear: 2015, ageRaw: '11',
    firstTermId: '2025-10',
    classHistory: [{ classId: 'sailfish', fromTermId: '2025-10' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    coach: '陈教练', firstTerm: '2025-10' },
  { id: 's006', name: '小舟', nameNormalized: '小舟',
    classId: 'jiaolong', coachIds: [], parentOpenids: [],
    age: 12, birthYear: 2014, ageRaw: '12',
    firstTermId: '2025-11',
    classHistory: [{ classId: 'jiaolong', fromTermId: '2025-11' }],
    status: 'active', needsClassReview: false,
    sourceMeta: { importedFrom: { fileName: 'mock', sheetName: 'mock' } },
    createdAt: 1700000000000, updatedAt: 1700000000000,
    coach: '陈教练', firstTerm: '2025-11' },
]

export const STUDENT_BY_ID = Object.fromEntries(STUDENTS.map((s) => [s.id, s]))

// 成绩(脱敏 — 实际从云数据库 score_records 集合读)
//
// v2 canonical schema:
//   {
//     studentId, termId,
//     eventKey,           // canonical (was: projectId)
//     scoreSec,           // canonical (was: time)
//     scoreStatus,        // canonical: 'measured' | 'missing' | 'invalid' | 'not_applicable'  (was: judge: 'pass'|'warn'|'fail'|'miss')
//     rawScore,           // 原始字符串(用于审计,如 "4′16″49")
//     classId,            // 考试时班级快照(V2 冗余,防转班改历史)
//     recordKey,          // `termId#studentId#eventKey` 唯一键
//     source,             // {fileName, sheetName, rowStart, sourceColumnValues, ...}
//     deltaSec,           // scoreSec - previousScoreSec(负数=进步)
//     isQualified,        // 按 scoreSec <= thresholdSec 重算
//     thresholdSec,       // 入库时 class.standards[eventKey].normalSec 快照
//     createdBy, updatedBy,
//     createdAt, updatedAt,
//   }
//
// MVP scaffold 短期同时输出 `projectId/time/judge` v1 alias,UI 层用 v1 judge
// 显示色阶;V3 移除 v1 alias。
export const SCORES = [
  // 小鲤 2025-10(v2 canonical + v1 alias)
  { studentId: 's001', termId: '2025-10', classId: 'goldfish',
    eventKey: '50fly',  scoreSec: 62.5, scoreStatus: 'measured',
    thresholdSec: 60, isQualified: false, deltaSec: null,
    projectId: '50fly', time: 62.5, judge: 'fail' },
  { studentId: 's001', termId: '2025-10', classId: 'goldfish',
    eventKey: '50back', scoreSec: 58.0, scoreStatus: 'measured',
    thresholdSec: 60, isQualified: true, deltaSec: null,
    projectId: '50back', time: 58.0, judge: 'pass' },
  { studentId: 's001', termId: '2025-10', classId: 'goldfish',
    eventKey: '50brst', scoreSec: 71.0, scoreStatus: 'measured',
    thresholdSec: 70, isQualified: false, deltaSec: null,
    projectId: '50brst', time: 71.0, judge: 'fail' },
  { studentId: 's001', termId: '2025-10', classId: 'goldfish',
    eventKey: '50free', scoreSec: 51.0, scoreStatus: 'measured',
    thresholdSec: 50, isQualified: false, deltaSec: null,
    projectId: '50free', time: 51.0, judge: 'fail' },
  // 小鲲 2025-10(含缺测)
  { studentId: 's002', termId: '2025-10', classId: 'goldfish',
    eventKey: '50fly',  scoreSec: null, scoreStatus: 'missing',
    thresholdSec: 60, isQualified: false, deltaSec: null,
    projectId: '50fly', time: null, judge: 'miss' },
  { studentId: 's002', termId: '2025-10', classId: 'goldfish',
    eventKey: '50back', scoreSec: 56.5, scoreStatus: 'measured',
    thresholdSec: 60, isQualified: true, deltaSec: null,
    projectId: '50back', time: 56.5, judge: 'pass' },
  { studentId: 's002', termId: '2025-10', classId: 'goldfish',
    eventKey: '50brst', scoreSec: 67.5, scoreStatus: 'measured',
    thresholdSec: 70, isQualified: true, deltaSec: null,
    projectId: '50brst', time: 67.5, judge: 'pass' },
  { studentId: 's002', termId: '2025-10', classId: 'goldfish',
    eventKey: '50free', scoreSec: 47.0, scoreStatus: 'measured',
    thresholdSec: 50, isQualified: true, deltaSec: null,
    projectId: '50free', time: 47.0, judge: 'pass' },
  // 小澜 2025-10(海豚班,4 项达标)
  { studentId: 's003', termId: '2025-10', classId: 'dolphin',
    eventKey: '50fly',  scoreSec: 53.0, scoreStatus: 'measured',
    thresholdSec: 55, isQualified: true, deltaSec: null,
    projectId: '50fly', time: 53.0, judge: 'pass' },
  { studentId: 's003', termId: '2025-10', classId: 'dolphin',
    eventKey: '50back', scoreSec: 50.0, scoreStatus: 'measured',
    thresholdSec: 55, isQualified: true, deltaSec: null,
    projectId: '50back', time: 50.0, judge: 'pass' },
  { studentId: 's003', termId: '2025-10', classId: 'dolphin',
    eventKey: '50brst', scoreSec: 58.5, scoreStatus: 'measured',
    thresholdSec: 60, isQualified: true, deltaSec: null,
    projectId: '50brst', time: 58.5, judge: 'pass' },
  { studentId: 's003', termId: '2025-10', classId: 'dolphin',
    eventKey: '50free', scoreSec: 42.0, scoreStatus: 'measured',
    thresholdSec: 45, isQualified: true, deltaSec: null,
    projectId: '50free', time: 42.0, judge: 'pass' },
]