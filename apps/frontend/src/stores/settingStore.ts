import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

const RESULTS_PER_SEARCH_KEY = 'settings.resultsPerSearch'
const SHOW_RELEVANCE_SCORE_KEY = 'settings.showRelevanceScore'
const DEFAULT_RESULTS_PER_SEARCH = 5

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
  const ResultsPerSearch = ref(readResultsPerSearch())
  const ShowRelevanceScore = ref(readShowRelevanceScore())

  const HideLeftTab = () => {
    LeftTabHidden.value = !LeftTabHidden.value
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

  return { LeftTabHidden, ResultsPerSearch, ShowRelevanceScore, HideLeftTab }
})
