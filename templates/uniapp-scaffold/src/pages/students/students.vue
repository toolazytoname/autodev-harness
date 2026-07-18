<script setup>
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { STUDENTS, CLASSES, CLASS_BY_ID } from '@/common/data.js'
import { useRoleStore } from '@/store/role.js'

const roleStore = useRoleStore()
const keyword = ref('')
const filterClass = ref('')

const classOptions = [{ id: '', name: '全部班级' }, ...CLASSES]

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return STUDENTS.filter((s) => {
    if (filterClass.value && s.classId !== filterClass.value) return false
    if (kw && !s.name.includes(kw)) return false
    return true
  })
})

function openDetail(id) {
  uni.navigateTo({ url: `/pages/students/student-detail?id=${id}` })
}

function addStudent() {
  if (!roleStore.isCoach) return
  // TODO: 教练端 — 调 addStudent 云函数
  uni.showToast({ title: '新增学员(待接云函数)', icon: 'none' })
}

function confirmDelete(id) {
  if (!roleStore.isCoach) return
  uni.showModal({
    title: '确认删除',
    content: '删除学员会同时删除其全部成绩记录,不可恢复。',
    success: (res) => {
      if (res.confirm) {
        // TODO: 调云函数
        uni.showToast({ title: '已删除(待接云函数)', icon: 'none' })
      }
    },
  })
}

function className(classId) {
  return CLASS_BY_ID[classId]?.name || classId
}
</script>

<template>
  <view class="page">
    <view class="searchbar">
      <input
        v-model="keyword"
        class="search-input"
        placeholder="搜索学员姓名"
        placeholder-class="placeholder"
      />
    </view>

    <scroll-view scroll-x class="filter-scroll">
      <view class="filter-row">
        <view
          v-for="c in classOptions"
          :key="c.id || 'all'"
          class="filter-chip"
          :class="{ 'filter-active': filterClass === c.id }"
          @click="filterClass = c.id"
        >
          {{ c.name }}
        </view>
      </view>
    </scroll-view>

    <view v-if="roleStore.isCoach" class="add-bar">
      <button class="btn-add" @click="addStudent">+ 新增学员</button>
    </view>

    <view class="list">
      <view
        v-for="s in filtered"
        :key="s.id"
        class="student-card"
        @click="openDetail(s.id)"
        hover-class="card-hover"
      >
        <view class="student-main">
          <text class="student-name">{{ s.name }}</text>
          <text class="student-class">{{ className(s.classId) }} · {{ s.coach }}</text>
          <text class="student-meta">{{ s.age }} 岁 · 首次 {{ s.firstTerm }}</text>
        </view>
        <view v-if="roleStore.isCoach" class="student-actions">
          <button class="btn-icon" @click.stop="confirmDelete(s.id)">删除</button>
        </view>
      </view>
      <view v-if="filtered.length === 0" class="empty">
        <text>暂无学员,试试切换筛选条件</text>
      </view>
    </view>
  </view>
</template>

<style lang="scss" scoped>
.page {
  padding: var(--sp-row);
}
.searchbar {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
  margin-bottom: var(--sp-row);
}
.search-input {
  font-size: var(--fs-base);
  color: var(--ink);
  width: 100%;
}
.placeholder {
  color: var(--ink-grey);
}

.filter-scroll {
  white-space: nowrap;
  margin-bottom: var(--sp-row);
}
.filter-row {
  display: inline-flex;
  gap: var(--sp-col-sm);
}
.filter-chip {
  padding: 8rpx 24rpx;
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: var(--fs-base);
  color: var(--ink-grey);
}
.filter-active {
  background: var(--aqua);
  color: #fff;
}

.add-bar {
  margin-bottom: var(--sp-row);
}
.btn-add {
  width: 100%;
  background: var(--orange);
  color: #fff;
  border-radius: var(--radius);
  font-size: var(--fs-base);
}

.list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-col);
}
.student-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
  display: flex;
  align-items: center;
}
.card-hover {
  background: var(--bg-hover);
}
.student-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.student-name {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--ink);
}
.student-class {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
}
.student-meta {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
}
.student-actions {
  display: flex;
  gap: var(--sp-col-sm);
}
.btn-icon {
  font-size: var(--fs-sm);
  color: var(--fail);
  background: transparent;
  border: none;
}

.empty {
  padding: var(--sp-row);
  text-align: center;
  color: var(--ink-grey);
  font-size: var(--fs-base);
}
</style>