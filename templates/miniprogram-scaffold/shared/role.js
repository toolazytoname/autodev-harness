// AutoDevHarness — miniprogram scaffold
// 角色管理(教练/家长) — 唯一允许 wx.* 的 utils 模块
// -------------------------------------------------------------------------
// Reviewer 约束(miniprogram reviewer §3):
//   wx.* 禁止在 utils/* 里,但 storage 类适配层允许。
//   这个文件就是 storage 适配层,作为白名单。
//
// 其他 utils 文件禁止 import 这个文件后调 wx.* —
// 它们应该 require('./storage.js') 后调 getRole() / setRole() 等封装函数,
// 而不是直接调 wx.getStorageSync。
// -------------------------------------------------------------------------

const ROLE_KEY = 'yy_role';

/** 取当前角色,'coach' | 'parent' */
function getRole() {
  try {
    const r = wx.getStorageSync(ROLE_KEY);
    return r === 'parent' ? 'parent' : 'coach';
  } catch (e) {
    return 'coach';
  }
}

/** 设置角色,持久化到 storage */
function setRole(r) {
  const role = r === 'parent' ? 'parent' : 'coach';
  try {
    wx.setStorageSync(ROLE_KEY, role);
  } catch (e) {
    // storage 失败时静默 fallback — 角色不是关键状态
  }
  return role;
}

/** 切换角色(coach <-> parent),返回新角色 */
function toggleRole() {
  return setRole(getRole() === 'coach' ? 'parent' : 'coach');
}

module.exports = { getRole, setRole, toggleRole };