<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
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

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

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

function switchMode() {
  formError.value = ''
  authMode.value = isLogin.value ? 'signup' : 'login'
  touched.confirmPassword = false
  touched.firstName = false
  touched.lastName = false
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
  <div class="auth-view">
    <div class="card auth-card">
      <div class="login-view">
        <h2 class="auth-title">{{ isLogin ? t('auth.login') : t('auth.signup') }}</h2>
        <form class="auth-form" @submit.prevent="onSubmit">
          <div class="auth-field">
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
          <button
            class="btn btn-text"
            type="button"
            :disabled="isResetSubmitting"
            @click="openResetDialog"
          >
            {{ t('auth.forgot') }}
          </button>
        </form>
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
        <h3 class="reset-title">{{ t('auth.resetTitle') }}</h3>
        <p class="reset-description">{{ t('auth.resetDescription') }}</p>
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
              class="btn"
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
.auth-view {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-8) var(--space-4);
}

.auth-card {
  width: 100%;
  max-width: 440px;
  padding: var(--space-6);
  display: grid;
  gap: var(--space-6);
}

.login-view,
.signup-view {
  display: grid;
  gap: var(--space-6);
}

.auth-title {
  text-align: center;
  margin: 0;
}

.auth-form {
  display: grid;
  gap: var(--space-3);
}

.auth-field {
  display: grid;
  gap: var(--space-2);
}

.input--invalid {
  border-color: var(--color-danger, #ef4444);
}

.field-feedback,
.form-feedback,
.reset-feedback {
  font-size: 0.875rem;
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

.reset-feedback--success {
  color: var(--color-success, #10b981);
}

.btn-text {
  background: transparent;
  border: 1px solid transparent;
  color: var(--color-primary);
  padding: 0;
}

.btn-text:hover {
  text-decoration: underline;
  background: transparent;
}

.oauth {
  display: grid;
  gap: var(--space-3);
}

.oauth-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  justify-content: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  line-height: 1.2;
}

.oauth-btn:hover {
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 3%);
  border-color: var(--color-border);
}

.oauth-logo {
  filter: none !important;
  width: 1.2em;
  height: 1.2em;
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
}

.btn-text {
  line-height: 1.2;
  display: inline-flex;
  align-items: baseline;
}

.reset-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.65);
  display: grid;
  place-items: center;
  padding: var(--space-4);
  z-index: 1000;
}

.reset-modal {
  background: var(--color-surface);
  color: var(--color-text);
  border-radius: var(--radius-md);
  padding: var(--space-6);
  box-shadow: var(--shadow-md);
  width: min(420px, 100%);
  display: grid;
  gap: var(--space-3);
}

.reset-title {
  margin: 0;
}

.reset-description {
  margin: 0;
  color: var(--color-muted);
}

.reset-form {
  display: grid;
  gap: var(--space-3);
}

.reset-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.reset-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
