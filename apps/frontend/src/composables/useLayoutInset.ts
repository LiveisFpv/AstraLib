import { computed } from 'vue'
import { useSettingStore } from '@/stores/settingStore'
import { storeToRefs } from 'pinia'

interface LayoutInsetOptions {
  expanded?: string
  collapsed?: string
  mobile?: string
}

export function useLayoutInset(options?: LayoutInsetOptions) {
  const settingStore = useSettingStore()
  const { IsMobileLayout, LeftTabHidden } = storeToRefs(settingStore)
  const expanded = options?.expanded ?? '60px 20px 20px 310px'
  const collapsed = options?.collapsed ?? '60px 20px 20px 80px'
  const mobile = options?.mobile ?? '70px 12px 12px 12px'

  const layoutInset = computed(() => {
    if (IsMobileLayout.value) return mobile
    return LeftTabHidden.value ? collapsed : expanded
  })

  return {
    IsMobileLayout,
    LeftTabHidden,
    layoutInset,
  }
}
