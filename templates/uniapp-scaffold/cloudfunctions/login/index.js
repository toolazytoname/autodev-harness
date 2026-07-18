// 云函数 login — 微信 openid → role 鉴权
// 部署:右键 cloudfunctions/login → 上传并部署(云端安装依赖)
//
// 输入:{} (空对象即可,openid 自动从 wx.cloud 上下文拿)
// 输出:{ openid, role: 'coach'|'parent'|'admin', name }
//
// MVP 简化版:首次登录默认 role=parent。教练账号通过云数据库
// `users` 集合手动维护(openid → role 映射)。

const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()

exports.main = async (_event, _context) => {
  const wxContext = cloud.getWXContext()
  const openid = wxContext.OPENID
  if (!openid) {
    return { error: 'no OPENID in context' }
  }

  // 查 users 集合
  const userRes = await db.collection('users').where({ openid }).limit(1).get()
  if (userRes.data && userRes.data.length > 0) {
    const user = userRes.data[0]
    return { openid, role: user.role || 'parent', name: user.name || '用户' }
  }

  // 首次登录:默认 parent,并插入 users 集合
  await db.collection('users').add({
    data: {
      openid,
      role: 'parent',
      name: '用户',
      createdAt: Date.now(),
    },
  })
  return { openid, role: 'parent', name: '用户' }
}