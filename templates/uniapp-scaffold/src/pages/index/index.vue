<script setup>
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useRoleStore } from '@/store/role.js'

const roleStore = useRoleStore()
const showWelcome = ref(true)

onShow(() => {
  showWelcome.value = true
})

// 教练端入口
const coachEntries = [
  { id: 'students', label: '学员管理', icon: '👥', url: '/pages/students/students' },
  { id: 'overview', label: '班级成绩总览', icon: '📊', url: '/pages/class-overview/class-overview' },
  { id: 'coaches',  label: '班级教练配置', icon: '👨‍🏫', url: '/pages/profile/profile' },
  { id: 'import',   label: '批量导入导出', icon: '📥', url: '/pages/class-overview/class-overview' },
  { id: 'standard', label: '晋级标准查询', icon: '📏', url: '/pages/profile/profile' },
  { id: 'near',     label: '临近达标名单', icon: '🎯', url: '/pages/students/students' },
]

// 家长端入口
const parentEntries = [
  { id: 'kids',    label: '我的孩子',       icon: '👶', url: '/pages/students/students' },
  { id: 'standard', label: '晋级标准查询',  icon: '📏', url: '/pages/profile/profile' },
]

const entries = computed(() => (roleStore.isCoach ? coachEntries : parentEntries))

function go(url) {
  uni.navigateTo({ url })
}
</script>

<template>
  <view class="page">
    <view class="header">
      <image src="/static/logo.png" class="logo" mode="aspectFit" />
      <view class="title-block">
        <text class="title">鱼跃 YuYue</text>
        <text class="subtitle">泳动联萌游泳俱乐部</text>
      </view>
      <view class="role-badge" :class="`role-${roleStore.role}`">
        {{ roleStore.role === 'coach' ? '教练' : roleStore.role === 'admin' ? '管理员' : '家长' }}
      </view>
    </view>

    <view v-if="showWelcome" class="welcome">
      <text class="welcome-title">欢迎使用</text>
      <text class="welcome-desc">数字化成绩与晋级管理,替代传统 Excel</text>
    </view>

    <view class="grid">
      <view
        v-for="e in entries"
        :key="e.id"
        class="grid-card"
        @click="go(e.url)"
        hover-class="grid-card-hover"
      >
        <text class="grid-icon">{{ e.icon }}</text>
        <text class="grid-label">{{ e.label }}</text>
      </view>
    </view>
  </view>
</template>

<style lang="scss" scoped>
.page {
  padding: var(--sp-row);
}
.header {
  display: flex;
  align-items: center;
  padding: var(--sp-col);
  background: var(--bg-card);
  border-radius: var(--radius);
  margin-bottom: var(--sp-row);
}
.logo {
  width: 80rpx;
  height: 80rpx;
  margin-right: var(--sp-col);
}
.title-block {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.title {
  font-size: var(--fs-xl);
  font-weight: 600;
  color: var(--ink);
}
.subtitle {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
  margin-top: 4rpx;
}
.role-badge {
  padding: 4rpx 16rpx;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  background: var(--aqua-light);
  color: var(--aqua-dark);
}
.role-parent {
  background: var(--orange-light);
  color: var(--orange);
}

.welcome {
  padding: var(--sp-col);
  background: var(--bg-card);
  border-radius: var(--radius);
  margin-bottom: var(--sp-row);
}
.welcome-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  display: block;
  color: var(--ink);
}
.welcome-desc {
  font-size: var(--fs-base);
  color: var(--ink-grey);
  display: block;
  margin-top: 4rpx;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-col);
}
.grid-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200rpx;
  transition: transform 0.1s;
}
.grid-card-hover {
  transform: scale(0.98);
  background: var(--bg-hover);
}
.grid-icon {
  font-size: 60rpx;
  display: block;
  margin-bottom: var(--sp-col);
}
.grid-label {
  font-size: var(--fs-base);
  color: var(--ink);
}
</style>