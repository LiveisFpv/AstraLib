<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import UpTab from '@/components/UpTab.vue'
import LeftTab from '@/components/LeftTab.vue'
import { locale, useI18n } from '@/i18n'
import { useLayoutInset } from '@/composables/useLayoutInset'
import { AlibApi } from '@/api/useAlibApi'
import type {
  ModerateSubmissionRequest,
  SubmissionRecord,
  SubmissionStatus,
  SubmissionUpsertRequest,
} from '@/api/types'

type LinkRef = { id: string }
type ModeratorFilter = 'all' | 'pending' | 'approved' | 'rejected'

type ModerationForm = {
  source_identifier: string
  title: string
  abstract: string
  year?: number
  best_oa_location: string
  related_works: LinkRef[]
  referenced_works: LinkRef[]
}

type ModerationItem = SubmissionRecord & {
  editing: boolean
  saving: boolean
  draftComment: string
  form: ModerationForm
}

const { t } = useI18n()
const router = useRouter()
const { LeftTabHidden: leftHidden } = useLayoutInset()

const items = reactive<ModerationItem[]>([])
const loaded = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const statusFilter = ref<ModeratorFilter>('pending')
const searchQuery = ref('')
const reviewModalOpen = ref(false)
const activeSubmissionId = ref<number | null>(null)

const filterOptions: Array<{ value: ModeratorFilter; labelKey: string }> = [
  { value: 'all', labelKey: 'papers.filter.allShort' },
  { value: 'pending', labelKey: 'papers.status.pending' },
  { value: 'approved', labelKey: 'papers.status.approved' },
  { value: 'rejected', labelKey: 'papers.status.rejected' },
]

const summary = computed(() => ({
  pending: items.filter((item) => item.status === 'pending').length,
  approved: items.filter((item) => item.status === 'approved').length,
  rejected: items.filter((item) => item.status === 'rejected').length,
  total: items.length,
}))

const sortedItems = computed(() =>
  [...items].sort((a, b) => {
    if (a.status === 'pending' && b.status !== 'pending') return -1
    if (a.status !== 'pending' && b.status === 'pending') return 1
    return toTimestamp(b.updated_at) - toTimestamp(a.updated_at)
  }),
)

const visibleItems = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return sortedItems.value.filter((item) => {
    const matchesStatus = statusFilter.value === 'all' || item.status === statusFilter.value
    const matchesQuery =
      !query ||
      getTitle(item).toLowerCase().includes(query) ||
      String(item.submission_id).includes(query) ||
      String(item.created_by_user_id).includes(query) ||
      (item.source_identifier ?? '').toLowerCase().includes(query)
    return matchesStatus && matchesQuery
  })
})

const nextReview = computed(() =>
  sortedItems.value.find((item) => item.status === 'pending' && !item.saving),
)

const activeItem = computed(() =>
  activeSubmissionId.value == null
    ? null
    : items.find((item) => item.submission_id === activeSubmissionId.value) || null,
)

function toTimestamp(value?: string) {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizeStringArray(values: string[] | null | undefined): string[] {
  return Array.isArray(values) ? values.filter((value) => typeof value === 'string') : []
}

function toLinkRefs(values: string[] | null | undefined): LinkRef[] {
  return normalizeStringArray(values).map((value) => ({ id: value }))
}

function createForm(submission: SubmissionRecord): ModerationForm {
  return {
    source_identifier: submission.source_identifier || '',
    title: submission.title || '',
    abstract: submission.abstract || '',
    year: submission.year || undefined,
    best_oa_location: submission.best_oa_location || '',
    related_works: toLinkRefs(submission.related_works),
    referenced_works: toLinkRefs(submission.referenced_works),
  }
}

function mapItem(submission: SubmissionRecord): ModerationItem {
  return {
    ...submission,
    related_works: normalizeStringArray(submission.related_works),
    referenced_works: normalizeStringArray(submission.referenced_works),
    editing: false,
    saving: false,
    draftComment: submission.moderation_comment || '',
    form: createForm(submission),
  }
}

function buildUpsertRequest(item: ModerationItem): SubmissionUpsertRequest {
  return {
    source_identifier: item.form.source_identifier.trim(),
    title: item.form.title.trim(),
    abstract: item.form.abstract.trim(),
    year: item.form.year || 0,
    best_oa_location: item.form.best_oa_location.trim(),
    related_works: item.form.related_works
      .map((link) => link.id.trim())
      .filter((value) => value.length > 0),
    referenced_works: item.form.referenced_works
      .map((link) => link.id.trim())
      .filter((value) => value.length > 0),
  }
}

function replaceItem(submission: SubmissionRecord) {
  const next = mapItem(submission)
  const index = items.findIndex((item) => item.submission_id === next.submission_id)
  if (index >= 0) {
    items.splice(index, 1, next)
  } else {
    items.unshift(next)
  }
}

function getFilterCount(filter: ModeratorFilter) {
  if (filter === 'all') return items.length
  return items.filter((item) => item.status === filter).length
}

function getTitle(item: SubmissionRecord) {
  return item.title?.trim() || t('papers.untitledDraft')
}

function getMetadataCompleteness(item: SubmissionRecord) {
  const checks = [
    !!item.title?.trim(),
    !!item.abstract?.trim(),
    !!item.year,
    !!item.best_oa_location?.trim(),
    !!item.source_identifier?.trim(),
    (item.referenced_works?.length ?? 0) > 0,
    (item.related_works?.length ?? 0) > 0,
  ]
  const complete = checks.filter(Boolean).length
  return {
    complete,
    total: checks.length,
    percent: Math.round((complete / checks.length) * 100),
  }
}

function formatDate(value?: string) {
  if (!value) return '--'
  try {
    return new Intl.DateTimeFormat(locale.value, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value))
  } catch {
    return value
  }
}

function statusTone(status: SubmissionStatus) {
  switch (status) {
    case 'approved':
      return 'success'
    case 'rejected':
      return 'danger'
    case 'pending':
      return 'warning'
    default:
      return 'info'
  }
}

function getStep(item: SubmissionRecord) {
  if (item.status === 'approved') return t('mod.step.approved')
  if (item.status === 'rejected') return t('mod.step.rejected')
  const completeness = getMetadataCompleteness(item).percent
  return completeness >= 70 ? t('mod.step.ready') : t('mod.step.needsMetadata')
}

async function loadItems() {
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await AlibApi.listModerationSubmissions({
      limit: 100,
      offset: 0,
    })
    items.splice(0, items.length, ...response.items.map(mapItem))
    loaded.value = true
  } catch (e: any) {
    errorMsg.value = e?.message || t('mod.errLoad')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadItems()
})

function cancelEdit(item: ModerationItem) {
  item.editing = false
  item.form = createForm(item)
}

function openReviewModal(item: ModerationItem) {
  item.form = createForm(item)
  item.draftComment = item.moderation_comment || ''
  item.editing = item.status === 'pending'
  activeSubmissionId.value = item.submission_id
  reviewModalOpen.value = true
}

function closeReviewModal() {
  const item = activeItem.value
  if (item?.saving) return
  if (item) cancelEdit(item)
  reviewModalOpen.value = false
  activeSubmissionId.value = null
}

function addRelated(item: ModerationItem) {
  item.form.related_works.push({ id: '' })
}

function removeRelated(item: ModerationItem, index: number) {
  item.form.related_works.splice(index, 1)
}

function addReferenced(item: ModerationItem) {
  item.form.referenced_works.push({ id: '' })
}

function removeReferenced(item: ModerationItem, index: number) {
  item.form.referenced_works.splice(index, 1)
}

async function saveEdit(item: ModerationItem) {
  item.saving = true
  errorMsg.value = ''
  try {
    const submissionId = item.submission_id
    const response = await AlibApi.updateModerationSubmission(
      item.submission_id,
      buildUpsertRequest(item),
    )
    replaceItem(response.submission)
    const updated = items.find((candidate) => candidate.submission_id === submissionId)
    if (updated && activeSubmissionId.value === submissionId) {
      updated.editing = updated.status === 'pending'
    }
  } catch (e: any) {
    errorMsg.value = e?.message || t('papers.errSave')
  } finally {
    item.saving = false
  }
}

async function moderate(item: ModerationItem, action: ModerateSubmissionRequest['action']) {
  item.saving = true
  errorMsg.value = ''
  try {
    if (item.editing) {
      const updated = await AlibApi.updateModerationSubmission(
        item.submission_id,
        buildUpsertRequest(item),
      )
      replaceItem(updated.submission)
    }
    const response = await AlibApi.moderateSubmission(item.submission_id, {
      action,
      comment: item.draftComment.trim() || undefined,
    })
    if (statusFilter.value !== 'all' && response.submission.status !== statusFilter.value) {
      const index = items.findIndex((candidate) => candidate.submission_id === item.submission_id)
      if (index >= 0) items.splice(index, 1)
    } else {
      replaceItem(response.submission)
    }
    reviewModalOpen.value = false
    activeSubmissionId.value = null
  } catch (e: any) {
    errorMsg.value = e?.message || t('mod.errModerate')
  } finally {
    item.saving = false
  }
}

function focusItem(item: ModerationItem) {
  statusFilter.value = item.status as ModeratorFilter
  openReviewModal(item)
}

function openPublic(item: SubmissionRecord) {
  if (!item.approved_paper_id) return
  void router.push({ path: `/paper/${item.approved_paper_id}` })
}
</script>

<template>
  <UpTab :show-menu="false" :show-upload="false" />
  <LeftTab />

  <main class="moderator-area" :class="{ collapsed: leftHidden }">
    <div class="moderator-shell">
      <header class="moderator-hero">
        <div class="moderator-heading">
          <p class="moderator-heading__eyebrow">{{ t('mod.workspaceLabel') }}</p>
          <h1>{{ t('mod.title') }}</h1>
          <p>{{ t('mod.heroDescription') }}</p>
          <div class="hero-metrics" :aria-label="t('mod.summary.label')">
            <span>
              <strong>{{ summary.pending }}</strong>
              {{ t('papers.status.pending') }}
            </span>
            <span>
              <strong>{{ summary.approved }}</strong>
              {{ t('papers.status.approved') }}
            </span>
            <span>
              <strong>{{ summary.rejected }}</strong>
              {{ t('papers.status.rejected') }}
            </span>
            <span>
              <strong>{{ summary.total }}</strong>
              {{ t('papers.summary.total') }}
            </span>
          </div>
        </div>

        <div class="hero-actions">
          <button class="action-button action-button--primary" type="button" :disabled="loading" @click="loadItems">
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

      <section class="next-review-panel" :aria-label="t('mod.next.title')">
        <div class="section-heading">
          <h2>{{ t('mod.next.title') }}</h2>
        </div>

        <article v-if="nextReview" class="next-review">
          <div>
            <strong>{{ t('mod.next.reviewSubmission') }}</strong>
            <span>{{ getTitle(nextReview) }}</span>
          </div>
          <button class="action-button action-button--small" type="button" @click="focusItem(nextReview)">
            {{ t('mod.action.reviewNow') }}
          </button>
        </article>

        <div v-else class="next-review-empty">
          {{ t('mod.next.empty') }}
        </div>
      </section>

      <section class="moderator-toolbar" :aria-label="t('papers.statusLabel')">
        <div class="status-tabs" role="tablist" :aria-label="t('papers.statusLabel')">
          <button
            v-for="option in filterOptions"
            :key="option.value"
            type="button"
            class="status-tab"
            :class="{ active: statusFilter === option.value }"
            @click="
              statusFilter = option.value;
              loadItems()
            "
          >
            <span>{{ t(option.labelKey) }}</span>
            <strong>{{ getFilterCount(option.value) }}</strong>
          </button>
        </div>

        <label class="search-box">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="11" cy="11" r="7" />
            <path d="m16.5 16.5 4 4" />
          </svg>
          <input v-model.trim="searchQuery" type="search" :placeholder="t('mod.search')" />
        </label>
      </section>

      <div v-if="errorMsg" class="state-banner state-banner--error">
        <strong>{{ t('mod.errLoadTitle') }}</strong>
        <span>{{ errorMsg }}</span>
      </div>

      <div v-if="loading && !items.length" class="state-panel">
        <span class="state-spinner" aria-hidden="true"></span>
        <div>
          <h2>{{ t('mod.loadingTitle') }}</h2>
          <p>{{ t('mod.loadingDesc') }}</p>
        </div>
      </div>

      <section v-else-if="visibleItems.length" class="moderation-list" aria-label="Submissions">
        <article
          v-for="it in visibleItems"
          :id="`submission-${it.submission_id}`"
          :key="it.submission_id"
          class="moderation-card"
          :class="`moderation-card--${it.status}`"
        >
          <header class="card-header">
            <div class="card-status">
              <span class="status-pill" :class="statusTone(it.status)">
                {{ t(`papers.status.${it.status}`) }}
              </span>
              <span class="submission-id">#{{ it.submission_id }}</span>
            </div>
            <span class="metadata-compact">
              {{ t('papers.metadataComplete').replace('{percent}', String(getMetadataCompleteness(it).percent)) }}
            </span>
          </header>

          <div class="card-body">
            <section class="card-main">
              <h2>{{ getTitle(it) }}</h2>
              <p class="paper-description">{{ it.abstract || t('chat.noAbstract') }}</p>

              <div class="paper-dates">
                <span>{{ t('mod.meta.author') }}: {{ it.created_by_user_id }}</span>
                <span>{{ t('papers.updatedAt') }}: {{ formatDate(it.updated_at) }}</span>
                <span v-if="it.submitted_at">{{ t('papers.submittedAt') }}: {{ formatDate(it.submitted_at) }}</span>
              </div>

              <div class="indicator-line">
                <span :class="{ active: !!it.best_oa_location }">{{ t('papers.indicator.pdf') }}</span>
                <span :class="{ active: !!it.source_identifier }">{{ t('papers.indicator.doi') }}</span>
                <span :class="{ active: it.referenced_works.length > 0 }">{{ t('papers.indicator.references') }}</span>
                <span :class="{ active: it.related_works.length > 0 }">{{ t('papers.analytics.related') }}</span>
              </div>

              <div class="metadata-line">
                <div class="metadata-track" aria-hidden="true">
                  <span :style="{ width: `${getMetadataCompleteness(it).percent}%` }"></span>
                </div>
                <span>{{ getMetadataCompleteness(it).complete }}/{{ getMetadataCompleteness(it).total }}</span>
              </div>
            </section>

            <aside class="review-panel">
              <strong>{{ getStep(it) }}</strong>
              <p v-if="it.moderation_comment">{{ it.moderation_comment }}</p>
              <button
                v-if="it.approved_paper_id"
                class="action-button action-button--small"
                type="button"
                @click="openPublic(it)"
              >
                {{ t('papers.action.openPublic') }}
              </button>
            </aside>
          </div>

          <footer class="moderation-actions">
            <div class="action-row">
              <button class="action-button action-button--primary" type="button" @click="openReviewModal(it)">
                {{ it.status === 'pending' ? t('mod.action.reviewNow') : t('papers.action.viewSubmission') }}
              </button>
            </div>
          </footer>
        </article>
      </section>

      <div v-else-if="loaded" class="state-panel">
        <div>
          <h2>{{ t('mod.noItems') }}</h2>
          <p>{{ t('mod.noItemsHint') }}</p>
        </div>
      </div>
    </div>
  </main>

  <Teleport to="body">
    <div v-if="reviewModalOpen && activeItem" class="modal-backdrop" @click.self="closeReviewModal">
      <section class="review-modal" role="dialog" aria-modal="true" :aria-label="t('mod.next.reviewSubmission')">
        <header class="modal-head">
          <div>
            <p class="modal-eyebrow">{{ t('mod.workspaceLabel') }}</p>
            <h2>{{ getTitle(activeItem) }}</h2>
            <p>
              {{ t('mod.meta.author') }}: {{ activeItem.created_by_user_id }} ·
              {{ t('papers.updatedAt') }}: {{ formatDate(activeItem.updated_at) }}
            </p>
          </div>
          <button class="icon-button" type="button" :aria-label="t('common.cancel')" @click="closeReviewModal">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </header>

        <div class="modal-summary">
          <span class="status-pill" :class="statusTone(activeItem.status)">
            {{ t(`papers.status.${activeItem.status}`) }}
          </span>
          <span>
            {{ t('papers.metadataComplete').replace('{percent}', String(getMetadataCompleteness(activeItem).percent)) }}
          </span>
          <span>#{{ activeItem.submission_id }}</span>
        </div>

        <form class="editor editor--modal" @submit.prevent="saveEdit(activeItem)">
          <fieldset :disabled="activeItem.status !== 'pending' || activeItem.saving">
            <label>
              <span>{{ t('papers.action.importIdentifier') }}</span>
              <input
                type="text"
                v-model="activeItem.form.source_identifier"
                :placeholder="t('paperAdd.idPlaceholder')"
              />
            </label>
            <label>
              <span>{{ t('paperAdd.title') }}</span>
              <input type="text" v-model="activeItem.form.title" />
            </label>
            <label>
              <span>{{ t('paperAdd.abstract') }}</span>
              <textarea rows="5" v-model="activeItem.form.abstract"></textarea>
            </label>
            <div class="form-grid">
              <label>
                <span>{{ t('paperAdd.year') }}</span>
                <input type="number" v-model="activeItem.form.year" min="1900" max="2100" />
              </label>
              <label>
                <span>{{ t('paperAdd.pdfSource') }}</span>
                <input
                  type="text"
                  v-model="activeItem.form.best_oa_location"
                  :placeholder="t('paperAdd.placeholderUrl')"
                />
              </label>
            </div>

            <section class="links">
              <div class="link-head">
                <strong>{{ t('paperAdd.related') }}</strong>
                <button class="action-button action-button--small" type="button" @click="addRelated(activeItem)">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="link-list" v-if="activeItem.form.related_works.length">
                <div
                  class="link-item"
                  v-for="(link, index) in activeItem.form.related_works"
                  :key="`modal-rel-${index}`"
                >
                  <input type="text" v-model="link.id" :placeholder="t('paperAdd.idPlaceholder')" />
                  <button
                    class="action-button action-button--small"
                    type="button"
                    @click="removeRelated(activeItem, index)"
                  >
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>

            <section class="links">
              <div class="link-head">
                <strong>{{ t('paperAdd.referenced') }}</strong>
                <button class="action-button action-button--small" type="button" @click="addReferenced(activeItem)">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="link-list" v-if="activeItem.form.referenced_works.length">
                <div
                  class="link-item"
                  v-for="(link, index) in activeItem.form.referenced_works"
                  :key="`modal-ref-${index}`"
                >
                  <input type="text" v-model="link.id" :placeholder="t('paperAdd.idPlaceholder')" />
                  <button
                    class="action-button action-button--small"
                    type="button"
                    @click="removeReferenced(activeItem, index)"
                  >
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>
          </fieldset>

          <label v-if="activeItem.status === 'pending'" class="comment-box">
            <span>{{ t('papers.moderatorComment') }}</span>
            <textarea
              rows="3"
              v-model="activeItem.draftComment"
              :placeholder="t('mod.commentPlaceholder')"
            ></textarea>
          </label>
          <p v-else-if="activeItem.moderation_comment" class="modal-comment">
            {{ activeItem.moderation_comment }}
          </p>

          <footer class="modal-actions">
            <button class="action-button" type="button" @click="closeReviewModal">
              {{ t('common.cancel') }}
            </button>
            <button
              v-if="activeItem.status === 'pending'"
              class="action-button action-button--primary"
              type="submit"
              :disabled="activeItem.saving"
            >
              {{ activeItem.saving ? t('common.loading') : t('common.save') }}
            </button>
            <button
              v-if="activeItem.status === 'pending'"
              class="action-button action-button--success"
              type="button"
              :disabled="activeItem.saving"
              @click="moderate(activeItem, 'approve')"
            >
              {{ t('mod.action.approve') }}
            </button>
            <button
              v-if="activeItem.status === 'pending'"
              class="action-button action-button--danger"
              type="button"
              :disabled="activeItem.saving"
              @click="moderate(activeItem, 'reject')"
            >
              {{ t('mod.action.reject') }}
            </button>
            <button
              v-if="activeItem.approved_paper_id"
              class="action-button action-button--primary"
              type="button"
              @click="openPublic(activeItem)"
            >
              {{ t('papers.action.openPublic') }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.moderator-area {
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

.moderator-area.collapsed {
  left: 120px;
}

.moderator-shell {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  gap: var(--space-3);
}

.moderator-hero,
.next-review-panel,
.moderation-card,
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

.moderator-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  min-width: 0;
  padding: 20px;
  border-radius: 18px;
}

.moderator-heading {
  min-width: 0;
}

.moderator-heading__eyebrow {
  margin: 0 0 8px;
  color: var(--color-primary-secondary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.moderator-heading h1 {
  margin: 0;
  color: var(--color-text);
  font-size: clamp(1.55rem, 2vw, 2rem);
  line-height: 1.1;
}

.moderator-heading p:not(.moderator-heading__eyebrow) {
  max-width: 640px;
  margin: 10px 0 0;
  color: var(--color-muted);
  font-size: 0.98rem;
  line-height: 1.55;
}

.hero-metrics,
.indicator-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hero-metrics {
  margin-top: 14px;
}

.hero-metrics span,
.indicator-line span {
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

.indicator-line {
  margin-top: 12px;
}

.indicator-line span.active {
  border-color: color-mix(in oklab, var(--color-primary-secondary), transparent 45%);
  color: var(--color-primary-secondary);
}

.hero-actions,
.action-row {
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
  cursor: progress;
  opacity: 0.7;
}

.action-button--primary {
  border-color: transparent;
  background: var(--color-primary-secondary);
  color: var(--color-primary-contrast);
}

.action-button--success {
  border-color: transparent;
  background: var(--color-success);
  color: #fff;
}

.action-button--danger {
  border-color: transparent;
  background: var(--color-danger);
  color: #fff;
}

.action-button--primary:hover,
.action-button--primary:focus-visible,
.action-button--success:hover,
.action-button--success:focus-visible,
.action-button--danger:hover,
.action-button--danger:focus-visible {
  color: #fff;
  filter: brightness(1.04);
}

.action-button--small {
  min-height: 34px;
  padding: 7px 11px;
  font-size: 0.82rem;
}

.next-review-panel {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
  padding: 12px 14px;
  border-radius: 16px;
}

.section-heading {
  min-width: 150px;
}

.section-heading h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 1.08rem;
}

.next-review {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.next-review strong {
  display: block;
  color: var(--color-text);
  line-height: 1.3;
}

.next-review span,
.next-review-empty {
  color: var(--color-muted);
  font-size: 0.9rem;
}

.next-review span {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.moderator-toolbar {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 310px);
  gap: var(--space-3);
  align-items: center;
}

.status-tabs {
  min-width: 0;
  display: inline-flex;
  gap: 6px;
  overflow-x: auto;
  padding: 4px;
  border: 1px solid var(--color-border-soft);
  border-radius: 14px;
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 12%);
}

.status-tab {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 7px 11px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  cursor: pointer;
}

.status-tab strong {
  min-width: 22px;
  padding: 2px 6px;
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 8%);
  color: var(--color-text);
  font-size: 0.75rem;
  text-align: center;
}

.status-tab.active {
  border-color: color-mix(in oklab, var(--color-border-soft), transparent 42%);
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 7%);
  color: var(--color-text);
}

.search-box {
  min-width: 0;
  height: 48px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 13px;
  border: 1px solid var(--color-border-soft);
  border-radius: 14px;
  background: var(--color-panel-elevated);
  color: var(--color-muted);
}

.search-box input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.moderation-list {
  display: grid;
  gap: var(--space-3);
}

.moderation-card {
  display: grid;
  gap: 12px;
  padding: 15px;
  border-left-width: 3px;
  border-radius: 16px;
  scroll-margin: 100px;
}

.moderation-card--approved {
  border-left-color: var(--color-success);
}

.moderation-card--pending {
  border-left-color: var(--color-warning);
}

.moderation-card--rejected {
  border-left-color: var(--color-danger);
}

.card-header,
.card-body {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
}

.card-header {
  align-items: center;
}

.card-body {
  align-items: flex-start;
}

.card-main {
  min-width: 0;
  flex: 1 1 auto;
}

.card-main h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 1.05rem;
  line-height: 1.28;
}

.paper-description {
  display: -webkit-box;
  margin: 7px 0 0;
  overflow: hidden;
  color: var(--color-muted);
  font-size: 0.9rem;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.paper-dates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 11px;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}

.card-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.submission-id,
.metadata-compact {
  color: var(--color-muted);
  font-size: 0.82rem;
  font-weight: 700;
}

.metadata-compact {
  flex: 0 0 auto;
}

.status-pill {
  width: fit-content;
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

.status-pill.danger {
  background: color-mix(in oklab, var(--color-danger), transparent 84%);
  color: var(--color-danger);
}

.status-pill.info {
  background: color-mix(in oklab, var(--color-primary-secondary), transparent 84%);
  color: var(--color-primary-secondary);
}

.metadata-line {
  max-width: 360px;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.metadata-track {
  flex: 1 1 auto;
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-text) 9%);
}

.metadata-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary-secondary);
}

.metadata-line > span {
  color: var(--color-muted);
  font-size: 0.8rem;
  font-weight: 700;
}

.review-panel {
  width: min(290px, 34%);
  min-width: 230px;
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 28%);
  border-radius: 12px;
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 10%);
}

.review-panel strong {
  color: var(--color-text);
  font-size: 0.88rem;
  line-height: 1.35;
}

.review-panel p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.45;
}

.editor {
  display: grid;
  gap: var(--space-3);
  padding: 13px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 30%);
  border-radius: 14px;
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 8%);
}

.editor fieldset {
  display: grid;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  border: 0;
}

.editor fieldset:disabled {
  opacity: 0.72;
}

.editor--modal {
  padding: 0;
  border: 0;
  background: transparent;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.links {
  display: grid;
  gap: var(--space-2);
}

.link-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.link-head strong {
  color: var(--color-text);
}

.link-list {
  display: grid;
  gap: var(--space-2);
}

.link-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-2);
}

.moderation-actions {
  display: grid;
  gap: var(--space-2);
}

.comment-box,
.editor label {
  display: grid;
  gap: 6px;
}

.comment-box span,
.editor label span {
  color: var(--color-muted);
  font-size: 0.9rem;
}

input[type='text'],
input[type='number'],
textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

textarea {
  resize: vertical;
}

.action-row {
  justify-content: flex-end;
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

.review-modal {
  width: min(920px, 100%);
  max-height: min(860px, calc(100vh - 48px));
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
  line-height: 1.45;
}

.modal-eyebrow {
  margin: 0 0 6px;
  color: var(--color-primary-secondary);
  font-size: 0.76rem;
  font-weight: 800;
  text-transform: uppercase;
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

.modal-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.modal-summary span:not(.status-pill),
.modal-comment {
  color: var(--color-muted);
  font-size: 0.88rem;
  font-weight: 700;
}

.modal-comment {
  margin: 0;
  padding: 11px 12px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 28%);
  border-radius: 12px;
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 10%);
  line-height: 1.45;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.state-banner {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 16px;
}

.state-banner strong {
  color: var(--color-text);
}

.state-banner span {
  color: var(--color-muted);
}

.state-banner--error {
  border-color: color-mix(in oklab, var(--color-danger), transparent 58%);
  background: color-mix(in oklab, var(--color-danger), transparent 94%);
}

.state-banner--error span {
  color: var(--color-danger);
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
  color: var(--color-text);
  font-size: 1.1rem;
}

.state-panel p {
  max-width: 460px;
  margin: 8px 0 0;
  color: var(--color-muted);
  line-height: 1.5;
}

.state-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid color-mix(in oklab, var(--color-primary-secondary), transparent 72%);
  border-top-color: var(--color-primary-secondary);
  border-radius: 50%;
  animation: mod-spin 0.8s linear infinite;
}

@keyframes mod-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1280px) {
  .moderator-area {
    right: 16px;
    bottom: 16px;
    left: 270px;
  }

  .moderator-area.collapsed {
    left: 120px;
  }
}

@media (max-width: 1060px) {
  .moderator-hero,
  .card-body {
    flex-direction: column;
  }

  .review-panel {
    width: 100%;
    min-width: 0;
  }

  .moderator-toolbar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .moderator-area {
    right: 14px;
    bottom: 14px;
    left: 270px;
    padding: var(--space-3);
  }

  .moderator-area.collapsed {
    left: 120px;
  }
}

@media (max-width: 900px) {
  .moderator-area,
  .moderator-area.collapsed {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 12px;
    padding: var(--space-3);
  }
}

@media (max-width: 768px) {
  .modal-backdrop {
    padding: 12px;
  }

  .review-modal {
    max-height: calc(100vh - 24px);
    padding: 16px;
  }

  .modal-head {
    flex-direction: column;
  }

  .moderator-area {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 12px;
    padding: 0;
  }

  .moderator-hero {
    align-items: stretch;
    padding: 16px;
  }

  .hero-actions,
  .action-row {
    justify-content: flex-start;
  }

  .card-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .moderator-area,
  .moderator-area.collapsed {
    left: 12px;
  }

  .next-review-panel {
    grid-template-columns: 1fr;
  }

  .next-review {
    display: grid;
    justify-items: start;
  }

  .metadata-compact {
    flex: 1 1 auto;
  }
}

@media (max-width: 520px) {
  .moderator-area,
  .moderator-area.collapsed {
    right: 8px;
    bottom: 8px;
    left: 8px;
  }

  .moderator-shell {
    gap: 10px;
  }

  .moderator-hero,
  .next-review-panel,
  .moderation-card {
    border-radius: 14px;
  }

  .action-row,
  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .action-button {
    width: 100%;
  }

  .link-item {
    grid-template-columns: 1fr;
  }
}
</style>
