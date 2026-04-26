export const AUTH_PASSWORD_MIN_LENGTH = 8
export const AUTH_PASSWORD_MAX_LENGTH = 40
export const AUTH_TEXT_MAX_LENGTH = 128

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PASSWORD_UPPER_RE = /[A-Z]/
const PASSWORD_LOWER_RE = /[a-z]/
const PASSWORD_NUMBER_RE = /[0-9]/
const PASSWORD_SYMBOL_RE = /[!@#~$%^&*()+|_{}\[\]:;<>,.?/]/

export type AuthMode = 'login' | 'signup'

export interface AuthDraft {
  email: string
  password: string
  confirmPassword: string
  firstName: string
  lastName: string
}

export type AuthDraftField = keyof AuthDraft

export type AuthFieldErrorCode =
  | 'required'
  | 'email'
  | 'maxLength'
  | 'passwordLength'
  | 'passwordPolicy'
  | 'mismatch'

export interface AuthValidationResult {
  values: AuthDraft
  fieldErrors: Partial<Record<AuthDraftField, AuthFieldErrorCode>>
}

export function createAuthDraft(initial: Partial<AuthDraft> = {}): AuthDraft {
  return {
    email: initial.email ?? '',
    password: initial.password ?? '',
    confirmPassword: initial.confirmPassword ?? '',
    firstName: initial.firstName ?? '',
    lastName: initial.lastName ?? '',
  }
}

function isValidPassword(password: string) {
  return (
    PASSWORD_UPPER_RE.test(password) &&
    PASSWORD_LOWER_RE.test(password) &&
    PASSWORD_NUMBER_RE.test(password) &&
    PASSWORD_SYMBOL_RE.test(password)
  )
}

export function validateAuthDraft(mode: AuthMode, draft: AuthDraft): AuthValidationResult {
  const values: AuthDraft = {
    email: draft.email.trim(),
    password: draft.password,
    confirmPassword: draft.confirmPassword,
    firstName: draft.firstName.trim(),
    lastName: draft.lastName.trim(),
  }
  const fieldErrors: Partial<Record<AuthDraftField, AuthFieldErrorCode>> = {}

  if (!values.email) {
    fieldErrors.email = 'required'
  } else if (values.email.length > AUTH_TEXT_MAX_LENGTH) {
    fieldErrors.email = 'maxLength'
  } else if (!EMAIL_RE.test(values.email)) {
    fieldErrors.email = 'email'
  }

  if (!values.password) {
    fieldErrors.password = 'required'
  } else if (
    values.password.length < AUTH_PASSWORD_MIN_LENGTH ||
    values.password.length > AUTH_PASSWORD_MAX_LENGTH
  ) {
    fieldErrors.password = 'passwordLength'
  } else if (!isValidPassword(values.password)) {
    fieldErrors.password = 'passwordPolicy'
  }

  if (mode === 'signup') {
    if (!values.lastName) {
      fieldErrors.lastName = 'required'
    } else if (values.lastName.length > AUTH_TEXT_MAX_LENGTH) {
      fieldErrors.lastName = 'maxLength'
    }

    if (!values.firstName) {
      fieldErrors.firstName = 'required'
    } else if (values.firstName.length > AUTH_TEXT_MAX_LENGTH) {
      fieldErrors.firstName = 'maxLength'
    }

    if (!values.confirmPassword) {
      fieldErrors.confirmPassword = 'required'
    } else if (values.confirmPassword !== values.password) {
      fieldErrors.confirmPassword = 'mismatch'
    }
  }

  return { values, fieldErrors }
}
