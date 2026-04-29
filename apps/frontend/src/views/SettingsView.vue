<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from '@/i18n'

type Theme = 'light' | 'dark'
const THEME_KEY = 'theme'

const emit = defineEmits<{
  close: []
}>()
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
      return
    }
    document.documentElement.dataset.theme = nextTheme
    localStorage.setItem(THEME_KEY, nextTheme)
  } catch {
    document.documentElement.dataset.theme = nextTheme
  }
}

function setTheme(nextTheme: Theme) {
  theme.value = nextTheme
  applyTheme(nextTheme)
}

function chooseLang(nextLocale: 'en' | 'ru') {
  setLocale(nextLocale)
}

function closeSettings() {
  emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeSettings()
  }
}

onMounted(() => {
  const currentTheme: Theme =
    (document.documentElement.dataset.theme as Theme) || readSavedTheme() || 'dark'
  theme.value = currentTheme
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="settings-overlay" role="presentation" @click.self="closeSettings">
    <section
      class="settings-modal"
      role="dialog"
      aria-modal="true"
      :aria-label="t('settings.title')"
    >
      <button
        type="button"
        class="settings-close"
        :aria-label="t('common.cancel')"
        @click="closeSettings"
      >
        <span aria-hidden="true"></span>
      </button>

      <aside class="settings-nav" aria-label="Settings sections">
        <button type="button" class="settings-nav__item active">
          <svg
            class="settings-nav__icon"
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M4 7h10" />
            <path d="M18 7h2" />
            <path d="M4 17h2" />
            <path d="M10 17h10" />
            <circle cx="16" cy="7" r="2" />
            <circle cx="8" cy="17" r="2" />
          </svg>
          <span>{{ t('settings.general') }}</span>
        </button>
      </aside>

      <main class="settings-content">
        <header class="settings-header">
          <h1>{{ t('settings.general') }}</h1>
        </header>

        <div class="settings-panel">
          <section class="settings-row">
            <div class="settings-row__text">
              <h2>{{ t('settings.appearance') }}</h2>
              <p>{{ theme === 'dark' ? t('settings.dark') : t('settings.light') }}</p>
            </div>
            <div class="settings-control" role="group" :aria-label="t('settings.appearance')">
              <button
                type="button"
                class="settings-choice"
                :class="{ active: theme === 'dark' }"
                @click="setTheme('dark')"
              >
                <span class="theme-dot theme-dot--dark" aria-hidden="true"></span>
                {{ t('settings.dark') }}
              </button>
              <button
                type="button"
                class="settings-choice"
                :class="{ active: theme === 'light' }"
                @click="setTheme('light')"
              >
                <span class="theme-dot theme-dot--light" aria-hidden="true"></span>
                {{ t('settings.light') }}
              </button>
            </div>
          </section>

          <section class="settings-row">
            <div class="settings-row__text">
              <h2>{{ t('settings.language') }}</h2>
              <p>
                {{
                  currentLang === 'en'
                    ? t('settings.langEnglish')
                    : t('settings.langRussian')
                }}
              </p>
            </div>
            <div class="settings-control" role="group" :aria-label="t('settings.language')">
              <button
                type="button"
                class="settings-choice"
                :class="{ active: currentLang === 'en' }"
                @click="chooseLang('en')"
              >
                EN
                <span>{{ t('settings.langEnglish') }}</span>
              </button>
              <button
                type="button"
                class="settings-choice"
                :class="{ active: currentLang === 'ru' }"
                @click="chooseLang('ru')"
              >
                RU
                <span>{{ t('settings.langRussian') }}</span>
              </button>
            </div>
          </section>
        </div>
      </main>
    </section>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(2, 6, 23, 0.58);
  backdrop-filter: blur(8px);
}

.settings-modal {
  position: relative;
  width: min(940px, calc(100vw - 40px));
  height: min(760px, calc(100vh - 48px));
  min-height: 420px;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--color-border-soft);
  border-radius: 22px;
  background:
    linear-gradient(
      180deg,
      color-mix(in oklab, var(--color-panel-elevated), var(--color-surface) 3%),
      var(--color-panel)
    );
  box-shadow:
    0 28px 80px rgba(0, 0, 0, 0.46),
    0 0 0 1px color-mix(in oklab, var(--color-border-soft), transparent 42%);
}

.settings-close {
  position: absolute;
  top: 22px;
  left: 22px;
  z-index: 3;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  transition:
    background var(--transition-fast) ease,
    color var(--transition-fast) ease;
}

.settings-close:hover,
.settings-close:focus-visible {
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 8%);
  outline: none;
}

.settings-close span,
.settings-close span::after {
  position: absolute;
  width: 18px;
  height: 2px;
  border-radius: 999px;
  background: currentColor;
  content: '';
}

.settings-close span {
  transform: rotate(45deg);
}

.settings-close span::after {
  inset: 0;
  transform: rotate(90deg);
}

.settings-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 80px 18px 18px;
  border-right: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 34%);
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 18%);
}

.settings-nav__item {
  width: 100%;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-weight: 600;
  text-align: left;
  cursor: default;
}

.settings-nav__item.active {
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 7%);
  color: var(--color-text);
  border-color: color-mix(in oklab, var(--color-border-soft), transparent 48%);
}

.settings-nav__icon {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.settings-content {
  min-width: 0;
  overflow-y: auto;
  padding: 36px 40px 44px;
}

.settings-header {
  padding-bottom: 24px;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 30%);
}

.settings-header h1 {
  margin: 0;
  font-size: 1.55rem;
  line-height: 1.2;
  font-weight: 700;
  color: var(--color-text);
}

.settings-panel {
  display: grid;
}

.settings-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  min-width: 0;
  padding: 22px 0;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 46%);
}

.settings-row__text {
  min-width: 0;
}

.settings-row__text h2 {
  margin: 0;
  font-size: 1rem;
  line-height: 1.3;
  font-weight: 650;
  color: var(--color-text);
}

.settings-row__text p {
  margin: 6px 0 0;
  color: var(--color-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}

.settings-control {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.settings-choice {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 28%);
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 18%);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 0.9rem;
  font-weight: 650;
  cursor: pointer;
  transition:
    background var(--transition-fast) ease,
    border-color var(--transition-fast) ease,
    color var(--transition-fast) ease,
    transform var(--transition-fast) ease;
}

.settings-choice span {
  font-weight: 600;
}

.settings-choice:hover,
.settings-choice:focus-visible {
  border-color: var(--color-primary-secondary);
  color: var(--color-text);
  outline: none;
}

.settings-choice.active {
  background: var(--color-primary-secondary);
  border-color: transparent;
  color: var(--color-primary-contrast);
}

.settings-choice:active {
  transform: translateY(1px);
}

.theme-dot {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
  border-radius: 50%;
  border: 1px solid currentColor;
}

.theme-dot--dark {
  background: #0b1020;
}

.theme-dot--light {
  background: #ffffff;
}

@media (max-width: 760px) {
  .settings-overlay {
    padding: 14px;
  }

  .settings-modal {
    width: 100%;
    height: min(760px, calc(100vh - 28px));
    grid-template-columns: 1fr;
  }

  .settings-close {
    top: 14px;
    left: 14px;
  }

  .settings-nav {
    padding: 60px 14px 12px;
    border-right: 0;
    border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 34%);
  }

  .settings-content {
    padding: 22px 20px 28px;
  }

  .settings-row {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .settings-control {
    justify-content: flex-start;
  }
}
</style>
