import { ref } from 'vue'
import { defineStore } from 'pinia'

export type SettingsSection = 'general' | 'profile'

export const useSettingsModalStore = defineStore('settingsModal', () => {
  const isOpen = ref(false)
  const section = ref<SettingsSection>('general')

  function open(nextSection: SettingsSection = 'general') {
    section.value = nextSection
    isOpen.value = true
  }

  function close() {
    isOpen.value = false
  }

  return {
    isOpen,
    section,
    open,
    close,
  }
})
