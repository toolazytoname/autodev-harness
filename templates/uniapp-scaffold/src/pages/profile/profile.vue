<script setup>
import { computed } from 'vue'
import { useRoleStore } from '@/store/role.js'

const roleStore = useRoleStore()

const roleLabel = computed(() => {
  return roleStore.role === 'coach' ? '教练' : roleStore.role === 'admin' ? '管理员' : '家长'
})

function toggleRole() {
  roleStore.toggle()
  uni.showToast({ title: `已切换为 ${roleStore.role === 'coach' ? '教练' : '家长' }`, icon: 'none' })
}

function logout() {
  uni.showModal({
    title: '退出登录',
    content: '确定要退出吗?',
    success: (res) => {
      if (res.confirm) {
        uni.showToast({ title: '已退出(待接云函数)', icon: 'none' })
      }
    },
  })
}
</script>

<template>
  <view class="page">
    <view class="profile-card">
      <view class="avatar" />
      <view class="info">
        <text class="name">用户 {{ roleLabel }}</text>
        <text class="role">泳动联萌游泳俱乐部</text>
      </view>
    </view>

    <view v-if="roleStore.isCoach" class="section">
      <text class="section-title">班级教练配置</text>
      <text class="section-desc">管理每个班级的执教教练(支持多人)</text>
      <!-- TODO: 班级教练列表 + 配置入口 -->
    </view>

    <view v-else class="section">
      <text class="section-title">我的孩子</text>
      <text class="section-desc">绑定学员后,可在此进入其成绩详情</text>
      <!-- TODO: 孩子列表 -->
    </view>

    <view class="actions">
      <button class="btn" @click="toggleRole">切换角色(测试)</button>
      <button class="btn btn-danger" @click="logout">退出登录</button>
    </view>
  </view>
</template>

<style lang="scss" scoped>
.page {
  padding: var(--sp-row);
  display: flex;
  flex-direction: column;
  gap: var(--sp-row);
}
.profile-card {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
  display: flex;
  align-items: center;
  gap: var(--sp-col);
}
.avatar {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  background: var(--aqua-light);
}
.info {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.name {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--ink);
}
.role {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
  margin-top: 4rpx;
}
.section {
  background: var(--bg-card);
  border-radius: var(--radius);
  padding: var(--sp-col);
}
.section-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--ink);
  display: block;
  margin-bottom: var(--sp-col-sm);
}
.section-desc {
  font-size: var(--fs-sm);
  color: var(--ink-grey);
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
.btn-danger {
  color: var(--fail);
  border-color: var(--fail);
}
</style>