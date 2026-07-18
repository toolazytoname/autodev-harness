/**
 * src/common/storage.js — 本地存储适配层(uni.* 白名单文件)
 *
 * 这是 reviewer 例外文件:**允许**调用 uni.* API(因为它本来就是
 * 平台适配层)。其他 common 文件(data.js / format.js / charts.js)
 * 必须保持纯函数,不调用 uni.* / wx.*。
 */

/**
 * 同步读取存储项;不存在时返回 fallback。
 */
export function getItem(key, fallback = null) {
  try {
    const v = uni.getStorageSync(key)
    return v === '' || v == null ? fallback : v
  } catch (e) {
    console.warn('[storage] getItem failed:', key, e)
    return fallback
  }
}

/**
 * 同步写入存储项;失败时 console.warn 不抛出。
 */
export function setItem(key, value) {
  try {
    uni.setStorageSync(key, value)
    return true
  } catch (e) {
    console.warn('[storage] setItem failed:', key, e)
    return false
  }
}

/**
 * 删除存储项。
 */
export function removeItem(key) {
  try {
    uni.removeStorageSync(key)
    return true
  } catch (e) {
    console.warn('[storage] removeItem failed:', key, e)
    return false
  }
}

// 角色相关快捷方法
export function getRole() {
  return getItem('role', 'parent')
}

export function setRole(role) {
  return setItem('role', role)
}

// 成绩更正历史(教练端用)
export function readScoreCorrections() {
  return getItem('score_corrections', [])
}

export function appendScoreCorrection(record) {
  const list = readScoreCorrections()
  list.push({ ...record, ts: Date.now() })
  return setItem('score_corrections', list)
}