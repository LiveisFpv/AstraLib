<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import UpTab from '@/components/UpTab.vue'
import LeftTab from '@/components/LeftTab.vue'
import { SSOApi } from '@/api/useSSOApi'
import type { UserListResponse, UserResponse, UserUpdateRequestWithRoles } from '@/api/types'
import { useI18n } from '@/i18n'
import { useLayoutInset } from '@/composables/useLayoutInset'

type UserEditing = UserResponse & {
  rolesString?: string
  _password?: string
  _saving?: boolean
  _error?: string
}

const router = useRouter()
const { t } = useI18n()
const { LeftTabHidden: leftHidden } = useLayoutInset()

const loading = ref(false)
const errorMsg = ref('')
const users = reactive<UserEditing[]>([])
const total = ref(0)
const page = ref(1)
const limit = ref(20)
const editModalOpen = ref(false)
const editingUserId = ref<number | null>(null)

const filters = reactive({
  q: '',
  role: '',
  locale: '',
  email_confirmed: '' as '' | 'true' | 'false',
})

const params = computed(() => ({
  q: filters.q || undefined,
  role: filters.role || undefined,
  locale: filters.locale || undefined,
  email_confirmed:
    filters.email_confirmed === '' ? undefined : filters.email_confirmed === 'true' ? true : false,
  page: page.value,
  limit: limit.value,
}))

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))
const activeUser = computed(() =>
  editingUserId.value == null ? null : users.find((user) => user.id === editingUserId.value) || null,
)
const summary = computed(() => {
  const confirmed = users.filter((user) => user.email_confirmed).length
  const admins = users.filter((user) => hasRole(user, 'ADMIN')).length
  const moderators = users.filter((user) => hasRole(user, 'MODERATOR')).length
  return { confirmed, admins, moderators, total: total.value }
})
const hasActiveFilters = computed(
  () => !!filters.q || !!filters.role || !!filters.locale || filters.email_confirmed !== '',
)

onMounted(() => {
  void loadUsers()
})

async function loadUsers() {
  errorMsg.value = ''
  loading.value = true
  try {
    const res = (await SSOApi.getUsers(params.value)) as UserListResponse
    users.splice(0, users.length, ...((res?.items ?? []) as UserEditing[]))
    total.value = res?.total ?? 0
    page.value = res?.page ?? page.value
    limit.value = res?.limit ?? limit.value
  } catch (e: any) {
    errorMsg.value = e?.message || t('admin.errFetch')
  } finally {
    loading.value = false
  }
}

function hasRole(user: UserResponse, role: string) {
  return (user.roles ?? []).some((value) => value.toUpperCase() === role)
}

function getDisplayName(user: UserResponse) {
  const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
  return name || user.email
}

function getInitials(user: UserResponse) {
  const first = user.first_name?.trim()?.[0]
  const last = user.last_name?.trim()?.[0]
  return `${first || user.email?.[0] || 'U'}${last || ''}`.toUpperCase()
}

function goModerator() {
  void router.push('/moderator')
}

function openEdit(user: UserEditing) {
  user.rolesString = user.roles?.join(', ') || ''
  user._password = ''
  user._error = ''
  editingUserId.value = user.id ?? null
  editModalOpen.value = true
}

function closeEdit() {
  if (activeUser.value?._saving) return
  editModalOpen.value = false
  editingUserId.value = null
}

async function saveUser(user: UserEditing) {
  user._error = ''
  user._saving = true
  try {
    const roles =
      typeof user.rolesString === 'string'
        ? user.rolesString
            .split(',')
            .map((role) => role.trim())
            .filter(Boolean)
        : (user.roles ?? [])
    const payload: UserUpdateRequestWithRoles = { roles }
    if (user.first_name) payload.first_name = user.first_name
    if (user.last_name) payload.last_name = user.last_name
    if (user.locale_type) payload.locale_type = user.locale_type
    if (user._password) payload.password = user._password
    const userId = user.id
    if (typeof userId !== 'number') throw new Error('Missing user id')
    const updated = await SSOApi.updateUserwithRoles(userId, payload)
    Object.assign(user, {
      first_name: updated.first_name,
      last_name: updated.last_name,
      locale_type: updated.locale_type,
      photo: updated.photo,
      email_confirmed: updated.email_confirmed,
      roles: updated.roles,
      rolesString: updated.roles?.join(', ') || '',
      _password: '',
    })
    closeEdit()
  } catch (e: any) {
    user._error = e?.message || 'Failed to save user'
  } finally {
    user._saving = false
  }
}

function applyFilters() {
  page.value = 1
  void loadUsers()
}

function resetFilters() {
  filters.q = ''
  filters.role = ''
  filters.locale = ''
  filters.email_confirmed = ''
  page.value = 1
  void loadUsers()
}

function prevPage() {
  if (page.value <= 1) return
  page.value -= 1
  void loadUsers()
}

function nextPage() {
  if (page.value >= pageCount.value) return
  page.value += 1
  void loadUsers()
}

function changeLimit(val: number) {
  limit.value = val
  page.value = 1
  void loadUsers()
}
</script>

<template>
  <UpTab :show-menu="false" :show-upload="false" />
  <LeftTab />

  <main class="admin-area" :class="{ collapsed: leftHidden }">
    <div class="admin-shell">
      <header class="admin-hero">
        <div class="admin-heading">
          <p class="admin-heading__eyebrow">{{ t('admin.workspaceLabel') }}</p>
          <h1>{{ t('admin.title') }}</h1>
          <p>{{ t('admin.heroDescription') }}</p>
          <div class="hero-metrics" :aria-label="t('admin.summary.label')">
            <span>
              <strong>{{ summary.total }}</strong>
              {{ t('admin.users') }}
            </span>
            <span>
              <strong>{{ summary.confirmed }}</strong>
              {{ t('admin.summary.confirmed') }}
            </span>
            <span>
              <strong>{{ summary.admins }}</strong>
              ADMIN
            </span>
            <span>
              <strong>{{ summary.moderators }}</strong>
              MODERATOR
            </span>
          </div>
        </div>

        <div class="hero-actions">
          <button class="action-button" type="button" @click="goModerator">
            {{ t('admin.toModerator') }}
          </button>
          <button class="action-button action-button--primary" type="button" :disabled="loading" @click="loadUsers">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
              <path d="M3 21v-5h5" />
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
              <path d="M16 8h5V3" />
            </svg>
            {{ loading ? t('common.loading') : t('common.refresh') }}
          </button>
        </div>
      </header>

      <section class="filters-panel" :aria-label="t('admin.filters.apply')">
        <label class="search-box">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="11" cy="11" r="7" />
            <path d="m16.5 16.5 4 4" />
          </svg>
          <input v-model.trim="filters.q" type="search" :placeholder="t('admin.filters.search')" @keyup.enter="applyFilters" />
        </label>

        <input v-model.trim="filters.role" type="text" :placeholder="t('admin.filters.role')" @keyup.enter="applyFilters" />
        <input v-model.trim="filters.locale" type="text" :placeholder="t('admin.filters.locale')" @keyup.enter="applyFilters" />

        <select v-model="filters.email_confirmed">
          <option value="">{{ t('admin.filters.confirmedAny') }}</option>
          <option value="true">{{ t('common.yes') }}</option>
          <option value="false">{{ t('common.no') }}</option>
        </select>

        <select :value="limit" @change="changeLimit(parseInt(($event.target as HTMLSelectElement).value))">
          <option :value="10">10</option>
          <option :value="20">20</option>
          <option :value="50">50</option>
        </select>

        <button class="action-button action-button--primary" type="button" @click="applyFilters">
          {{ t('admin.filters.apply') }}
        </button>
        <button class="action-button" type="button" :disabled="!hasActiveFilters" @click="resetFilters">
          {{ t('admin.filters.reset') }}
        </button>
      </section>

      <div v-if="errorMsg" class="state-banner state-banner--error">
        <strong>{{ t('admin.errFetch') }}</strong>
        <span>{{ errorMsg }}</span>
      </div>

      <div v-if="loading && !users.length" class="state-panel">
        <span class="state-spinner" aria-hidden="true"></span>
        <div>
          <h2>{{ t('admin.loadingTitle') }}</h2>
          <p>{{ t('admin.loadingDesc') }}</p>
        </div>
      </div>

      <section v-else-if="users.length" class="users-table" :aria-label="t('admin.users')">
        <div class="table-head" aria-hidden="true">
          <span>{{ t('admin.columns.email') }}</span>
          <span>ID</span>
          <span>{{ t('admin.columns.locale') }}</span>
          <span>{{ t('admin.columns.confirmed') }}</span>
          <span>{{ t('admin.columns.roles') }}</span>
          <span></span>
        </div>

        <article v-for="user in users" :key="user.id ?? user.email" class="user-row">
          <div class="user-cell user-cell--identity">
            <span class="cell-label">{{ t('admin.columns.email') }}</span>
            <div class="user-avatar">
              <img v-if="user.photo" :src="user.photo" alt="" />
              <span v-else>{{ getInitials(user) }}</span>
            </div>
            <div class="user-title">
              <h2>{{ getDisplayName(user) }}</h2>
              <p>{{ user.email }}</p>
            </div>
          </div>

          <div class="user-cell">
            <span class="cell-label">ID</span>
            <span class="mono-value">{{ user.id ?? '--' }}</span>
          </div>

          <div class="user-cell">
            <span class="cell-label">{{ t('admin.columns.locale') }}</span>
            <span>{{ user.locale_type || '--' }}</span>
          </div>

          <div class="user-cell">
            <span class="cell-label">{{ t('admin.columns.confirmed') }}</span>
            <span class="status-pill" :class="user.email_confirmed ? 'success' : 'warning'">
              {{ user.email_confirmed ? t('admin.status.confirmed') : t('admin.status.unconfirmed') }}
            </span>
          </div>

          <div class="user-cell user-cell--roles">
            <span class="cell-label">{{ t('admin.columns.roles') }}</span>
            <div class="role-list">
              <span v-for="role in user.roles || []" :key="role" class="role-pill">{{ role }}</span>
              <span v-if="!user.roles?.length" class="role-pill role-pill--empty">--</span>
            </div>
          </div>

          <div class="user-cell user-cell--actions">
            <button class="action-button action-button--primary" type="button" @click="openEdit(user)">
              {{ t('common.edit') }}
            </button>
          </div>
        </article>
      </section>

      <div v-else class="state-panel">
        <div>
          <h2>{{ t('admin.noUsers') }}</h2>
          <p>{{ t('admin.noUsersHint') }}</p>
        </div>
      </div>

      <footer v-if="!loading && total > 0" class="pager">
        <button class="action-button" type="button" @click="prevPage" :disabled="page <= 1">
          {{ t('admin.pager.prev') }}
        </button>
        <span>
          {{
            t('admin.pager.pageOf')
              .replace('{page}', String(page))
              .replace('{pages}', String(pageCount))
          }}
          {{ t('admin.pager.total').replace('{total}', String(total)) }}
        </span>
        <button class="action-button" type="button" @click="nextPage" :disabled="page >= pageCount">
          {{ t('admin.pager.next') }}
        </button>
      </footer>
    </div>
  </main>

  <Teleport to="body">
    <div v-if="editModalOpen && activeUser" class="modal-backdrop" @click.self="closeEdit">
      <section class="edit-modal" role="dialog" aria-modal="true" :aria-label="t('common.edit')">
        <header class="modal-head">
          <div>
            <p class="modal-eyebrow">{{ t('admin.workspaceLabel') }}</p>
            <h2>{{ getDisplayName(activeUser) }}</h2>
            <p>{{ activeUser.email }}</p>
          </div>
          <button class="icon-button" type="button" :aria-label="t('common.cancel')" @click="closeEdit">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </header>

        <form class="edit-form" @submit.prevent="saveUser(activeUser)">
          <div class="form-grid">
            <label>
              <span>{{ t('admin.columns.first') }}</span>
              <input type="text" v-model="activeUser.first_name" />
            </label>
            <label>
              <span>{{ t('admin.columns.last') }}</span>
              <input type="text" v-model="activeUser.last_name" />
            </label>
          </div>

          <div class="form-grid">
            <label>
              <span>{{ t('admin.columns.locale') }}</span>
              <input type="text" v-model="activeUser.locale_type" />
            </label>
            <label>
              <span>{{ t('admin.columns.password') }}</span>
              <input type="password" v-model="activeUser._password" placeholder="******" />
            </label>
          </div>

          <label>
            <span>{{ t('admin.columns.roles') }}</span>
            <input type="text" v-model="activeUser.rolesString" placeholder="USER, MODERATOR, ADMIN" />
          </label>

          <p v-if="activeUser._error" class="form-error">{{ activeUser._error }}</p>

          <footer class="modal-actions">
            <button class="action-button" type="button" @click="closeEdit">
              {{ t('common.cancel') }}
            </button>
            <button class="action-button action-button--primary" type="submit" :disabled="activeUser._saving">
              {{ activeUser._saving ? t('common.loading') : t('common.save') }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.admin-area {
  position: fixed;
  top: 80px;
  right: 20px;
  bottom: 20px;
  left: 310px;
  box-sizing: border-box;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--space-4) var(--space-4) var(--space-5);
  transition: all var(--transition-slow) ease;
}

.admin-area.collapsed {
  left: 120px;
}

.admin-shell {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  gap: var(--space-3);
}

.admin-hero,
.filters-panel,
.users-table,
.state-panel,
.state-banner {
  border: 1px solid var(--color-border-soft);
  background:
    linear-gradient(
      180deg,
      color-mix(in oklab, var(--color-panel-elevated), var(--color-surface) 3%),
      color-mix(in oklab, var(--color-panel), var(--color-bg) 5%)
    );
  box-shadow: var(--shadow-card);
}

.admin-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  min-width: 0;
  padding: 16px;
  border-radius: 16px;
}

.admin-heading {
  min-width: 0;
}

.admin-heading__eyebrow,
.modal-eyebrow {
  margin: 0 0 8px;
  color: var(--color-primary-secondary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.admin-heading h1 {
  margin: 0;
  color: var(--color-text);
  font-size: clamp(1.35rem, 1.8vw, 1.75rem);
  line-height: 1.1;
}

.admin-heading p:not(.admin-heading__eyebrow) {
  max-width: 640px;
  margin: 8px 0 0;
  color: var(--color-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}

.hero-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.hero-metrics span,
.role-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 34%);
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 18%);
  color: var(--color-muted);
  font-size: 0.8rem;
  font-weight: 650;
}

.hero-metrics strong {
  color: var(--color-text);
  font-size: 0.9rem;
}

.hero-actions,
.user-cell--actions,
.modal-actions,
.pager {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.action-button {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 13px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 24%);
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 12%);
  color: var(--color-text);
  font: inherit;
  font-size: 0.88rem;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
}

.action-button svg,
.search-box svg {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.action-button:hover,
.action-button:focus-visible {
  border-color: var(--color-primary-secondary);
  color: var(--color-primary-secondary);
  outline: none;
}

.action-button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.action-button--primary {
  border-color: transparent;
  background: var(--color-primary-secondary);
  color: var(--color-primary-contrast);
}

.action-button--primary:hover,
.action-button--primary:focus-visible {
  color: var(--color-primary-contrast);
  filter: brightness(1.04);
}

.filters-panel {
  position: sticky;
  top: 0;
  z-index: 3;
  display: grid;
  grid-template-columns: minmax(220px, 1.3fr) repeat(4, minmax(120px, 0.7fr)) auto auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border-radius: 16px;
}

.search-box {
  min-width: 0;
  height: 42px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 13px;
  border: 1px solid var(--color-border-soft);
  border-radius: 12px;
  background: var(--color-panel-elevated);
  color: var(--color-muted);
}

.search-box input,
.filters-panel > input,
.filters-panel select,
.edit-form input {
  box-sizing: border-box;
  min-width: 0;
  width: 100%;
  height: 42px;
  border: 1px solid var(--color-border-soft);
  border-radius: 12px;
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  padding: 0 12px;
  outline: 0;
}

.search-box input {
  height: auto;
  padding: 0;
  border: 0;
  background: transparent;
}

.users-table {
  display: grid;
  gap: 0;
  overflow: hidden;
  border-radius: 16px;
}

.table-head,
.user-row {
  display: grid;
  grid-template-columns: minmax(230px, 1.7fr) 78px minmax(88px, 0.55fr) minmax(130px, 0.7fr) minmax(180px, 1.05fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
}

.table-head {
  border-bottom: 1px solid var(--color-border-soft);
  color: var(--color-muted);
  font-size: 0.76rem;
  font-weight: 800;
  text-transform: uppercase;
}

.user-row {
  min-width: 0;
  border-bottom: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 36%);
}

.user-row:last-child {
  border-bottom: 0;
}

.user-row:hover {
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 4%);
}

.user-cell {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text);
  font-size: 0.9rem;
}

.user-cell--identity {
  gap: 10px;
}

.user-cell--roles {
  align-items: flex-start;
}

.user-cell--actions {
  justify-content: flex-end;
}

.cell-label {
  display: none;
  color: var(--color-muted);
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
}

.user-avatar {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid var(--color-border-soft);
  border-radius: 50%;
  background: color-mix(in oklab, var(--color-primary-secondary), transparent 82%);
  color: var(--color-primary-secondary);
  font-size: 0.78rem;
  font-weight: 800;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.user-title {
  min-width: 0;
}

.user-title h2 {
  margin: 0;
  overflow: hidden;
  color: var(--color-text);
  font-size: 0.94rem;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-title p {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--color-muted);
  font-size: 0.8rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 800;
  line-height: 1.2;
  text-transform: uppercase;
}

.status-pill.success {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.status-pill.warning {
  background: color-mix(in oklab, var(--color-warning), transparent 82%);
  color: var(--color-warning);
}

.role-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.role-pill--empty {
  opacity: 0.7;
}

.mono-value {
  color: var(--color-muted);
  font-variant-numeric: tabular-nums;
}

.pager {
  color: var(--color-muted);
  font-size: 0.86rem;
}

.state-banner {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 16px;
}

.state-banner strong,
.state-panel h2 {
  color: var(--color-text);
}

.state-banner span,
.state-panel p {
  color: var(--color-muted);
}

.state-banner--error {
  border-color: color-mix(in oklab, var(--color-danger), transparent 58%);
  background: color-mix(in oklab, var(--color-danger), transparent 94%);
}

.state-panel {
  min-height: 260px;
  display: grid;
  place-items: center;
  gap: 14px;
  padding: var(--space-5);
  text-align: center;
  border-style: dashed;
  border-radius: 18px;
}

.state-panel h2 {
  margin: 0;
  font-size: 1.1rem;
}

.state-panel p {
  max-width: 460px;
  margin: 8px 0 0;
  line-height: 1.5;
}

.state-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid color-mix(in oklab, var(--color-primary-secondary), transparent 72%);
  border-top-color: var(--color-primary-secondary);
  border-radius: 50%;
  animation: admin-spin 0.8s linear infinite;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in oklab, var(--color-bg), transparent 18%);
  backdrop-filter: blur(10px);
}

.edit-modal {
  width: min(760px, 100%);
  max-height: min(760px, calc(100vh - 48px));
  display: grid;
  gap: var(--space-4);
  overflow-y: auto;
  padding: 20px;
  border: 1px solid var(--color-border-soft);
  border-radius: 18px;
  background:
    linear-gradient(
      180deg,
      color-mix(in oklab, var(--color-panel-elevated), var(--color-surface) 3%),
      color-mix(in oklab, var(--color-panel), var(--color-bg) 5%)
    );
  box-shadow: var(--shadow-modal, 0 24px 70px rgba(0, 0, 0, 0.42));
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.modal-head h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 1.25rem;
  line-height: 1.25;
}

.modal-head p:not(.modal-eyebrow) {
  margin: 8px 0 0;
  color: var(--color-muted);
}

.icon-button {
  width: 34px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid var(--color-border-soft);
  border-radius: 999px;
  background: var(--color-panel-elevated);
  color: var(--color-text);
  cursor: pointer;
}

.icon-button svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}

.edit-form {
  display: grid;
  gap: var(--space-3);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.edit-form label {
  display: grid;
  gap: 6px;
}

.edit-form label span {
  color: var(--color-muted);
  font-size: 0.9rem;
}

.form-error {
  margin: 0;
  color: var(--color-danger);
}

@keyframes admin-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1280px) {
  .admin-area {
    right: 16px;
    bottom: 16px;
    left: 270px;
  }

  .admin-area.collapsed {
    left: 120px;
  }
}

@media (max-width: 1120px) {
  .filters-panel {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .table-head,
  .user-row {
    grid-template-columns: minmax(220px, 1.5fr) 70px 86px 120px minmax(150px, 0.9fr) auto;
  }
}

@media (max-width: 960px) {
  .admin-area {
    right: 14px;
    bottom: 14px;
    left: 270px;
    padding: var(--space-3);
  }

  .admin-area.collapsed {
    left: 120px;
  }

  .admin-hero {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 900px) {
  .admin-area,
  .admin-area.collapsed {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 12px;
    padding: var(--space-3);
  }
}

@media (max-width: 768px) {
  .admin-area {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 12px;
    padding: 0;
  }

  .admin-hero {
    padding: 16px;
  }

  .filters-panel,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .table-head {
    display: none;
  }

  .user-row {
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 13px;
  }

  .user-cell {
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .user-cell--identity {
    justify-content: flex-start;
  }

  .user-cell--actions {
    justify-content: flex-start;
  }

  .cell-label {
    display: inline-flex;
    flex: 0 0 118px;
  }

  .user-cell--identity .cell-label {
    display: none;
  }

  .hero-actions,
  .pager,
  .modal-actions {
    justify-content: flex-start;
  }

  .modal-backdrop {
    padding: 12px;
  }

  .edit-modal {
    max-height: calc(100vh - 24px);
    padding: 16px;
  }
}

@media (max-width: 700px) {
  .admin-area,
  .admin-area.collapsed {
    left: 12px;
  }
}

@media (max-width: 520px) {
  .admin-area,
  .admin-area.collapsed {
    right: 8px;
    bottom: 8px;
    left: 8px;
  }

  .admin-shell {
    gap: 10px;
  }

  .admin-hero,
  .filters-panel,
  .users-table {
    border-radius: 14px;
  }

  .hero-actions,
  .user-cell--actions,
  .modal-actions,
  .pager {
    align-items: stretch;
    flex-direction: column;
  }

  .user-cell {
    display: grid;
    gap: 4px;
  }

  .cell-label {
    flex: none;
  }

  .action-button {
    width: 100%;
  }
}
</style>
