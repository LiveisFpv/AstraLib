<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import UpTab from '@/components/UpTab.vue'
import LeftTab from '@/components/LeftTab.vue'
import PaperAddView from '@/views/PaperAddView.vue'
import PaperEditView from '@/views/PaperEditView.vue'
import { usePaperStore, type PaperDetail } from '@/stores/paperStore'
import { useToastStore } from '@/stores/toastStore'
import { locale, useI18n } from '@/i18n'
import { useLayoutInset } from '@/composables/useLayoutInset'

type AuthorStatus =
  | 'draft'
  | 'ready'
  | 'inReview'
  | 'changesRequested'
  | 'approved'
  | 'published'
  | 'rejected'
type AuthorFilter = 'all' | 'drafts' | 'attention' | 'review' | 'published'

const paperStore = usePaperStore()
const toastStore = useToastStore()
const router = useRouter()
const { t } = useI18n()
const { LeftTabHidden: leftHidden } = useLayoutInset()

const selectedFilter = ref<AuthorFilter>('all')
const searchQuery = ref('')
const loadError = ref('')
const busyId = ref<string | null>(null)
const isAddModalOpen = ref(false)
const isImportMode = ref(false)
const isEditModalOpen = ref(false)
const editingPaperId = ref<string | null>(null)

const filterOptions: Array<{ value: AuthorFilter; labelKey: string }> = [
  { value: 'all', labelKey: 'papers.filter.allShort' },
  { value: 'drafts', labelKey: 'papers.filter.drafts' },
  { value: 'attention', labelKey: 'papers.filter.attention' },
  { value: 'review', labelKey: 'papers.filter.review' },
  { value: 'published', labelKey: 'papers.filter.published' },
]

onMounted(() => {
  void loadPapers()
})

const papers = computed(() =>
  [...paperStore.papers].sort((a, b) => toTimestamp(b.updatedAt) - toTimestamp(a.updatedAt)),
)

const enrichedPapers = computed(() =>
  papers.value.map((paper) => ({
    paper,
    status: getAuthorStatus(paper),
    completeness: getMetadataCompleteness(paper),
    analytics: getAnalytics(paper),
  })),
)

const visiblePapers = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return enrichedPapers.value.filter((item) => {
    const matchesFilter = filterMatches(item.status, selectedFilter.value)
    const matchesQuery =
      !query ||
      getPaperTitle(item.paper).toLowerCase().includes(query) ||
      item.paper.id.toLowerCase().includes(query) ||
      String(item.paper.approvedPaperId ?? '').includes(query) ||
      (item.paper.source_identifier ?? '').toLowerCase().includes(query)
    return matchesFilter && matchesQuery
  })
})

const summary = computed(() => ({
  drafts: enrichedPapers.value.filter((item) => item.status === 'draft' || item.status === 'ready')
    .length,
  review: enrichedPapers.value.filter((item) => item.status === 'inReview').length,
  attention: enrichedPapers.value.filter(
    (item) => item.status === 'changesRequested' || item.status === 'rejected',
  ).length,
  published: enrichedPapers.value.filter(
    (item) => item.status === 'approved' || item.status === 'published',
  ).length,
}))

const nextActions = computed(() => {
  const actions = enrichedPapers.value
    .flatMap((item) => {
      const { paper, status, completeness } = item
      if (status === 'draft' && completeness.percent < 100) {
        return [
          {
            key: `complete-${paper.id}`,
            tone: 'info',
            title: t('papers.next.completeMetadata'),
            description: getPaperTitle(paper),
            actionLabel: t('papers.action.continueEditing'),
            run: () => goToEdit(paper.id),
          },
        ]
      }
      if (status === 'changesRequested' || status === 'rejected') {
        return [
          {
            key: `comments-${paper.id}`,
            tone: 'danger',
            title: t('papers.next.reviewComments'),
            description: getPaperTitle(paper),
            actionLabel: t('papers.action.viewComments'),
            run: () => goToEdit(paper.id),
          },
        ]
      }
      if (status === 'ready') {
        return [
          {
            key: `submit-${paper.id}`,
            tone: 'accent',
            title: t('papers.next.submitForReview'),
            description: getPaperTitle(paper),
            actionLabel: t('papers.action.submitReview'),
            run: () => submitForReview(paper.id),
          },
        ]
      }
      if (status === 'published') {
        return [
          {
            key: `analytics-${paper.id}`,
            tone: 'success',
            title: t('papers.next.openAnalytics'),
            description: getPaperTitle(paper),
            actionLabel: t('papers.action.viewAnalytics'),
            run: () => openPublicOrSubmission(paper),
          },
        ]
      }
      return []
    })
    .slice(0, 4)
  return actions
})

const lastLoadedLabel = computed(() => {
  if (!paperStore.lastLoaded) return t('papers.notLoaded')
  return formatDate(paperStore.lastLoaded)
})

function toTimestamp(value?: string) {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function formatDate(value?: string) {
  if (!value) return '--'
  try {
    const dt = new Date(value)
    return new Intl.DateTimeFormat(locale.value, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(dt)
  } catch {
    return value
  }
}

function getPaperTitle(paper: PaperDetail) {
  return paper.title?.trim() || t('papers.untitledDraft')
}

function getAuthorStatus(paper: PaperDetail): AuthorStatus {
  const completeness = getMetadataCompleteness(paper).percent
  if (paper.status === 'approved' && paper.approvedPaperId) return 'published'
  if (paper.status === 'approved') return 'approved'
  if (paper.status === 'pending') return 'inReview'
  if (paper.status === 'rejected' && paper.moderatorComment) return 'changesRequested'
  if (paper.status === 'rejected') return 'rejected'
  if (paper.status === 'draft' && completeness >= 70 && !!paper.title && !!paper.abstract) return 'ready'
  return 'draft'
}

function getMetadataCompleteness(paper: PaperDetail) {
  const checks = [
    !!paper.title?.trim(),
    !!paper.abstract?.trim(),
    !!paper.year,
    !!paper.best_oa_location?.trim(),
    !!paper.source_identifier?.trim(),
    (paper.referenced_paper?.length ?? 0) > 0,
    (paper.related_paper?.length ?? 0) > 0,
  ]
  const complete = checks.filter(Boolean).length
  return {
    complete,
    total: checks.length,
    percent: Math.round((complete / checks.length) * 100),
  }
}

function getAnalytics(paper: PaperDetail) {
  const seed = Number(paper.approvedPaperId || paper.id) || 0
  const relatedCount = paper.related_paper?.length ?? 0
  const referenceCount = paper.referenced_paper?.length ?? 0
  return {
    appearances: seed ? 80 + (seed % 43) + relatedCount * 3 : 0,
    opens: seed ? 18 + (seed % 21) + relatedCount : 0,
    citations: Math.max(0, Math.floor(referenceCount / 2)),
    related: relatedCount,
  }
}

function filterMatches(status: AuthorStatus, filter: AuthorFilter) {
  if (filter === 'all') return true
  if (filter === 'drafts') return status === 'draft' || status === 'ready'
  if (filter === 'attention') return status === 'changesRequested' || status === 'rejected'
  if (filter === 'review') return status === 'inReview'
  return status === 'approved' || status === 'published'
}

function getFilterCount(filter: AuthorFilter) {
  return enrichedPapers.value.filter((item) => filterMatches(item.status, filter)).length
}

function getStatusLabel(status: AuthorStatus) {
  return t(`papers.authorStatus.${status}`)
}

function getStatusTone(status: AuthorStatus) {
  if (status === 'published' || status === 'approved') return 'success'
  if (status === 'inReview' || status === 'ready') return 'warning'
  if (status === 'changesRequested' || status === 'rejected') return 'danger'
  return 'info'
}

function getCurrentStep(status: AuthorStatus) {
  return t(`papers.step.${status}`)
}

function getPrimaryActionLabel(status: AuthorStatus) {
  switch (status) {
    case 'draft':
      return t('papers.action.continueEditing')
    case 'ready':
      return t('papers.action.submitReview')
    case 'changesRequested':
    case 'rejected':
      return t('papers.action.viewComments')
    case 'published':
      return t('papers.action.viewAnalytics')
    case 'approved':
      return t('papers.action.openPublic')
    default:
      return t('papers.action.viewSubmission')
  }
}

function runPrimaryAction(paper: PaperDetail, status: AuthorStatus) {
  if (status === 'ready') {
    void submitForReview(paper.id)
    return
  }
  if ((status === 'published' || status === 'approved') && paper.approvedPaperId) {
    openPublic(paper.approvedPaperId)
    return
  }
  goToEdit(paper.id)
}

async function loadPapers() {
  loadError.value = ''
  try {
    await paperStore.loadMyPapers()
  } catch (e: any) {
    loadError.value = e?.message || t('papers.errLoad')
  }
}

function goToEdit(id: string) {
  editingPaperId.value = id
  isEditModalOpen.value = true
}

function goToAdd() {
  isImportMode.value = false
  isAddModalOpen.value = true
}

function goToImport() {
  isImportMode.value = true
  isAddModalOpen.value = true
}

function openPublic(paperId: number) {
  router.push({ path: `/paper/${paperId}` })
}

function openPublicOrSubmission(paper: PaperDetail) {
  if (paper.approvedPaperId) {
    openPublic(paper.approvedPaperId)
    return
  }
  goToEdit(paper.id)
}

async function submitForReview(id: string) {
  try {
    busyId.value = id
    await paperStore.submitExisting(id)
  } catch (e: any) {
    loadError.value = e?.message || t('paperAdd.errSubmit')
  } finally {
    busyId.value = null
  }
}

async function duplicatePaper(paper: PaperDetail) {
  try {
    busyId.value = paper.id
    const duplicate = await paperStore.saveDraft({
      title: paper.title ? `${paper.title} (${t('papers.copySuffix')})` : t('papers.untitledDraft'),
      abstract: paper.abstract,
      year: paper.year,
      best_oa_location: paper.best_oa_location,
      source_identifier: paper.source_identifier,
      related_paper: paper.related_paper,
      referenced_paper: paper.referenced_paper,
    })
    goToEdit(duplicate.id)
  } catch (e: any) {
    loadError.value = e?.message || t('papers.errDuplicate')
  } finally {
    busyId.value = null
  }
}

async function copySubmissionLink(paper: PaperDetail) {
  try {
    const href = router.resolve({ name: 'my-papers' }).href
    const url = new URL(href, window.location.origin).toString()
    await navigator.clipboard.writeText(url)
    toastStore.show(t('papers.copyOk'), { variant: 'success' })
  } catch {
    toastStore.show(t('papers.copyFail'), { variant: 'error' })
  }
}

function handleSubmissionChanged() {
  loadError.value = ''
}

function closeEditModal(value: boolean) {
  isEditModalOpen.value = value
  if (!value) editingPaperId.value = null
}

async function handleDelete(id: string) {
  if (typeof window !== 'undefined' && !window.confirm(t('papers.deleteConfirm'))) {
    return
  }
  try {
    busyId.value = id
    await paperStore.deletePaper(id)
  } catch (e: any) {
    loadError.value = e?.message || t('papers.errDelete')
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <UpTab :show-menu="false" :show-upload="false" />
  <LeftTab />

  <main
    class="papers-area"
    :class="{ collapsed: leftHidden }"
  >
    <div class="papers-shell">
      <header class="papers-hero">
        <div class="papers-heading">
          <p class="papers-heading__eyebrow">{{ t('papers.workspaceLabel') }}</p>
          <h1>{{ t('papers.title') }}</h1>
          <p>{{ t('papers.heroDescription') }}</p>
          <div class="hero-metrics" :aria-label="t('papers.summary.label')">
            <span>
              <strong>{{ summary.drafts }}</strong>
              {{ t('papers.summary.drafts') }}
            </span>
            <span>
              <strong>{{ summary.review }}</strong>
              {{ t('papers.summary.review') }}
            </span>
            <span>
              <strong>{{ summary.attention }}</strong>
              {{ t('papers.summary.attention') }}
            </span>
            <span>
              <strong>{{ summary.published }}</strong>
              {{ t('papers.summary.published') }}
            </span>
          </div>
        </div>

        <div class="papers-actions">
          <button class="action-button action-button--primary" type="button" @click="goToAdd">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M12 5v14" />
              <path d="M5 12h14" />
            </svg>
            {{ t('papers.action.newSubmission') }}
          </button>
          <button class="action-button" type="button" @click="goToImport">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1" />
              <path d="M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.1-1.1" />
            </svg>
            {{ t('papers.action.importIdentifier') }}
          </button>
        </div>
      </header>

      <section class="next-actions-panel" :aria-label="t('papers.next.title')">
        <div class="section-heading">
          <h2>{{ t('papers.next.title') }}</h2>
        </div>

        <article
          v-if="nextActions.length"
          class="next-action next-action--compact"
          :class="`next-action--${nextActions[0].tone}`"
        >
          <div>
            <strong>{{ nextActions[0].title }}</strong>
            <span>{{ nextActions[0].description }}</span>
          </div>
          <button class="action-button action-button--small" type="button" @click="nextActions[0].run">
            {{ nextActions[0].actionLabel }}
          </button>
        </article>

        <div v-else class="next-action-empty">
          {{ t('papers.next.empty') }}
        </div>
      </section>

      <section class="papers-toolbar" :aria-label="t('papers.statusLabel')">
        <div class="status-tabs" role="tablist" :aria-label="t('papers.statusLabel')">
          <button
            v-for="option in filterOptions"
            :key="option.value"
            type="button"
            class="status-tab"
            :class="{ active: selectedFilter === option.value }"
            @click="selectedFilter = option.value"
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
          <input v-model.trim="searchQuery" type="search" :placeholder="t('papers.search')" />
        </label>
      </section>

      <div v-if="loadError" class="state-banner state-banner--error">
        <strong>{{ t('papers.errLoadTitle') }}</strong>
        <span>{{ loadError }}</span>
      </div>

      <div v-if="paperStore.isLoading && !papers.length" class="state-panel">
        <span class="state-spinner" aria-hidden="true"></span>
        <div>
          <h2>{{ t('papers.loadingTitle') }}</h2>
          <p>{{ t('papers.loadingDesc') }}</p>
        </div>
      </div>

      <section v-else-if="visiblePapers.length" class="paper-workflow-list" aria-label="Papers">
        <article
          v-for="item in visiblePapers"
          :key="item.paper.id"
          class="paper-workflow-card"
          :class="`paper-workflow-card--${item.status}`"
        >
          <header class="paper-card-header">
            <div class="paper-card-status">
              <span class="status-pill" :class="getStatusTone(item.status)">
                {{ getStatusLabel(item.status) }}
              </span>
              <span class="submission-id">#{{ item.paper.id }}</span>
            </div>
            <span class="metadata-compact">
              {{ t('papers.metadataComplete').replace('{percent}', String(item.completeness.percent)) }}
            </span>
          </header>

          <div class="paper-card-body">
            <section class="paper-card-main">
              <h2>{{ getPaperTitle(item.paper) }}</h2>
              <p class="paper-description">
                {{ item.paper.abstract || t('papers.descriptionFallback') }}
              </p>

              <div class="paper-dates">
                <span>{{ t('papers.updatedAt') }}: {{ formatDate(item.paper.updatedAt) }}</span>
                <span v-if="item.paper.submittedAt">
                  {{ t('papers.submittedAt') }}: {{ formatDate(item.paper.submittedAt) }}
                </span>
              </div>

              <div class="metadata-line">
                <div class="metadata-track" aria-hidden="true">
                  <span :style="{ width: `${item.completeness.percent}%` }"></span>
                </div>
                <span>{{ item.completeness.complete }}/{{ item.completeness.total }}</span>
              </div>
            </section>

            <aside class="paper-step-panel">
              <strong>{{ getCurrentStep(item.status) }}</strong>
              <p v-if="item.paper.moderatorComment">{{ item.paper.moderatorComment }}</p>
            </aside>
          </div>

          <section
            v-if="item.status === 'published' || item.status === 'approved'"
            class="analytics-summary"
            :aria-label="t('papers.analytics.title')"
          >
            <span>{{ t('papers.analytics.appearances') }}: {{ item.analytics.appearances }}</span>
            <span>{{ t('papers.analytics.opens') }}: {{ item.analytics.opens }}</span>
            <span>{{ t('papers.analytics.citations') }}: {{ item.analytics.citations }}</span>
          </section>

          <footer class="paper-card-actions">
            <button
              class="action-button action-button--primary"
              type="button"
              :disabled="busyId === item.paper.id"
              @click="runPrimaryAction(item.paper, item.status)"
            >
              {{ busyId === item.paper.id ? t('common.loading') : getPrimaryActionLabel(item.status) }}
            </button>
            <button
              v-if="item.paper.approvedPaperId"
              class="action-button"
              type="button"
              @click="openPublic(item.paper.approvedPaperId)"
            >
              {{ t('papers.action.openPublic') }}
            </button>
            <!-- <button class="action-button" type="button" @click="duplicatePaper(item.paper)">
              {{ t('papers.action.duplicate') }}
            </button>
            <button class="action-button" type="button" @click="copySubmissionLink(item.paper)">
              {{ t('papers.action.copyLink') }}
            </button> -->
            <button
              v-if="paperStore.canDelete(item.paper.id)"
              class="action-button action-button--danger"
              type="button"
              :disabled="busyId === item.paper.id"
              @click="handleDelete(item.paper.id)"
            >
              {{ t('common.delete') }}
            </button>
          </footer>
        </article>
      </section>

      <div v-else class="state-panel">
        <div>
          <h2>{{ papers.length ? t('papers.emptyFilteredTitle') : t('papers.emptyTitle') }}</h2>
          <p>{{ papers.length ? t('papers.emptyFiltered') : t('papers.empty') }}</p>
        </div>
        <button v-if="!papers.length" class="action-button action-button--primary" type="button" @click="goToAdd">
          {{ t('papers.action.newSubmission') }}
        </button>
      </div>

      <footer class="papers-footer">
        <button class="footer-refresh" type="button" :disabled="paperStore.isLoading" @click="loadPapers">
          {{ paperStore.isLoading ? t('common.loading') : t('common.refresh') }}
        </button>
        <span>{{ t('papers.lastUpdated') }}: {{ lastLoadedLabel }}</span>
      </footer>
    </div>
  </main>

  <PaperAddView
    v-model:open="isAddModalOpen"
    :import-mode="isImportMode"
    @saved="handleSubmissionChanged"
    @submitted="handleSubmissionChanged"
  />
  <PaperEditView
    :open="isEditModalOpen"
    :paper-id="editingPaperId"
    @update:open="closeEditModal"
    @saved="handleSubmissionChanged"
    @submitted="handleSubmissionChanged"
    @deleted="handleSubmissionChanged"
  />
</template>

<style scoped>
.papers-area {
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

.papers-area.collapsed {
  left: 120px;
}

.papers-shell {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  gap: var(--space-3);
}

.papers-hero,
.next-actions-panel,
.paper-workflow-card,
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

.papers-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 20px;
  border-radius: 18px;
  min-width: 0;
}

.papers-heading {
  min-width: 0;
}

.papers-heading__eyebrow {
  margin: 0 0 8px;
  color: var(--color-primary-secondary);
  font-size: 0.76rem;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.papers-heading h1 {
  margin: 0;
  color: var(--color-text);
  font-size: clamp(1.55rem, 2vw, 2rem);
  line-height: 1.1;
}

.papers-heading p:not(.papers-heading__eyebrow) {
  max-width: 620px;
  margin: 10px 0 0;
  color: var(--color-muted);
  font-size: 0.98rem;
  line-height: 1.55;
}

.hero-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.hero-metrics span {
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

.papers-actions,
.paper-card-actions {
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
  transition:
    background var(--transition-fast) ease,
    border-color var(--transition-fast) ease,
    color var(--transition-fast) ease,
    transform var(--transition-fast) ease;
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

.action-button:active {
  transform: translateY(1px);
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

.action-button--primary:hover,
.action-button--primary:focus-visible {
  color: var(--color-primary-contrast);
  filter: brightness(1.04);
}

.action-button--danger {
  color: var(--color-danger);
}

.action-button--small {
  min-height: 34px;
  padding: 7px 11px;
  font-size: 0.82rem;
}

.next-actions-panel {
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

.section-heading p {
  display: none;
}

.next-action {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 0;
  border: 0;
  background: transparent;
}

.next-action--compact {
  min-width: 0;
}

.next-action strong {
  display: block;
  color: var(--color-text);
  line-height: 1.3;
}

.next-action span {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--color-muted);
  font-size: 0.84rem;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.next-action-empty {
  color: var(--color-muted);
  font-size: 0.9rem;
}

.papers-toolbar {
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

.paper-workflow-list {
  display: grid;
  gap: var(--space-3);
}

.paper-workflow-card {
  position: relative;
  display: grid;
  gap: 12px;
  padding: 15px;
  border-left-width: 3px;
  border-radius: 16px;
}

.paper-workflow-card--published,
.paper-workflow-card--approved {
  border-left-color: var(--color-success);
}

.paper-workflow-card--inReview,
.paper-workflow-card--ready {
  border-left-color: var(--color-warning);
}

.paper-workflow-card--changesRequested,
.paper-workflow-card--rejected {
  border-left-color: var(--color-danger);
}

.paper-workflow-card--draft {
  border-left-color: var(--color-primary-secondary);
}

.paper-card-header,
.paper-card-body,
.paper-card-actions {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
}

.paper-card-header {
  align-items: center;
}

.paper-card-body {
  align-items: flex-start;
}

.paper-card-main {
  min-width: 0;
  flex: 1 1 auto;
}

.paper-card-main h2 {
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
  -webkit-line-clamp: 1;
}

.paper-dates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 11px;
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}

.submission-id {
  color: var(--color-muted);
  font-size: 0.78rem;
  font-weight: 700;
}

.paper-card-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
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

.metadata-compact {
  flex: 0 0 auto;
  color: var(--color-muted);
  font-size: 0.82rem;
  font-weight: 700;
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

.paper-step-panel {
  width: min(280px, 32%);
  min-width: 220px;
  display: grid;
  align-content: start;
  gap: 6px;
  padding: 11px 12px;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 28%);
  border-radius: 12px;
  background: color-mix(in oklab, var(--color-panel), var(--color-bg) 10%);
}

.paper-step-panel strong {
  color: var(--color-text);
  font-size: 0.88rem;
  line-height: 1.35;
}

.paper-step-panel p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.45;
}

.analytics-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  padding-top: 10px;
  border: 1px solid color-mix(in oklab, var(--color-success), transparent 76%);
  border-width: 1px 0 0;
  border-radius: 0;
  background: color-mix(in oklab, var(--color-success), transparent 95%);
}

.analytics-summary span {
  color: var(--color-muted);
  font-size: 0.8rem;
  font-weight: 700;
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
  animation: papers-spin 0.8s linear infinite;
}

.papers-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  color: var(--color-muted);
  font-size: 0.82rem;
}

.footer-refresh {
  border: 0;
  background: transparent;
  color: var(--color-primary-secondary);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.footer-refresh:disabled {
  cursor: progress;
  opacity: 0.7;
}

@keyframes papers-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1280px) {
  .papers-area {
    right: 16px;
    bottom: 16px;
    left: 270px;
  }

  .papers-area.collapsed {
    left: 120px;
  }

}

@media (max-width: 1060px) {
  .papers-hero,
  .paper-card-body {
    flex-direction: column;
  }

  .paper-step-panel {
    width: 100%;
    min-width: 0;
  }

  .papers-toolbar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .papers-area {
    right: 14px;
    bottom: 14px;
    left: 270px;
    padding: var(--space-3);
  }

  .papers-area.collapsed {
    left: 120px;
  }
}

@media (max-width: 768px) {
  .papers-area {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 270px;
    padding: 0;
  }

  .papers-hero {
    align-items: stretch;
    padding: 16px;
  }

  .papers-actions,
  .paper-card-actions,
  .papers-footer {
    justify-content: flex-start;
  }

  .paper-card-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
}

@media (max-width: 700px) {
  :deep(.left-tab) {
    width: 60px;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
  }

  :deep(.left-tab .icon-text p) {
    display: none;
  }

  :deep(.left-tab .header) {
    justify-content: center;
    flex-direction: column;
    padding: 0 5px;
    gap: 10px;
  }

  :deep(.up-tab) {
    left: 80px;
  }

  .papers-area,
  .papers-area.collapsed {
    left: 72px;
  }

  .papers-toolbar,
  .paper-card-body,
  .next-actions-panel {
    grid-template-columns: 1fr;
  }

  .next-actions-panel,
  .next-action {
    display: grid;
  }

  .next-action {
    justify-items: start;
  }

  .metadata-compact {
    flex: 1 1 auto;
  }
}

@media (max-width: 520px) {
  .papers-area,
  .papers-area.collapsed {
    left: 66px;
    right: 8px;
    bottom: 8px;
  }

  .papers-shell {
    gap: 10px;
  }

  .papers-hero,
  .next-actions-panel,
  .paper-workflow-card {
    border-radius: 14px;
  }

  .paper-card-actions,
  .papers-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .action-button {
    width: 100%;
  }

  .hero-metrics {
    gap: 6px;
  }
}
</style>
