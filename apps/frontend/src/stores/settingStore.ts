import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

const RESULTS_PER_SEARCH_KEY = 'settings.resultsPerSearch'
const SHOW_RELEVANCE_SCORE_KEY = 'settings.showRelevanceScore'
const DEFAULT_RESULTS_PER_SEARCH = 5
const MOBILE_SIDEBAR_QUERY = '(max-width: 900px)'

function readResultsPerSearch() {
  try {
    const saved = Number(localStorage.getItem(RESULTS_PER_SEARCH_KEY))
    if (Number.isFinite(saved) && saved >= 2 && saved <= 9) return saved
  } catch {}
  return DEFAULT_RESULTS_PER_SEARCH
}

function readShowRelevanceScore() {
  try {
    const saved = localStorage.getItem(SHOW_RELEVANCE_SCORE_KEY)
    if (saved === 'true') return true
    if (saved === 'false') return false
  } catch {}
  return true
}

export const useSettingStore = defineStore('setting', () => {
  const LeftTabHidden = ref(false)
  const IsMobileLayout = ref(false)
  const MobileSidebarOpen = ref(false)
  const ResultsPerSearch = ref(readResultsPerSearch())
  const ShowRelevanceScore = ref(readShowRelevanceScore())

  if (typeof window !== 'undefined') {
    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_QUERY)
    const syncMobileLayout = (matches: boolean) => {
      IsMobileLayout.value = matches
      if (matches) MobileSidebarOpen.value = false
    }
    syncMobileLayout(mediaQuery.matches)
    try {
      mediaQuery.addEventListener('change', (event) => syncMobileLayout(event.matches))
    } catch {
      mediaQuery.addListener((event) => syncMobileLayout(event.matches))
    }
  }

  const HideLeftTab = () => {
    LeftTabHidden.value = !LeftTabHidden.value
  }

  const OpenMobileSidebar = () => {
    MobileSidebarOpen.value = true
  }

  const CloseMobileSidebar = () => {
    MobileSidebarOpen.value = false
  }

  const ToggleSidebar = () => {
    if (IsMobileLayout.value) {
      MobileSidebarOpen.value = !MobileSidebarOpen.value
      return
    }
    HideLeftTab()
  }

  watch(ResultsPerSearch, (value) => {
    try {
      localStorage.setItem(RESULTS_PER_SEARCH_KEY, String(value))
    } catch {}
  })

  watch(ShowRelevanceScore, (value) => {
    try {
      localStorage.setItem(SHOW_RELEVANCE_SCORE_KEY, String(value))
    } catch {}
  })

  return {
    LeftTabHidden,
    IsMobileLayout,
    MobileSidebarOpen,
    ResultsPerSearch,
    ShowRelevanceScore,
    HideLeftTab,
    OpenMobileSidebar,
    CloseMobileSidebar,
    ToggleSidebar,
  }
})
