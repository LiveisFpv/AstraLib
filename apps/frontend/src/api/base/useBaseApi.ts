import { useAuthStore } from '@/stores/authStore'
import axios, { AxiosError } from 'axios'
import { SSO_CLIENT_ID_URL } from '@/config'
import { redirectToAuthAfterFailedRefresh } from '@/api/base/authRedirect'

export const api = axios.create({
  baseURL: SSO_CLIENT_ID_URL,
  timeout: 10000,
  withCredentials: true,
})

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  const token = auth.AccessToken
  if (token) {
    config.headers = config.headers ?? {}
    ;(config.headers as any).Authorization = `Bearer ${token}`
  }
  return config
})

let refreshPromise: Promise<boolean> | null = null

function refreshAccessToken(auth: ReturnType<typeof useAuthStore>) {
  if (!refreshPromise) {
    refreshPromise = auth
      .refreshToken()
      .then(() => true)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const auth = useAuthStore()
    const original = error.config!
    const status = error.response?.status
    const reqUrl = (original?.url || '') as string
    const isRefreshCall = reqUrl.includes('/auth/refresh')
    const isLogoutCall = reqUrl.includes('/auth/logout')

    if (status === 401 && !(original as any)._retry && !isRefreshCall && !isLogoutCall) {
      const refreshOk = await refreshAccessToken(auth)
      if (!refreshOk) {
        auth.clearSession()
        await redirectToAuthAfterFailedRefresh()
        return Promise.reject(normalizeApiError(error))
      }
      ;(original as any)._retry = true
      return api(original)
    }
    return Promise.reject(normalizeApiError(error))
  },
)

export class ApiError extends Error {
  status?: number
  details?: unknown
  constructor(message: string, status?: number, details?: unknown) {
    super(message)
    this.status = status
    this.details = details
  }
}

function normalizeApiError(err: AxiosError) {
  const status = err.response?.status
  const payload = (err.response?.data as any) ?? {}
  const message = payload.error || payload.message || err.message || 'Request failed'
  const details = err.response?.data
  return new ApiError(message, status, details)
}
