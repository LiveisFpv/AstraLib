<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useI18n } from '@/i18n'
import {
  AUTH_PASSWORD_MAX_LENGTH,
  AUTH_PASSWORD_MIN_LENGTH,
  AUTH_TEXT_MAX_LENGTH,
  createAuthDraft,
  validateAuthDraft,
  type AuthDraft,
  type AuthDraftField,
  type AuthMode,
} from '@/utils/auth'
// Settings
type Theme = 'light' | 'dark'
const THEME_KEY = 'theme'

const { locale, setLocale, t } = useI18n()

const theme = ref<Theme>('dark')

function readSavedTheme(): Theme | null {
  try {
    const t = localStorage.getItem(THEME_KEY)
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}
function applyTheme(t: Theme) {
  try {
    if (typeof (window as any).__setTheme === 'function') {
      ;(window as any).__setTheme(t)
    } else {
      document.documentElement.dataset.theme = t
      localStorage.setItem(THEME_KEY, t)
    }
  } catch {
    document.documentElement.dataset.theme = t
  }
}
function setTheme(t: Theme) {
  theme.value = t
  applyTheme(t)
}

onMounted(() => {
  const current: Theme =
    (document.documentElement.dataset.theme as Theme) || readSavedTheme() || 'dark'
  theme.value = current
})

const currentLang = computed(() => locale.value)
function chooseLang(l: 'en' | 'ru') {
  setLocale(l)
}

function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

function toggleLang() {
  chooseLang(locale.value === 'en' ? 'ru' : 'en')
}

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()

if (authStore.isAuthenticated) {
  router.replace('/')
}

const authMode = ref<AuthMode>('login')
const isLogin = computed(() => authMode.value === 'login')
const draft = reactive<AuthDraft>(createAuthDraft())
const touched = reactive<Record<AuthDraftField, boolean>>({
  email: false,
  password: false,
  confirmPassword: false,
  firstName: false,
  lastName: false,
})
const validationResult = computed(() => validateAuthDraft(authMode.value, draft))
const formError = ref('')
const isSubmitting = ref(false)
const isResetSubmitting = ref(false)
const isResetOpen = ref(false)
const resetEmail = ref('')
const resetMessage = ref('')
const resetError = ref('')

function isVisibleField(field: AuthDraftField) {
  return isLogin.value ? field === 'email' || field === 'password' : true
}

function getFieldError(field: AuthDraftField) {
  const code = validationResult.value.fieldErrors[field]
  if (!code) return ''

  switch (field) {
    case 'email':
      if (code === 'required') return t('auth.validation.emailRequired')
      if (code === 'maxLength') return t('auth.validation.emailMaxLength')
      return t('auth.validation.emailInvalid')
    case 'password':
      if (code === 'required') return t('auth.validation.passwordRequired')
      if (code === 'passwordLength') return t('auth.validation.passwordLength')
      return t('auth.validation.passwordPolicy')
    case 'confirmPassword':
      return code === 'required'
        ? t('auth.validation.confirmPasswordRequired')
        : t('auth.validation.confirmPasswordMismatch')
    case 'firstName':
      return code === 'required'
        ? t('auth.validation.firstNameRequired')
        : t('auth.validation.firstNameMaxLength')
    case 'lastName':
      return code === 'required'
        ? t('auth.validation.lastNameRequired')
        : t('auth.validation.lastNameMaxLength')
  }
}

function hasFieldError(field: AuthDraftField) {
  return touched[field] && isVisibleField(field) && !!validationResult.value.fieldErrors[field]
}

function markFieldTouched(field: AuthDraftField) {
  touched[field] = true
}

function markVisibleFieldsTouched() {
  markFieldTouched('email')
  markFieldTouched('password')
  if (!isLogin.value) {
    markFieldTouched('firstName')
    markFieldTouched('lastName')
    markFieldTouched('confirmPassword')
  }
}

function clearFormError() {
  formError.value = ''
}

function setAuthMode(mode: AuthMode) {
  if (authMode.value === mode) return
  formError.value = ''
  authMode.value = mode
  touched.confirmPassword = false
  touched.firstName = false
  touched.lastName = false
}

function switchMode() {
  setAuthMode(isLogin.value ? 'signup' : 'login')
}

const openResetDialog = async (e: Event) => {
  e.preventDefault()
  resetMessage.value = ''
  resetError.value = ''
  resetEmail.value = draft.email.trim()
  isResetOpen.value = true
  await nextTick()
  ;(document.getElementById('reset-email') as HTMLInputElement | null)?.focus()
}

const closeResetDialog = () => {
  if (isResetSubmitting.value) return
  isResetOpen.value = false
  resetMessage.value = ''
  resetError.value = ''
}

const onSubmit = async (e: Event) => {
  e.preventDefault()
  if (isSubmitting.value) return

  clearFormError()
  markVisibleFieldsTouched()

  if (Object.keys(validationResult.value.fieldErrors).length > 0) {
    formError.value = t('auth.validation.fixErrors')
    return
  }

  try {
    isSubmitting.value = true
    const { values } = validationResult.value

    if (isLogin.value) {
      await authStore.login(values.email, values.password)
      if (authStore.isAuthenticated) {
        const target = (route.query.redirect as string) || '/'
        router.replace(target)
      }
      return
    }

    await authStore.signup(values.email, values.password, values.firstName, values.lastName)
    const target = (route.query.redirect as string) || '/'
    router.replace(target)
  } catch (error) {
    const fallback = isLogin.value ? t('auth.loginFailed') : t('auth.signupFailed')
    if (error && typeof error === 'object' && 'message' in error) {
      formError.value = String((error as { message?: string }).message || fallback)
    } else {
      formError.value = fallback
    }
  } finally {
    isSubmitting.value = false
  }
}

const onForgotPassword = async (e?: Event) => {
  e?.preventDefault()
  resetMessage.value = ''
  resetError.value = ''
  const email = resetEmail.value.trim()
  if (!email) {
    resetError.value = t('auth.resetEmailRequired')
    return
  }
  isResetSubmitting.value = true
  try {
    await authStore.requestPasswordReset(email)
    resetMessage.value = t('auth.resetSuccess')
  } catch (error) {
    const fallback = t('auth.resetFailed')
    if (error && typeof error === 'object' && 'message' in error) {
      const errMessage = (error as { message?: string }).message
      resetError.value = errMessage || fallback
    } else {
      resetError.value = fallback
    }
  } finally {
    isResetSubmitting.value = false
  }
}
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
  <div class="auth-view">
    <div class="card auth-card">
      <span class="book-spine" aria-hidden="true"></span>
      <span class="book-ribbon" aria-hidden="true"></span>
      <header class="auth-header">
        <div class="brand-lockup">
          <img class="brand-logo" src="/src/assets/logo.svg" alt="" />
          <!-- <h1 class="auth-title">{{ isLogin ? t('auth.login') : t('auth.signup') }}</h1> -->
        </div>
      </header>

      <div class="auth-body">
        <form class="auth-form" @submit.prevent="onSubmit">
          <div class="auth-field">
            <label class="field-label" for="email">{{ t('auth.email') }}</label>
            <input
              v-model.trim="draft.email"
              type="email"
              :placeholder="t('auth.email')"
              class="input"
              :class="{ 'input--invalid': hasFieldError('email') }"
              autocomplete="email"
              id="email"
              :maxlength="AUTH_TEXT_MAX_LENGTH"
              @input="clearFormError"
              @blur="markFieldTouched('email')"
            />
            <p v-if="hasFieldError('email')" class="field-feedback field-feedback--error">
              {{ getFieldError('email') }}
            </p>
          </div>
          <div v-if="!isLogin" class="auth-field">
            <label class="field-label" for="lastname">{{ t('auth.lastname') }}</label>
            <input
              v-model.trim="draft.lastName"
              type="text"
              :placeholder="t('auth.lastname')"
              class="input"
              :class="{ 'input--invalid': hasFieldError('lastName') }"
              autocomplete="family-name"
              id="lastname"
              :maxlength="AUTH_TEXT_MAX_LENGTH"
              @input="clearFormError"
              @blur="markFieldTouched('lastName')"
            />
            <p v-if="hasFieldError('lastName')" class="field-feedback field-feedback--error">
              {{ getFieldError('lastName') }}
            </p>
          </div>
          <div v-if="!isLogin" class="auth-field">
            <label class="field-label" for="firstname">{{ t('auth.firstname') }}</label>
            <input
              v-model.trim="draft.firstName"
              type="text"
              :placeholder="t('auth.firstname')"
              class="input"
              :class="{ 'input--invalid': hasFieldError('firstName') }"
              autocomplete="given-name"
              id="firstname"
              :maxlength="AUTH_TEXT_MAX_LENGTH"
              @input="clearFormError"
              @blur="markFieldTouched('firstName')"
            />
            <p v-if="hasFieldError('firstName')" class="field-feedback field-feedback--error">
              {{ getFieldError('firstName') }}
            </p>
          </div>
          <div class="auth-field">
            <label class="field-label" for="password">{{ t('auth.password') }}</label>
            <input
              v-model="draft.password"
              type="password"
              :placeholder="t('auth.password')"
              class="input"
              :class="{ 'input--invalid': hasFieldError('password') }"
              :autocomplete="isLogin ? 'current-password' : 'new-password'"
              id="password"
              :minlength="AUTH_PASSWORD_MIN_LENGTH"
              :maxlength="AUTH_PASSWORD_MAX_LENGTH"
              @input="clearFormError"
              @blur="markFieldTouched('password')"
            />
            <p v-if="hasFieldError('password')" class="field-feedback field-feedback--error">
              {{ getFieldError('password') }}
            </p>
            <p v-else-if="!isLogin" class="field-feedback field-feedback--hint">
              {{ t('auth.passwordHint') }}
            </p>
          </div>
          <div v-if="!isLogin" class="auth-field">
            <label class="field-label" for="confirmpassword">{{ t('auth.confirmPassword') }}</label>
            <input
              v-model="draft.confirmPassword"
              type="password"
              :placeholder="t('auth.confirmPassword')"
              class="input"
              :class="{ 'input--invalid': hasFieldError('confirmPassword') }"
              autocomplete="new-password"
              id="confirmpassword"
              :minlength="AUTH_PASSWORD_MIN_LENGTH"
              :maxlength="AUTH_PASSWORD_MAX_LENGTH"
              @input="clearFormError"
              @blur="markFieldTouched('confirmPassword')"
            />
            <p v-if="hasFieldError('confirmPassword')" class="field-feedback field-feedback--error">
              {{ getFieldError('confirmPassword') }}
            </p>
          </div>
          <p v-if="formError" class="form-feedback form-feedback--error">
            {{ formError }}
          </p>
          <button class="btn btn--primary" type="submit" :disabled="isSubmitting">
            {{ isSubmitting ? t('common.loading') : isLogin ? t('auth.login') : t('auth.signup') }}
          </button>
          <div class="form-footer">
            <button
              class="btn btn-text"
              type="button"
              :disabled="isResetSubmitting"
              @click="openResetDialog"
            >
              {{ t('auth.forgot') }}
            </button>
          </div>
        </form>

        <div class="auth-divider" aria-hidden="true"></div>

        <div class="oauth">
          <button class="btn oauth-btn" @click="authStore.oauth('google', '/')">
            <img src="/src/assets/google-icon.svg" alt="Google" class="logo oauth-logo" />
            <span>{{ t('auth.continueGoogle') }}</span>
          </button>
          <button class="btn oauth-btn" @click="authStore.oauth('yandex', '/')">
            <img src="/src/assets/yandex-icon.svg" alt="Yandex" class="logo oauth-logo" />
            <span>{{ t('auth.continueYandex') }}</span>
          </button>
        </div>
        <div class="switch">
          <span class="muted">{{ isLogin ? t('auth.noAccount') : t('auth.haveAccount') }}</span>
          <button class="btn btn-text" type="button" @click="switchMode">
            {{ isLogin ? t('auth.createOne') : t('auth.signIn') }}
          </button>
        </div>
      </div>
    </div>
    <div v-if="isResetOpen" class="reset-modal-overlay" @click.self="closeResetDialog">
      <div class="reset-modal" role="dialog" aria-modal="true">
        <!-- <span class="reset-ribbon" aria-hidden="true"></span> -->
        <header class="reset-header">
          <div>
            <h2 class="reset-title">{{ t('auth.resetTitle') }}</h2>
            <p class="reset-description">{{ t('auth.resetDescription') }}</p>
          </div>
          <button
            class="btn reset-close"
            type="button"
            :aria-label="t('auth.resetClose')"
            :disabled="isResetSubmitting"
            @click="closeResetDialog"
          >
            x
          </button>
        </header>
        <form class="reset-form" @submit.prevent="onForgotPassword()">
          <label class="reset-label" for="reset-email">{{ t('auth.email') }}</label>
          <input
            id="reset-email"
            v-model="resetEmail"
            type="email"
            class="input"
            :placeholder="t('auth.email')"
            autocomplete="email"
            required
          />
          <p v-if="resetMessage" class="reset-feedback reset-feedback--success">
            {{ resetMessage }}
          </p>
          <p v-if="resetError" class="reset-feedback reset-feedback--error">
            {{ resetError }}
          </p>
          <div class="reset-actions">
            <button
              class="btn reset-secondary"
              type="button"
              :disabled="isResetSubmitting"
              @click="closeResetDialog"
            >
              {{ resetMessage ? t('auth.resetClose') : t('auth.resetCancel') }}
            </button>
            <button class="btn btn--primary" type="submit" :disabled="isResetSubmitting">
              {{ isResetSubmitting ? t('common.loading') : t('auth.resetSubmit') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style lang="css" scoped>
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

.auth-view {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background:
    linear-gradient(
      135deg,
      color-mix(in oklab, var(--color-bg), var(--color-accent) 5%),
      var(--color-bg) 48%
    ),
    var(--color-bg);
}

.auth-card {
  position: relative;
  width: 100%;
  max-width: 456px;
  padding: 22px 24px 24px 58px;
  display: grid;
  gap: var(--space-4);
  border-radius: 8px;
  isolation: isolate;
  box-shadow:
    0 18px 48px rgba(2, 6, 23, 0.12),
    inset -5px 0 0 color-mix(in oklab, var(--color-border), transparent 35%);
}

.auth-card::before {
  top: 10px;
  right: -7px;
  bottom: 13px;
  width: 12px;
  border: 1px solid color-mix(in oklab, var(--color-border), transparent 14%);
  border-left: 0;
  border-radius: 0 8px 8px 0;
  background: linear-gradient(
    90deg,
    color-mix(in oklab, var(--color-surface), black 3%),
    color-mix(in oklab, var(--color-surface), var(--color-bg-secondary) 22%)
  );
  z-index: -1;
}

.auth-card::after {
  left: 48px;
  right: 15px;
  bottom: -8px;
  height: 12px;
  border: 1px solid color-mix(in oklab, var(--color-border), transparent 16%);
  border-top: 0;
  border-radius: 0 0 8px 8px;
  background: repeating-linear-gradient(
    0deg,
    color-mix(in oklab, var(--color-surface), var(--color-bg-secondary) 18%) 0 2px,
    color-mix(in oklab, var(--color-border), transparent 46%) 2px 3px
  );
  z-index: -1;
}

.auth-card > * {
  position: relative;
  z-index: 1;
}

.book-spine {
  position: absolute;
  inset: 0 auto 0 0;
  width: 40px;
  border-radius: 8px 0 0 8px;
  background:
    linear-gradient(90deg, rgba(255, 255, 255, 0.16), transparent 28%),
    linear-gradient(
      180deg,
      color-mix(in oklab, var(--color-primary), var(--color-surface) 12%),
      color-mix(in oklab, var(--color-accent), var(--color-primary) 34%)
    );
  box-shadow:
    inset -8px 0 12px rgba(2, 6, 23, 0.16),
    inset 1px 0 0 rgba(255, 255, 255, 0.22);
  z-index: 1;
}

.book-ribbon {
  position: absolute;
  top: -10px;
  left: 12px;
  width: 20px;
  height: 118px;
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 82%, 0 100%);
  background: linear-gradient(180deg, var(--color-accent), var(--color-primary));
  box-shadow: 0 10px 20px color-mix(in oklab, var(--color-primary), transparent 74%);
  z-index: 3;
}

.auth-header {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-2);
  padding-bottom: var(--space-1);
}

.brand-lockup {
  display: inline-flex;
  justify-self: center;
  align-items: center;
  gap: var(--space-3);
  font-weight: 800;
  color: var(--color-text);
}

.brand-logo {
  width: auto;
  height: 80px;
  filter: none;
}

.auth-title {
  margin: 0;
  font-size: 1.18rem;
  letter-spacing: 0;
}

.mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  margin: -4px auto 0;
  width: min(100%, 360px);
}

.mode-switch__button {
  position: relative;
  min-height: 32px;
  padding: 0 var(--space-2) 8px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in oklab, var(--color-muted), var(--color-text) 16%);
  cursor: pointer;
  font: inherit;
  font-size: 0.95rem;
  font-weight: 600;
  line-height: 1.15;
  transition:
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.mode-switch__button::after {
  content: '';
  position: absolute;
  right: 34%;
  bottom: 0;
  left: 34%;
  height: 2px;
  border-radius: 999px;
  background: transparent;
  opacity: 0;
  transform: scaleX(0.72);
  transition:
    opacity var(--transition-fast),
    transform var(--transition-fast);
}

.mode-switch__button:hover {
  color: var(--color-text);
}

.mode-switch__button:focus-visible {
  outline: 2px solid color-mix(in oklab, var(--color-primary), transparent 18%);
  outline-offset: 2px;
  border-radius: 6px;
}

.mode-switch__button.active {
  color: color-mix(in oklab, var(--color-text), var(--color-primary) 10%);
}

.mode-switch__button.active::after {
  background: linear-gradient(90deg, var(--color-primary), var(--color-accent));
  opacity: 1;
  transform: scaleX(1);
}

.auth-body {
  display: grid;
  gap: var(--space-3);
}

.auth-form {
  display: grid;
  gap: 10px;
}

.auth-field {
  display: grid;
  gap: 5px;
}

.field-label,
.reset-label {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.2;
}

.input {
  min-height: 39px;
  padding-block: 0.45rem;
  border-radius: 8px;
  border-color: var(--color-border);
  background: color-mix(in oklab, var(--color-surface), var(--color-bg-secondary) 10%);
}

.input:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--color-focus), transparent 62%);
}

.input--invalid {
  border-color: var(--color-danger, #ef4444);
}

.field-feedback,
.form-feedback,
.reset-feedback {
  font-size: 0.8rem;
  line-height: 1.3;
  margin: 0;
}

.field-feedback--error,
.form-feedback--error,
.reset-feedback--error {
  color: var(--color-danger, #ef4444);
}

.field-feedback--hint {
  color: var(--color-muted);
}

.form-feedback {
  padding: var(--space-2) var(--space-3);
  border-radius: 8px;
  border: 1px solid color-mix(in oklab, var(--color-danger), transparent 62%);
  background: color-mix(in oklab, var(--color-danger), transparent 88%);
}

.reset-feedback--success {
  color: var(--color-success, #10b981);
}

.btn {
  padding-block: 0.6rem;
  border-radius: 8px;
  font-weight: 700;
}

.btn--primary {
  background: linear-gradient(
    135deg,
    var(--color-primary),
    color-mix(in oklab, var(--color-primary), var(--color-accent) 22%)
  );
  box-shadow: 0 10px 22px color-mix(in oklab, var(--color-primary), transparent 78%);
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
}

.btn-text {
  background: transparent;
  border: 1px solid transparent;
  color: var(--color-primary);
  padding: 0;
  height: 20px;
}

.btn-text:hover {
  text-decoration: underline;
  background: transparent;
}

.auth-divider {
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    color-mix(in oklab, var(--color-border), var(--color-accent) 8%),
    transparent
  );
}

.oauth {
  display: grid;
  gap: var(--space-2);
}

.oauth-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  justify-content: center;
  background: color-mix(in oklab, var(--color-surface), var(--color-bg-secondary) 12%);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  line-height: 1.2;
}

.oauth-btn:hover {
  background: var(--color-surface);
  border-color: color-mix(in oklab, var(--color-border), var(--color-primary) 18%);
}

.oauth-logo {
  filter: none !important;
  width: 1.05em;
  height: 1.05em;
  flex-shrink: 0;
}

.oauth-btn span {
  line-height: 1.2;
  white-space: nowrap;
}

.switch {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  justify-content: center;
  flex-wrap: wrap;
  font-size: 0.88rem;
}

.btn-text {
  line-height: 1.2;
  display: inline-flex;
  align-items: baseline;
}

.reset-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.68);
  display: grid;
  place-items: center;
  padding: var(--space-4);
  z-index: 1000;
  backdrop-filter: blur(6px);
}

.reset-modal {
  position: relative;
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: var(--space-6);
  box-shadow: 0 20px 56px rgba(2, 6, 23, 0.22);
  width: min(420px, 100%);
  display: grid;
  gap: var(--space-3);
  overflow: hidden;
}

.reset-ribbon {
  position: absolute;
  top: -6px;
  left: 22px;
  width: 18px;
  height: 78px;
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 82%, 0 100%);
  background: linear-gradient(180deg, var(--color-accent), var(--color-primary));
  box-shadow: 0 8px 18px color-mix(in oklab, var(--color-primary), transparent 78%);
}

.reset-modal > * {
  position: relative;
  z-index: 1;
}

.reset-header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-3);
  align-items: start;
}

.reset-title {
  margin: 0;
  font-size: 1.1rem;
}

.reset-description {
  margin: var(--space-1) 0 0;
  color: var(--color-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}

.reset-form {
  display: grid;
  gap: var(--space-3);
}

.reset-close {
  min-width: 34px;
  width: 34px;
  min-height: 34px;
  height: 34px;
  padding: 0;
  color: var(--color-muted);
}

.reset-secondary {
  background: transparent;
}

.reset-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  flex-wrap: wrap;
}

@media (max-height: 760px) and (min-width: 640px) {
  .auth-view {
    align-items: start;
    padding-block: var(--space-3);
  }

  .auth-card {
    padding: var(--space-4) var(--space-4) var(--space-4) 48px;
    gap: var(--space-3);
  }

  .book-spine {
    width: 32px;
  }

  .book-ribbon {
    left: 9px;
    width: 16px;
    height: 94px;
  }

  .auth-body,
  .auth-form {
    gap: var(--space-2);
  }
}

@media (max-width: 520px) {
  .auth-view {
    padding: var(--space-3);
    place-items: stretch;
  }

  .auth-card {
    max-width: none;
    padding: var(--space-4) var(--space-4) var(--space-4) 44px;
  }

  .auth-card::before {
    right: -5px;
    width: 9px;
  }

  .auth-card::after {
    left: 38px;
    right: 12px;
  }

  .book-spine {
    width: 28px;
  }

  .book-ribbon {
    left: 8px;
    width: 14px;
    height: 88px;
  }

  .mode-switch__button {
    min-height: 31px;
    padding-inline: 2px;
    font-size: 0.88rem;
  }

  .mode-switch__button::after {
    right: 30%;
    left: 30%;
  }

  .reset-actions {
    flex-direction: column-reverse;
  }

  .reset-actions .btn {
    width: 100%;
  }
}

@media (max-width: 520px) {
  .setting-panel {
    right: 12px;
    bottom: 12px;
  }
}
</style>
