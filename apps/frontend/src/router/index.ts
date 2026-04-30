import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { setAuthRedirectHandler } from '@/api/base/authRedirect'

const Homeview = () => import('@/views/HomeView.vue')
const AuthView = () => import('@/views/AuthView.vue')
const SearchView = () => import('@/views/SearchView.vue')
const PaperView = () => import('@/views/PaperView.vue')
const MyPapersView = () => import('@/views/MyPapersView.vue')
const NotFoundView = () => import('@/views/NotFoundView.vue')
const AdminDashboardView = () => import('@/views/AdminDashboardView.vue')
const ModeratorDashboardView = () => import('@/views/ModeratorDashboardView.vue')

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', component: Homeview, meta: { requiresAuth: true } },
    { path: '/auth', component: AuthView, meta: { public: true } },
    { path: '/search/:uid', component: SearchView, meta: { requiresAuth: true } },
    {
      path: '/paper/my',
      name: 'my-papers',
      component: MyPapersView,
      meta: { requiresAuth: true, roles: ['AUTHOR', 'MODERATOR', 'ADMIN'] },
    },
    {
      path: '/paper/add',
      redirect: { name: 'my-papers' },
      meta: { requiresAuth: true, roles: ['AUTHOR', 'MODERATOR', 'ADMIN'] },
    },
    {
      path: '/paper/:id/edit',
      redirect: { name: 'my-papers' },
      meta: { requiresAuth: true, roles: ['AUTHOR', 'MODERATOR', 'ADMIN'] },
    },
    { path: '/paper/:uid', component: PaperView },
    {
      path: '/admin',
      component: AdminDashboardView,
      meta: { requiresAuth: true, roles: ['ADMIN'] },
    },
    {
      path: '/moderator',
      component: ModeratorDashboardView,
      meta: { requiresAuth: true, roles: ['MODERATOR', 'ADMIN'] },
    },
    { path: '/:pathMatch(.*)*', component: NotFoundView },
  ],
})

setAuthRedirectHandler(async (redirect) => {
  await router.replace({ path: '/auth', query: { redirect } })
})

// Global auth guard + redirect support
function normalizeRole(r?: string): string | null {
  if (!r || typeof r !== 'string') return null
  return r.trim().toUpperCase()
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const isPublicRoute = to.meta?.public === true

  if (!auth.isAuthenticated) {
    await auth.restoreSession()
  }

  // block private routes
  if (!isPublicRoute && !auth.isAuthenticated) {
    return { path: '/auth', query: { redirect: to.fullPath }, replace: true }
  }
  // prevent opening /auth when already logged in
  if (to.path === '/auth' && auth.isAuthenticated) {
    const target = (to.query?.redirect as string) || '/'
    return { path: target, replace: true }
  }
  // Ensure roles loaded if needed
  const required = ((to.meta as any)?.roles as string[] | undefined) ?? []
  let userRoles = (auth.User?.roles ?? []).map((r) => normalizeRole(r)).filter(Boolean) as string[]
  if (required.length && auth.isAuthenticated && (!userRoles || userRoles.length === 0)) {
    try {
      await auth.authenticate()
      userRoles = (auth.User?.roles ?? []).map((r) => normalizeRole(r)).filter(Boolean) as string[]
    } catch {}
  }

  const isAdmin: boolean = userRoles.includes('ADMIN')
  const isModerator: boolean = userRoles.includes('MODERATOR')
  // Enforce role-based access if route defines roles
  const requiredRoles = required
  if (requiredRoles && requiredRoles.length) {
    const requiredNormalized = requiredRoles
      .map((r) => normalizeRole(r))
      .filter(Boolean) as string[]
    const ok = requiredNormalized.some((r) => userRoles.includes(r))
    if (!ok) {
      if (isAdmin) return { path: '/admin', replace: true }
      if (isModerator) return { path: '/moderator', replace: true }
      return { path: '/', replace: true }
    }
  }
})

export default router
