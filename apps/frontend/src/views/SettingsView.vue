<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useSettingStore } from '@/stores/settingStore'
import { useI18n } from '@/i18n'
import type { SettingsSection } from '@/stores/settingsModalStore'
import type { UserUpdateRequest } from '@/api/types'

type Theme = 'light' | 'dark'
const THEME_KEY = 'theme'

const props = withDefaults(
  defineProps<{
    initialSection?: SettingsSection
  }>(),
  {
    initialSection: 'general',
  },
)

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()
const auth = useAuthStore()
const appSettings = useSettingStore()
const { locale, setLocale, t } = useI18n()
const activeSection = ref<SettingsSection>(props.initialSection)
const theme = ref<Theme>('dark')
const currentLang = computed(() => locale.value)
const saving = ref(false)
const successMsg = ref('')
const errorMsg = ref('')

const form = reactive({
  email: '',
  first_name: '',
  last_name: '',
  locale_type: '',
  password: '',
})

watch(
  () => props.initialSection,
  (section) => {
    activeSection.value = section
  },
)

const fullName = computed(() => {
  const user = auth.User
  if (!user) return ''
  return [user.first_name, user.last_name].filter(Boolean).join(' ')
})

const avatarUrl = computed(() => auth.User?.photo || '')

const avatarLetter = computed(() => {
  const user = auth.User
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email || ''
  const trimmed = name.trim()
  return trimmed ? trimmed[0].toUpperCase() : 'U'
})

watch(
  () => auth.User,
  () => {
    resetFormFromUser()
  },
  { immediate: true },
)

function resetFormFromUser() {
  const user = auth.User
  if (!user) return
  form.email = user.email || ''
  form.first_name = user.first_name || ''
  form.last_name = user.last_name || ''
  form.locale_type = user.locale_type || ''
  form.password = ''
}

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

function setSection(section: SettingsSection) {
  successMsg.value = ''
  errorMsg.value = ''
  activeSection.value = section
}

function closeSettings() {
  emit('close')
}

function buildPayload(): UserUpdateRequest {
  const user = auth.User
  const payload: UserUpdateRequest = {}
  if (user) {
    if (form.email && form.email !== user.email) payload.email = form.email
    if (form.first_name !== user.first_name) payload.first_name = form.first_name
    if (form.last_name !== user.last_name) payload.last_name = form.last_name
    if ((form.locale_type || '') !== (user.locale_type || '')) {
      payload.locale_type = form.locale_type || undefined
    }
  } else {
    if (form.email) payload.email = form.email
    if (form.first_name) payload.first_name = form.first_name
    if (form.last_name) payload.last_name = form.last_name
    if (form.locale_type) payload.locale_type = form.locale_type
  }
  if (form.password) payload.password = form.password
  return payload
}

async function saveProfile() {
  successMsg.value = ''
  errorMsg.value = ''
  const payload = buildPayload()
  if (!Object.keys(payload).length) {
    successMsg.value = t('profile.msg.nothing')
    return
  }
  try {
    saving.value = true
    await auth.updateUser(payload)
    successMsg.value = t('profile.msg.updated')
  } catch (e: any) {
    errorMsg.value = e?.message || t('profile.msg.failed')
  } finally {
    saving.value = false
  }
}

async function handleLogout() {
  await auth.logout()
  closeSettings()
  await router.replace('/auth')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeSettings()
  }
}

onMounted(async () => {
  const currentTheme: Theme =
    (document.documentElement.dataset.theme as Theme) || readSavedTheme() || 'dark'
  theme.value = currentTheme
  document.addEventListener('keydown', handleKeydown)
  if (auth.isAuthenticated && !auth.User) {
    try {
      await auth.authenticate()
    } catch {}
  }
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

      <aside class="settings-nav" :aria-label="t('settings.sections')">
        <button
          type="button"
          class="settings-nav__item"
          :class="{ active: activeSection === 'general' }"
          @click="setSection('general')"
        >
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

        <button
          type="button"
          class="settings-nav__item"
          :class="{ active: activeSection === 'profile' }"
          @click="setSection('profile')"
        >
          <svg
            class="settings-nav__icon"
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c1.8-4 4.5-6 8-6s6.2 2 8 6" />
          </svg>
          <span>{{ t('profile.title') }}</span>
        </button>
      </aside>

      <main class="settings-content">
        <header class="settings-header">
          <h1>{{ activeSection === 'general' ? t('settings.general') : t('profile.title') }}</h1>
        </header>

        <div v-if="activeSection === 'general'" class="settings-panel">
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

          <section class="settings-row">
            <div class="settings-row__text">
              <h2>{{ t('settings.resultsPerSearch') }}</h2>
              <p>{{ t('settings.resultsPerSearchDisabled') }}</p>
            </div>
            <div class="settings-control" :aria-label="t('settings.resultsPerSearch')">
              <div class="settings-slider settings-slider--disabled" aria-disabled="true">
                <span class="settings-slider__track" aria-hidden="true">
                  <span class="settings-slider__fill"></span>
                  <span class="settings-slider__thumb"></span>
                  <span class="settings-slider__min">2</span>
                  <span class="settings-slider__value">5</span>
                  <span class="settings-slider__max">9</span>
                </span>
              </div>
            </div>
          </section>

          <section class="settings-row">
            <div class="settings-row__text">
              <h2>{{ t('settings.showRelevanceScore') }}</h2>
              <p>{{ t('paper.scoreTooltip') }}</p>
            </div>
            <div class="settings-control">
              <label class="settings-toggle">
                <input
                  v-model="appSettings.ShowRelevanceScore"
                  type="checkbox"
                  :aria-label="t('settings.showRelevanceScore')"
                />
                <span aria-hidden="true"></span>
              </label>
            </div>
          </section>
        </div>

        <div v-else class="settings-panel">
          <section class="profile-summary">
            <div class="profile-avatar">
              <img v-if="avatarUrl" :src="avatarUrl" :alt="fullName || auth.User?.email || ''" />
              <span v-else>{{ avatarLetter }}</span>
            </div>
            <div class="profile-summary__text">
              <h2>{{ fullName || t('profile.title') }}</h2>
              <p v-if="auth.User?.email">{{ auth.User.email }}</p>
            </div>
          </section>

          <section class="settings-form">
            <label class="settings-field">
              <span>Email</span>
              <input v-model.trim="form.email" type="email" autocomplete="email" />
            </label>
            <label class="settings-field">
              <span>{{ t('profile.form.firstName') }}</span>
              <input
                v-model.trim="form.first_name"
                type="text"
                autocomplete="given-name"
                :placeholder="t('profile.form.firstName')"
              />
            </label>
            <label class="settings-field">
              <span>{{ t('profile.form.lastName') }}</span>
              <input
                v-model.trim="form.last_name"
                type="text"
                autocomplete="family-name"
                :placeholder="t('profile.form.lastName')"
              />
            </label>
            <label class="settings-field">
              <span>{{ t('profile.form.locale') }}</span>
              <input
                v-model.trim="form.locale_type"
                type="text"
                inputmode="text"
                :placeholder="t('profile.form.locale')"
              />
            </label>
            <label class="settings-field settings-field--wide">
              <span>{{ t('profile.form.newPassword') }}</span>
              <input
                v-model="form.password"
                type="password"
                autocomplete="new-password"
                :placeholder="t('profile.form.keepBlank')"
              />
            </label>
          </section>

          <section class="profile-meta">
            <div class="profile-meta__row">
              <span>{{ t('profile.emailConfirmed') }}</span>
              <strong :class="{ ok: auth.User?.email_confirmed, warn: !auth.User?.email_confirmed }">
                {{ auth.User?.email_confirmed ? t('common.yes') : t('common.no') }}
              </strong>
            </div>
            <div v-if="auth.User?.roles?.length" class="profile-meta__row">
              <span>{{ t('profile.roles') }}</span>
              <span class="profile-roles">
                <span v-for="role in auth.User.roles" :key="role" class="profile-role">
                  {{ role }}
                </span>
              </span>
            </div>
          </section>

          <div class="settings-feedback">
            <span v-if="successMsg" class="ok">{{ successMsg }}</span>
            <span v-else-if="errorMsg" class="err">{{ errorMsg }}</span>
          </div>

          <footer class="settings-actions">
            <button type="button" class="settings-button settings-button--danger" @click="handleLogout">
              {{ t('profile.btn.logout') }}
            </button>
            <button type="button" class="settings-button" :disabled="saving" @click="resetFormFromUser">
              {{ t('profile.btn.cancel') }}
            </button>
            <button
              type="button"
              class="settings-button settings-button--primary"
              :disabled="saving"
              @click="saveProfile"
            >
              {{ saving ? t('profile.saving') : t('profile.btn.save') }}
            </button>
          </footer>
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
  cursor: pointer;
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

.settings-choice,
.settings-button {
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
.settings-choice:focus-visible,
.settings-button:hover,
.settings-button:focus-visible {
  border-color: var(--color-primary-secondary);
  color: var(--color-text);
  outline: none;
}

.settings-choice.active,
.settings-button--primary {
  background: var(--color-primary-secondary);
  border-color: transparent;
  color: var(--color-primary-contrast);
}

.settings-button--danger {
  margin-right: auto;
  color: var(--color-danger);
}

.settings-choice:active,
.settings-button:active {
  transform: translateY(1px);
}

.settings-button:disabled {
  cursor: progress;
  opacity: 0.7;
}

.settings-toggle {
  position: relative;
  width: 48px;
  height: 28px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.settings-toggle input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.settings-toggle span {
  position: relative;
  width: 100%;
  height: 100%;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 28%);
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 18%);
  transition:
    background var(--transition-fast) ease,
    border-color var(--transition-fast) ease;
}

.settings-toggle span::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-text-secondary);
  transition:
    background var(--transition-fast) ease,
    transform var(--transition-fast) ease;
}

.settings-toggle input:checked + span {
  border-color: transparent;
  background: var(--color-primary-secondary);
}

.settings-toggle input:checked + span::after {
  background: var(--color-primary-contrast);
  transform: translateX(20px);
}

.settings-toggle input:focus-visible + span {
  outline: 2px solid var(--color-primary-secondary);
  outline-offset: 2px;
}

.settings-slider {
  width: min(280px, 44vw);
  color: var(--color-muted);
  font-size: 0.8rem;
  font-weight: 650;
}

.settings-slider__track {
  position: relative;
  display: block;
  height: 44px;
}

.settings-slider__track::before {
  content: '';
  position: absolute;
  top: 8px;
  left: 0;
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 8%);
}

.settings-slider__fill {
  position: absolute;
  top: 8px;
  left: 0;
  width: calc((5 - 2) / (9 - 2) * 100%);
  height: 6px;
  border-radius: 999px;
  background: var(--color-primary-secondary);
}

.settings-slider__thumb {
  position: absolute;
  top: 2px;
  left: calc((5 - 2) / (9 - 2) * 100%);
  width: 18px;
  height: 18px;
  border: 3px solid var(--color-primary-contrast);
  border-radius: 50%;
  background: var(--color-primary-secondary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.24);
  transform: translateX(-50%);
}

.settings-slider__min,
.settings-slider__max,
.settings-slider__value {
  position: absolute;
  top: 25px;
  line-height: 1;
}

.settings-slider__min {
  left: 0;
}

.settings-slider__max {
  right: 0;
}

.settings-slider__value {
  left: calc((5 - 2) / (9 - 2) * 100%);
  min-width: 22px;
  padding: 3px 6px;
  border-radius: 6px;
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 5%);
  color: var(--color-text);
  text-align: center;
  transform: translateX(-50%);
}

.settings-slider--disabled {
  cursor: not-allowed;
  opacity: 0.66;
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

.profile-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px 0;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 46%);
}

.profile-avatar {
  width: 64px;
  height: 64px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 2px solid var(--color-primary-secondary);
  border-radius: 50%;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 1.5rem;
  font-weight: 700;
}

.profile-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.profile-summary__text {
  min-width: 0;
}

.profile-summary__text h2 {
  margin: 0;
  font-size: 1.1rem;
  line-height: 1.25;
  color: var(--color-text);
}

.profile-summary__text p {
  margin: 5px 0 0;
  color: var(--color-muted);
  overflow-wrap: anywhere;
}

.settings-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 22px 0;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 46%);
}

.settings-field {
  min-width: 0;
  display: grid;
  gap: 7px;
}

.settings-field--wide {
  grid-column: 1 / -1;
}

.settings-field span {
  color: var(--color-muted);
  font-size: 0.9rem;
  line-height: 1.35;
}

.settings-field input {
  width: 100%;
  min-width: 0;
  height: 40px;
  padding: 8px 11px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 24%);
  border-radius: 10px;
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.settings-field input:focus {
  border-color: var(--color-primary-secondary);
  outline: none;
}

.profile-meta {
  display: grid;
  gap: 10px;
  padding: 18px 0;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 46%);
}

.profile-meta__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--color-muted);
  font-size: 0.92rem;
}

.profile-meta__row strong {
  color: var(--color-text);
}

.profile-meta__row .ok {
  color: var(--color-success);
}

.profile-meta__row .warn {
  color: var(--color-danger);
}

.profile-roles {
  display: inline-flex;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.profile-role {
  padding: 4px 8px;
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 7%);
  color: var(--color-text);
  font-size: 0.78rem;
  font-weight: 650;
}

.settings-feedback {
  min-height: 22px;
  padding-top: 14px;
  font-size: 0.9rem;
}

.settings-feedback .ok {
  color: var(--color-success);
}

.settings-feedback .err {
  color: var(--color-danger);
}

.settings-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 10px;
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
    flex-direction: row;
    overflow-x: auto;
    padding: 60px 14px 12px;
    border-right: 0;
    border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 34%);
  }

  .settings-nav__item {
    width: auto;
    flex: 0 0 auto;
  }

  .settings-content {
    padding: 22px 20px 28px;
  }

  .settings-row,
  .settings-form {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .settings-control,
  .settings-actions {
    justify-content: flex-start;
  }

  .settings-button--danger {
    margin-right: 0;
  }
}
</style>
