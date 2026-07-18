// AutoDevHarness — miniprogram scaffold
// 鱼跃 YuYue 学员管理系统 — 全局 app 入口
//
// 这个文件由 generator agent 在第一个 task 中 fork 自
// templates/miniprogram-scaffold/。后续 task 不要修改 app.js
// 除非真的需要新增全局生命周期。
//
// Reviewer 约束(miniprogram reviewer §3):
//   app.js 是允许使用 wx.* 的文件之一。

const { getRole } = require('./shared/role.js');

App({
  onLaunch() {
    // 启动时恢复角色(教练/家长),持久化在 storage 层
    this.globalData.role = getRole();
  },

  onShow() {
    // 小程序回到前台时刷新角色(用户可能在其他页面切换过)
    this.globalData.role = getRole();
  },

  globalData: {
    role: 'coach',  // 'coach' | 'parent',由 shared/role.js 同步到 wx.storage
  },
});