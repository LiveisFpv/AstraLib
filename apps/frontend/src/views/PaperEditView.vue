<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { usePaperStore, type PaperPayload, type PaperStatus } from '@/stores/paperStore'
import { locale, useI18n } from '@/i18n'

type Related = { id: string }
type Referenced = { id: string }

const props = defineProps<{
  open: boolean
  paperId: string | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: [id: string]
  submitted: [id: string]
  deleted: [id: string]
}>()

const paperStore = usePaperStore()
const { t } = useI18n()
const currentId = computed(() => props.paperId || '')
const loading = ref(false)
const saving = ref(false)
const successMsg = ref('')
const errorMsg = ref('')

const statusKeyMap: Record<PaperStatus, string> = {
  draft: 'papers.status.draft',
  pending: 'papers.status.pending',
  rejected: 'papers.status.rejected',
  approved: 'papers.status.approved',
}

const form = reactive({
  source_identifier: '',
  title: '',
  abstract: '',
  year: undefined as number | undefined,
  best_oa_location: '',
  related_paper: [] as Related[],
  referenced_paper: [] as Referenced[],
})

const paper = computed(() => paperStore.getById(currentId.value))
const canEdit = computed(() => (paper.value ? paperStore.canEdit(paper.value.id) : false))
const canDelete = computed(() => (paper.value ? paperStore.canDelete(paper.value.id) : false))
const statusLabel = computed(() => {
  const status = paper.value?.status ?? 'draft'
  return t(statusKeyMap[status])
})

watch(
  () => [props.open, currentId.value] as const,
  async (value) => {
    const [open, id] = value
    if (!open || !id) return
    loading.value = true
    errorMsg.value = ''
    successMsg.value = ''
    try {
      await paperStore.fetchSubmission(id)
    } catch (e: any) {
      if (!paperStore.getById(id)) {
        errorMsg.value = e?.message || t('papers.errNotFound')
      }
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

watch(
  () => paper.value,
  (value) => {
    if (!props.open || !value) return
    form.source_identifier = value.source_identifier || ''
    form.title = value.title
    form.abstract = value.abstract || ''
    form.year = value.year
    form.best_oa_location = value.best_oa_location || ''
    form.related_paper = value.related_paper?.map((item) => ({ id: item.id || '' })) ?? []
    form.referenced_paper = value.referenced_paper?.map((item) => ({ id: item.id || '' })) ?? []
  },
  { immediate: true },
)

function statusTone(status: PaperStatus | undefined) {
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

function addRelated() {
  form.related_paper.push({ id: '' })
}
function removeRelated(index: number) {
  form.related_paper.splice(index, 1)
}
function addReferenced() {
  form.referenced_paper.push({ id: '' })
}
function removeReferenced(index: number) {
  form.referenced_paper.splice(index, 1)
}

function buildPayload(): PaperPayload {
  return {
    id: paper.value?.id,
    source_identifier: form.source_identifier.trim() || undefined,
    title: form.title.trim() || undefined,
    abstract: form.abstract.trim() || undefined,
    year: form.year,
    best_oa_location: form.best_oa_location.trim() || undefined,
    related_paper: form.related_paper
      .filter((item) => item.id.trim())
      .map((item) => ({ id: item.id.trim() })),
    referenced_paper: form.referenced_paper
      .filter((item) => item.id.trim())
      .map((item) => ({ id: item.id.trim() })),
  }
}

async function saveDraft() {
  successMsg.value = ''
  errorMsg.value = ''
  if (!paper.value) {
    errorMsg.value = t('papers.errNotFound')
    return
  }
  if (!canEdit.value) {
    errorMsg.value = t('papers.errNotEditable')
    return
  }
  try {
    saving.value = true
    await paperStore.saveDraft(buildPayload())
    emit('saved', paper.value.id)
    successMsg.value = t('papers.okSaved')
  } catch (e: any) {
    errorMsg.value = e?.message || t('papers.errSave')
  } finally {
    saving.value = false
  }
}

async function submitForReview() {
  successMsg.value = ''
  errorMsg.value = ''
  if (!paper.value) {
    errorMsg.value = t('papers.errNotFound')
    return
  }
  if (!canEdit.value) {
    errorMsg.value = t('papers.errNotEditable')
    return
  }
  if (!form.title.trim()) {
    errorMsg.value = t('paperAdd.errNoTitle')
    return
  }
  try {
    saving.value = true
    await paperStore.submitPaper(buildPayload())
    emit('submitted', paper.value.id)
    successMsg.value = t('paperAdd.okSubmitted')
    emit('update:open', false)
  } catch (e: any) {
    errorMsg.value = e?.message || t('paperAdd.errSubmit')
  } finally {
    saving.value = false
  }
}

async function deleteSubmission() {
  if (!paper.value || !canDelete.value) return
  if (typeof window !== 'undefined' && !window.confirm(t('papers.deleteConfirm'))) {
    return
  }
  try {
    saving.value = true
    const deletedId = paper.value.id
    await paperStore.deletePaper(paper.value.id)
    emit('deleted', deletedId)
    emit('update:open', false)
  } catch (e: any) {
    errorMsg.value = e?.message || t('papers.errDelete')
  } finally {
    saving.value = false
  }
}

function goBack() {
  if (saving.value) return
  emit('update:open', false)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="goBack">
      <section class="paper-modal" role="dialog" aria-modal="true" :aria-label="t('paperEdit.title')">
      <template v-if="paper">
        <header class="modal-head">
          <div>
            <h2>{{ t('paperEdit.title') }}</h2>
            <p class="muted">
              {{ t('paperEdit.statusLabel') }}
              <span class="status" :class="statusTone(paper.status)">{{ statusLabel }}</span>
            </p>
            <p class="meta-line">
              <span>{{ t('papers.updatedAt') }}: {{ formatDate(paper.updatedAt) }}</span>
              <span v-if="paper.submittedAt">
                {{ t('papers.submittedAt') }}: {{ formatDate(paper.submittedAt) }}
              </span>
            </p>
          </div>
          <aside class="side-info" v-if="paper.moderatorComment">
            <strong>{{ t('papers.moderatorComment') }}</strong>
            <p>{{ paper.moderatorComment }}</p>
          </aside>
          <button class="icon-button" type="button" :aria-label="t('common.cancel')" @click="goBack">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </header>

        <form class="form" @submit.prevent="submitForReview">
          <fieldset :disabled="!canEdit || saving">
            <label>
              <span>{{ t('papers.action.importIdentifier') }}</span>
              <input
                type="text"
                v-model="form.source_identifier"
                :placeholder="t('paperAdd.idPlaceholder')"
              />
            </label>
            <label>
              <span>{{ t('paperAdd.title') }}</span>
              <input type="text" v-model="form.title" />
            </label>
            <label>
              <span>{{ t('paperAdd.abstract') }}</span>
              <textarea v-model="form.abstract" rows="5"></textarea>
            </label>
            <div class="grid">
              <label>
                <span>{{ t('paperAdd.year') }}</span>
                <input type="number" v-model="form.year" min="1900" max="2100" />
              </label>
              <label>
                <span>{{ t('paperAdd.pdfSource') }}</span>
                <input type="text" v-model="form.best_oa_location" placeholder="https://..." />
              </label>
            </div>

            <section class="subsection">
              <div class="row">
                <h3>{{ t('paperAdd.related') }}</h3>
                <button class="btn" type="button" @click="addRelated">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="list" v-if="form.related_paper.length">
                <div class="item" v-for="(rel, idx) in form.related_paper" :key="idx">
                  <input type="text" v-model="rel.id" />
                  <button class="btn" type="button" @click="removeRelated(idx)">
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>

            <section class="subsection">
              <div class="row">
                <h3>{{ t('paperAdd.referenced') }}</h3>
                <button class="btn" type="button" @click="addReferenced">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="list" v-if="form.referenced_paper.length">
                <div class="item" v-for="(ref, idx) in form.referenced_paper" :key="idx">
                  <input type="text" v-model="ref.id" />
                  <button class="btn" type="button" @click="removeReferenced(idx)">
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>
          </fieldset>

          <div class="feedback">
            <span class="ok" v-if="successMsg">{{ successMsg }}</span>
            <span class="err" v-else-if="errorMsg">{{ errorMsg }}</span>
            <span class="muted" v-else-if="!canEdit">{{ t('paperEdit.readonly') }}</span>
          </div>

          <div class="actions">
            <button class="btn" type="button" @click="goBack">
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn danger"
              type="button"
              v-if="canDelete"
              :disabled="saving"
              @click="deleteSubmission"
            >
              {{ t('common.delete') }}
            </button>
            <button class="btn" type="button" v-if="canEdit" :disabled="saving" @click="saveDraft">
              {{ saving ? t('common.loading') : t('common.save') }}
            </button>
            <button class="btn primary" type="submit" :disabled="saving || !canEdit">
              {{ saving ? t('common.submitting') : t('common.submit') }}
            </button>
          </div>
        </form>
      </template>
      <section v-else-if="loading" class="empty">
        <p class="muted">{{ t('common.loading') }}</p>
      </section>
      <section v-else class="empty">
        <h3>{{ t('papers.errNotFound') }}</h3>
        <p class="muted">{{ t('paperEdit.notFoundHint') }}</p>
        <button class="btn primary" type="button" @click="goBack">
          {{ t('papers.action.back') }}
        </button>
      </section>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
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
.paper-modal {
  width: min(920px, 100%);
  max-height: min(840px, calc(100vh - 48px));
  max-width: 900px;
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
  gap: var(--space-4);
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
}
.modal-head h2 {
  margin: 0;
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
.btn.link {
  background: none;
  border: none;
  padding: 0;
  color: var(--color-primary-secondary);
  cursor: pointer;
  text-decoration: underline;
}
.muted {
  color: var(--color-muted);
}
.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}
.status {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
}
.status.success {
  background: color-mix(in oklab, var(--color-success), white 70%);
  color: var(--color-success);
}
.status.warning {
  background: color-mix(in oklab, var(--color-warning), white 70%);
  color: var(--color-warning);
}
.status.danger {
  background: color-mix(in oklab, var(--color-danger), white 70%);
  color: var(--color-danger);
}
.status.info {
  background: color-mix(in oklab, var(--color-primary-secondary), white 70%);
  color: var(--color-primary-secondary);
}
.side-info {
  min-width: 240px;
  max-width: 320px;
  padding: var(--space-2);
  border-left: 2px solid var(--color-border);
  background: var(--color-bg-secondary);
  border-radius: 8px;
}
.form {
  display: grid;
  gap: var(--space-4);
}
fieldset {
  display: grid;
  gap: var(--space-3);
  border: none;
  padding: 0;
  margin: 0;
}
label {
  display: grid;
  gap: 6px;
}
label span {
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
  border-radius: 6px;
  background: var(--color-surface);
  color: var(--color-text);
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
.subsection {
  display: grid;
  gap: var(--space-3);
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}
.list {
  display: grid;
  gap: var(--space-2);
}
.item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-2);
}
.feedback {
  min-height: 1.25rem;
}
.ok {
  color: var(--color-success);
}
.err {
  color: var(--color-danger);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
.btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.btn.primary {
  background: var(--color-primary-secondary);
  border-color: var(--color-primary-secondary);
  color: #fff;
}
.btn.danger {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: #fff;
}
.empty {
  padding: var(--space-4);
  border: 1px dashed var(--color-border);
  border-radius: 10px;
  text-align: center;
  background: var(--color-bg-secondary);
}
@media (max-width: 960px) {
  .side-info {
    width: 100%;
    max-width: none;
  }
}
@media (max-width: 768px) {
  .modal-backdrop {
    padding: 12px;
  }
  .paper-modal {
    max-height: calc(100vh - 24px);
    padding: 16px;
  }
  .modal-head {
    flex-direction: column;
  }
  .actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  .grid {
    grid-template-columns: 1fr;
  }
  .item {
    grid-template-columns: 1fr;
  }
  .actions .btn {
    flex: 1 1 160px;
  }
}
</style>
