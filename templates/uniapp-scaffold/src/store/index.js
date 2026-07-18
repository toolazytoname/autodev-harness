/**
 * src/store/index.js — Pinia 入口
 *
 * 各 store 模块(role / students / scores)按需引入。
 */
import { createPinia } from 'pinia'

export const pinia = createPinia()

// 各 store 模块导出
export { useRoleStore } from './role.js'