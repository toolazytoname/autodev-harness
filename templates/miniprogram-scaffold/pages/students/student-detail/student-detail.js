// pages/students/student-detail.js — 学员详情
// Reviewer 约束:这个文件 ≤ ~30 行逻辑。

Page({
  data: {
    studentId: '',
    studentName: '',
    // TODO(g-4): 历史成绩、各泳姿达标、晋级进度
  },

  onLoad(query) {
    this.setData({ studentId: query.id || '' });
    // TODO(g-4): 拉学员详情
  },
});