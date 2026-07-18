/**
 * src/store/role.js — 角色状态(教练 / 家长 / 管理员)
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getRole, setRole } from '@/common/storage.js'

export const useRoleStore = defineStore('role', () => {
  const role = ref(getRole()) // 'coach' | 'parent' | 'admin'

  const isCoach = computed(() => role.value === 'coach' || role.value === 'admin')
  const isParent = computed(() => role.value === 'parent')
  const isAdmin = computed(() => role.value === 'admin')

  function set(newRole) {
    role.value = newRole
    setRole(newRole)
  }

  function toggle() {
    const next = role.value === 'coach' ? 'parent' : 'coach'
    set(next)
  }

  return { role, isCoach, isParent, isAdmin, set, toggle }
})