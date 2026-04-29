<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '@/i18n'

type Theme = 'light' | 'dark'

const THEME_KEY = 'theme'

const { locale, setLocale, t } = useI18n()
const theme = ref<Theme>('dark')
const currentLang = computed(() => locale.value)

function readSavedTheme(): Theme | null {
  try {
    const savedTheme = localStorage.getItem(THEME_KEY)
    return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : null
  } catch {
    return null
  }
}

function applyTheme(nextTheme: Theme) {
  try {
    if (typeof (window as any).__setTheme === 'function') {
      ;(window as any).__setTheme(nextTheme)
    } else {
      document.documentElement.dataset.theme = nextTheme
      localStorage.setItem(THEME_KEY, nextTheme)
    }
  } catch {
    document.documentElement.dataset.theme = nextTheme
  }
}

function setTheme(nextTheme: Theme) {
  theme.value = nextTheme
  applyTheme(nextTheme)
}

function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

function toggleLang() {
  setLocale(locale.value === 'en' ? 'ru' : 'en')
}

onMounted(() => {
  const currentTheme =
    (document.documentElement.dataset.theme as Theme) || readSavedTheme() || 'dark'
  theme.value = currentTheme
})
</script>

<template>
  <div class="setting-panel" :aria-label="t('settings.title')">
    <button
      type="button"
      class="setting-button"
      :title="theme === 'dark' ? t('settings.light') : t('settings.dark')"
      :aria-label="theme === 'dark' ? t('settings.light') : t('settings.dark')"
      @click="toggleTheme"
    >
      <span
        class="theme-swatch"
        :class="theme === 'dark' ? 'theme-swatch--dark' : 'theme-swatch--light'"
        aria-hidden="true"
      ></span>
    </button>
    <button
      type="button"
      class="setting-button setting-button--language"
      :title="currentLang === 'en' ? t('settings.langRussian') : t('settings.langEnglish')"
      :aria-label="currentLang === 'en' ? t('settings.langRussian') : t('settings.langEnglish')"
      @click="toggleLang"
    >
      {{ currentLang.toUpperCase() }}
    </button>
  </div>
</template>

<style scoped>
.setting-panel {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 20;
  display: inline-flex;
  gap: 8px;
  padding: 6px;
  color: var(--color-text);
  background: color-mix(in oklab, var(--color-surface), transparent 14%);
  border: 1px solid color-mix(in oklab, var(--color-border), transparent 24%);
  border-radius: 8px;
  box-shadow: 0 10px 26px rgba(2, 6, 23, 0.1);
  opacity: 0.68;
  backdrop-filter: blur(10px);
  transition:
    opacity var(--transition-fast) ease,
    border-color var(--transition-fast) ease;
}

.setting-panel:hover,
.setting-panel:focus-within {
  border-color: color-mix(in oklab, var(--color-border), var(--color-primary) 18%);
  opacity: 1;
}

.setting-button {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: color-mix(in oklab, var(--color-surface), var(--color-bg-secondary) 10%);
  color: var(--color-text);
  cursor: pointer;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  line-height: 1.15;
  transition:
    background var(--transition-fast) ease,
    border-color var(--transition-fast) ease,
    box-shadow var(--transition-fast) ease,
    transform var(--transition-fast) ease;
}

.setting-button:hover {
  border-color: color-mix(in oklab, var(--color-primary-secondary), var(--color-border) 24%);
  background: var(--color-surface);
  transform: translateY(-1px);
}

.setting-button:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--color-focus), transparent 62%);
}

.theme-swatch {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1px solid var(--color-border);
}

.theme-swatch--dark {
  background: linear-gradient(135deg, #0b1020 0 50%, #1f2a44 50% 100%);
}

.theme-swatch--light {
  background: linear-gradient(135deg, #ffffff 0 50%, #f3f8fc 50% 100%);
}

.setting-button--language {
  letter-spacing: 0;
}

@media (max-width: 520px) {
  .setting-panel {
    right: 12px;
    bottom: 12px;
  }
}
</style>
