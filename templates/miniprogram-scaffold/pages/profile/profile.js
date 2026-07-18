// pages/profile/profile.js — 我的
// Reviewer 约束:这个文件 ≤ ~30 行逻辑。
// 角色切换走 shared/role.js(utils 里的 wx.* 白名单模块)。

const { getRole, toggleRole } = require('../../shared/role.js');

const ROLE_LABEL = { coach: '教练', parent: '家长' };

Page({
  data: {
    role: 'coach',
    roleLabel: '教练',
  },

  onLoad() {
    const role = getRole();
    this.setData({ role, roleLabel: ROLE_LABEL[role] });
  },

  toggleRole() {
    const role = toggleRole();
    this.setData({ role, roleLabel: ROLE_LABEL[role] });
  },
});