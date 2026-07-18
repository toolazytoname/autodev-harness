<script setup>
import { onLaunch } from '@dcloudio/uni-app'
import { callFn } from '@/common/cloud.js'
import { useRoleStore } from '@/store/role.js'

onLaunch(() => {
  console.log('[YuYue] App Launch')
  // 初始化云开发(微信小程序端)
  // #ifdef MP-WEIXIN
  if (typeof wx !== 'undefined' && wx.cloud) {
    wx.cloud.init({ traceUser: true })
    // 调 login 云函数拿角色
    callFn('login').then((res) => {
      const roleStore = useRoleStore()
      roleStore.setRole(res.result?.role || 'parent')
    }).catch((err) => {
      console.warn('[YuYue] login cloud function failed:', err)
    })
  }
  // #endif
})
</script>

<style lang="scss">
/* 全局样式 — 由 uni.scss 注入变量 */
@import '@/static/css/tokens.scss';

page {
  background-color: var(--bg);
  color: var(--ink);
  font-family: var(--font);
  font-size: 28rpx;
  line-height: 1.5;
}
</style>