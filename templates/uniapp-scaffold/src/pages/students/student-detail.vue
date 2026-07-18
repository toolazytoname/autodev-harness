<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { STUDENT_BY_ID, CLASS_BY_ID, TERMS, SCORES, PROJECTS, PROMO_LINES, PROMO_RULES } from '@/common/data.js'
import { fmtTime, fmtDiff, promoProgress, summarizePass, scoreStatusToJudge } from '@/common/format.js'
import { lineChart, barChart, donut } from '@/common/charts.js'
import { useRoleStore } from '@/store/role.js'

const roleStore = useRoleStore()
const studentId = ref('')
const student = computed(() => STUDENT_BY_ID[studentId.value])
const klass = computed(() => (student.value ? CLASS_BY_ID[student.value.classId] : null))
const projects = computed(() => (klass.value ? PROJECTS[klass.value.projectSet] : []))
const lines = computed(() => (klass.value ? PROMO_LINES[klass.value.classId] : {}))

onLoad((q) => {
  studentId.value = q?.id || ''
})

// 成绩按考期分组
const scoreByTerm = computed(() => {
  const map = {}
  SCORES.filter((s) => s.studentId === studentId.value).forEach((s) => {
    if (!map[s.termId]) map[s.termId] = []
    map[s.termId].push(s)
  })
  return map
})

// 当前班级达标进度(用 summarizePass 汇总,处理多次成绩 + 缺测)
const progress = computed(() => {
  if (!student.value || !klass.value) {
    return { passed: 0, required: 0, next: '下一班' }
  }
  const allScores = SCORES.filter((s) => s.studentId === studentId.value)
  const projectIds = projects.value.map((p) => p.id)
  const summary = summarizePass(allScores, projectIds)
  return {
    passed: summary.passed,
    required: summary.required,
    next: '下一班',
  }
})

// 折线图数据(50 自 趋势)
const trendData = computed(() => {
  if (!student.value) return []
  const points = []
  TERMS.forEach((t) => {
    const rec = SCORES.find(
      (r) => r.studentId === studentId.value && r.termId === t.id && (r.eventKey || r.projectId) === '50free'
    )
    const sec = rec ? (rec.scoreSec ?? rec.time) : null
    if (rec && sec != null) {
      points.push({ x: t.id.slice(2), y: sec })
    }
  })
  return points
})
const trendSvg = computed(() => lineChart(trendData.value, lines.value['50free'] || null))

// 柱状图(各泳姿当前 vs 达标线)
const barData = computed(() => {
  if (!student.value) return []
  return projects.value.map((p) => {
    const recs = SCORES.filter(
      (r) => r.studentId === studentId.value && (r.eventKey || r.projectId) === p.id && (r.scoreSec ?? r.time) != null
    )
    const last = recs[recs.length - 1]
    return {
      label: p.label,
      value: last ? (last.scoreSec ?? last.time) : null,
      target: lines.value[p.id] || 0,
    }
  })
})
const barSvg = computed(() => barChart(barData.value))

const donutSvg = computed(() =>
  donut(progress.value.passed, progress.value.required || 1)
)

const progressText = computed(() =>
  promoProgress(progress.value.passed, progress.value.required, progress.value.next)
)

function exportPoster() {
  uni.showToast({ title: '导出海报(待接 canvas)', icon: 'none' })
}

function editLatest() {
  if (!roleStore.isCoach) return
  uni.showToast({ title: '修改最新成绩(待接云函数)', icon: 'none' })
}

function goBack() {
  uni.navigateBack({ delta: 1 })
}
</script>

<template>
  <view v-if="student" class="page">
    <view class="info-card">
      <text class="name">{{ student.name }}</text>
      <text class="meta">{{ klass?.name }} · {{ student.coach }} · {{ student.age }} 岁</text>
      <view class="progress-row">
        <rich-text :nodes="donutSvg" class="donut" />
        <view class="progress-text-block">
          <text class="progress-title">晋级达标进度</text>
          <text class="progress-desc">{{ progressText }}</text>
        </view>
      </view>
    </view>

    <view class="chart-card">
      <text class="chart-title">50 自进步趋势</text>
      <rich-text :nodes="trendSvg" class="chart-svg" />
    </view>

    <view class="chart-card">
      <text class="chart-title">各泳姿能力对比</text>
      <rich-text :nodes="barSvg" class="chart-svg" />
    </view>

    <view class="actions">
      <button class="btn btn-primary" @click="exportPoster">导出海报</button>
      <button v-if="roleStore.isCoach" class="btn" @click="editLatest">修改最新成绩</button>
      <button class="btn" @click="goBack">返回班级总览</button>
    </view>
  </view>
  <view v-else class="empty">
    <text>学员不存在</text>
  </view>
</template>

<style lang="scss" scoped>
.page {
  padding: var(--sp-row);
  display: flex;
  flex-direction: column;
  gap: var(--sp-row);
}
.info-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
}
.name {
  font-size: var(--fs-xxl);
  font-weight: 700;
  color: var(--ink);
  display: block;
}
.meta {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
  display: block;
  margin-top: 4rpx;
}
.progress-row {
  display: flex;
  align-items: center;
  margin-top: var(--sp-col);
  gap: var(--sp-col);
}
.donut {
  flex-shrink: 0;
}
.progress-text-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.progress-title {
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--ink);
}
.progress-desc {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
}

.chart-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
}
.chart-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--ink);
  display: block;
  margin-bottom: var(--sp-col);
}
.chart-svg {
  display: block;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: var(--sp-col);
}
.btn {
  background: var(--bg-card);
  color: var(--ink);
  border: 1rpx solid var(--border);
  border-radius: var(--radius);
  font-size: var(--fs-base);
}
.btn-primary {
  background: var(--aqua);
  color: #fff;
  border: none;
}

.empty {
  padding: var(--sp-row);
  text-align: center;
  color: var(--ink-grey);
}
</style>