// pages/students/students.js — 学员管理
// Reviewer 约束:这个文件 ≤ ~30 行逻辑。复杂逻辑放在 utils/data.js 等纯函数里。

Page({
  data: {
    q: '',
    list: [],
    editOpen: false,
    delOpen: false,
    // TODO(g-3): 完整 data(班级 chip 列表、当前选中的学员、编辑表单字段)
  },

  onLoad() {
    this.render();
  },

  onSearch(e) {
    this.setData({ q: e.detail.value });
    this.render();
  },

  render() {
    // TODO(g-3): 走 utils/data.js + utils/format.js 计算 list
  },

  openEdit() {
    this.setData({ editOpen: true });
  },

  closeScrim(e) {
    if (e.target === e.currentTarget) {
      this.setData({ editOpen: false, delOpen: false });
    }
  },

  noop() {},
});