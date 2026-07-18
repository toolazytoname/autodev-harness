<script setup>
import { ref, computed } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { STUDENTS, CLASSES, TERMS, SCORES, PROJECTS, PROMO_LINES } from '@/common/data.js'
import { judge, fmtTime, scoreCellClass, scoreStatusToJudge } from '@/common/format.js'

const selectedClass = ref('goldfish')
const selectedTerm = ref('2025-10')
const showImportSheet = ref(false)

const classes = CLASSES
const terms = TERMS

const classStudents = computed(() =>
  STUDENTS.filter((s) => s.classId === selectedClass.value)
)

const lines = computed(() => PROMO_LINES[selectedClass.value] || {})

function cellFor(studentId, eventKey) {
  const rec = SCORES.find(
    (r) => r.studentId === studentId && r.termId === selectedTerm.value && (r.eventKey || r.projectId) === eventKey
  )
  if (!rec) return { scoreSec: null, scoreStatus: 'missing', judge: 'miss', label: '—' }
  // v2 path
  if (rec.scoreStatus) {
    const j = scoreStatusToJudge(rec.scoreStatus, rec.scoreSec, rec.thresholdSec)
    return { scoreSec: rec.scoreSec, scoreStatus: rec.scoreStatus, judge: j, label: fmtTime(rec.scoreSec) }
  }
  // v1 fallback
  return { scoreSec: rec.time, scoreStatus: null, judge: rec.judge, label: fmtTime(rec.time) }
}

function cellClass(studentId, eventKey) {
  return scoreCellClass(cellFor(studentId, eventKey) || {})
}

const projects = computed(() => {
  const c = classes.find((c) => c.id === selectedClass.value)
  return c ? (PROJECTS[c.projectSet] || []) : []
})

function pickClass(id) {
  selectedClass.value = id
}

function pickTerm(id) {
  selectedTerm.value = id
}

function openImport() {
  showImportSheet.value = true
}

function closeImport() {
  showImportSheet.value = false
}
</script>

<template>
  <view class="page">
    <view class="class-tabs">
      <view
        v-for="c in classes"
        :key="c.id"
        class="tab"
        :class="{ 'tab-active': c.id === selectedClass }"
        @click="pickClass(c.id)"
      >
        {{ c.name }}
      </view>
    </view>

    <view class="term-tabs">
      <view
        v-for="t in terms"
        :key="t.id"
        class="term-chip"
        :class="{ 'term-active': t.id === selectedTerm }"
        @click="pickTerm(t.id)"
      >
        {{ t.id }}
      </view>
    </view>

    <scroll-view scroll-x class="table-scroll">
      <view class="table">
        <view class="thead">
          <view class="th th-name">学员</view>
          <view v-for="p in projects" :key="p.id" class="th">{{ p.label }}</view>
        </view>
        <view v-for="s in classStudents" :key="s.id" class="tr">
          <view class="td td-name">{{ s.name }}</view>
          <view
            v-for="p in projects"
            :key="p.id"
            class="td"
            :class="cellClass(s.id, p.id)"
          >
            {{ cellFor(s.id, p.id).label }}
          </view>
        </view>
      </view>
    </scroll-view>

    <view class="actions">
      <button class="btn btn-primary" @click="openImport">批量导入</button>
      <button class="btn">导出 Excel</button>
    </view>

    <view v-if="showImport" class="scrim" @click="closeImport">
      <view class="sheet" @click.stop>
        <text class="sheet-title">批量导入成绩</text>
        <text class="sheet-desc">选择考期 Excel,系统解析预览比对,确认入库。</text>
        <button class="btn btn-primary" @click="closeImport">关闭</button>
      </view>
    </view>
  </view>
</template>

<style lang="scss" scoped>
.page {
  padding: var(--sp-row);
}
.class-tabs {
  display: flex;
  gap: var(--sp-col-sm);
  margin-bottom: var(--sp-row);
  flex-wrap: wrap;
}
.tab {
  padding: 8rpx 24rpx;
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: var(--fs-base);
  color: var(--ink-grey);
}
.tab-active {
  background: var(--aqua);
  color: #fff;
}
.term-tabs {
  display: flex;
  gap: var(--sp-col-sm);
  margin-bottom: var(--sp-row);
}
.term-chip {
  padding: 6rpx 16rpx;
  border-radius: var(--radius-sm);
  background: var(--bg-grey);
  font-size: var(--fs-sm);
  color: var(--ink-grey);
}
.term-active {
  background: var(--orange-light);
  color: var(--orange);
}
.table-scroll {
  white-space: nowrap;
}
.table {
  display: inline-block;
  background: var(--bg-card);
  border-radius: var(--radius);
  overflow: hidden;
}
.thead {
  display: flex;
  background: var(--bg-grey);
}
.th {
  width: 120rpx;
  padding: var(--sp-col);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink);
}
.th-name {
  width: 160rpx;
}
.tr {
  display: flex;
  border-top: 1rpx solid var(--border);
}
.td {
  width: 120rpx;
  padding: var(--sp-col);
  font-size: var(--fs-base);
  text-align: center;
}
.td-name {
  width: 160rpx;
  text-align: left;
  font-weight: 500;
}
.cell-pass { color: var(--pass); }
.cell-warn { color: var(--warn); }
.cell-fail { color: var(--fail); }
.cell-miss { color: var(--miss); }

.actions {
  display: flex;
  gap: var(--sp-col);
  margin-top: var(--sp-row);
}
.btn {
  flex: 1;
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

.scrim {
  position: fixed;
  inset: 0;
  background: var(--mask);
  display: flex;
  align-items: flex-end;
}
.sheet {
  width: 100%;
  background: var(--bg-card);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  padding: var(--sp-row);
}
.sheet-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  display: block;
  margin-bottom: var(--sp-col);
}
.sheet-desc {
  font-size: var(--fs-base);
  color: var(--ink-grey);
  display: block;
  margin-bottom: var(--sp-row);
}
</style>