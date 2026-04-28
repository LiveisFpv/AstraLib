type AuthRedirectHandler = (redirect: string) => Promise<void> | void

let authRedirectHandler: AuthRedirectHandler | null = null

export function setAuthRedirectHandler(handler: AuthRedirectHandler) {
  authRedirectHandler = handler
}

export async function redirectToAuthAfterFailedRefresh() {
  if (typeof window === 'undefined') return

  const redirect = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (window.location.pathname === '/auth') return

  if (authRedirectHandler) {
    await authRedirectHandler(redirect)
    return
  }

  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  window.location.assign(`${base}/auth?redirect=${encodeURIComponent(redirect)}`)
}
