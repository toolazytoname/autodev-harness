/**
 * src/common/cloud.js — 微信云开发 wx.cloud.* 适配层(wx.cloud 白名单文件)
 *
 * 跟 storage.js 同理:这是 reviewer 例外文件,**允许**调用
 * wx.cloud.* API。其他 common 文件(data.js / format.js / charts.js)
 * 必须保持纯函数。
 *
 * 调用方约定:page / store 通过 `import { callFn, db } from '@/common/cloud.js'`
 * 拿到封装,**禁止**直接写 `wx.cloud.callFunction(...)`。
 */

/**
 * 调云函数
 *
 * @param {string} name  云函数名(如 'login' / 'addStudent')
 * @param {object} data  入参对象
 * @returns {Promise<{result: object, errMsg: string}>}
 */
export function callFn(name, data = {}) {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    if (typeof wx === 'undefined' || !wx.cloud) {
      reject(new Error('[cloud] wx.cloud not available (not in MP-WEIXIN)'))
      return
    }
    wx.cloud.callFunction({
      name,
      data,
      success: (res) => resolve(res),
      fail: (err) => reject(err),
    })
    // #endif
    // #ifndef MP-WEIXIN
    // H5 / 其他平台:返回 mock,方便本地预览
    console.warn(`[cloud] mock callFn(${name}) on non-MP-WEIXIN platform`)
    resolve({ result: { mock: true, name, data }, errMsg: 'mock' })
    // #endif
  })
}

/**
 * 拿到云数据库引用。
 * 调用方需自行 .collection('xxx').where({...}).get()
 *
 * @returns {object|null} wx.cloud.database() 或 null(非 MP-WEIXIN 平台)
 */
export function db() {
  // #ifdef MP-WEIXIN
  if (typeof wx !== 'undefined' && wx.cloud) {
    return wx.cloud.database()
  }
  // #endif
  console.warn('[cloud] db() not available on non-MP-WEIXIN platform')
  return null
}

/**
 * 上传文件到云存储
 *
 * @param {string} cloudPath  云端路径(如 'students/avatar/123.jpg')
 * @param {string} filePath   本地文件路径(uni.chooseImage 选出来的)
 * @returns {Promise<object>}
 */
export function uploadFile(cloudPath, filePath) {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    if (typeof wx === 'undefined' || !wx.cloud) {
      reject(new Error('[cloud] wx.cloud not available'))
      return
    }
    wx.cloud.uploadFile({
      cloudPath,
      filePath,
      success: resolve,
      fail: reject,
    })
    // #endif
    // #ifndef MP-WEIXIN
    console.warn('[cloud] uploadFile mock on non-MP-WEIXIN')
    resolve({ fileID: `mock://${cloudPath}`, mock: true })
    // #endif
  })
}