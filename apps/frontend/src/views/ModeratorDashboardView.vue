<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import UpTab from '@/components/UpTab.vue'
import LeftTab from '@/components/LeftTab.vue'
import { useI18n } from '@/i18n'
import { useLayoutInset } from '@/composables/useLayoutInset'
import { AlibApi } from '@/api/useAlibApi'
import type {
  ModerateSubmissionRequest,
  SubmissionRecord,
  SubmissionStatus,
  SubmissionUpsertRequest,
} from '@/api/types'

type LinkRef = { id: string }

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
const items = reactive<ModerationItem[]>([])
const loaded = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const statusFilter = ref<'all' | SubmissionStatus>('pending')
const { LeftTabHidden: leftHidden, layoutInset } = useLayoutInset()

function toLinkRefs(values: string[] | undefined): LinkRef[] {
  return (values ?? []).map((value) => ({ id: value }))
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

const visibleItems = computed(() =>
  statusFilter.value === 'all' ? items : items.filter((item) => item.status === statusFilter.value),
)

function formatDate(value?: string) {
  if (!value) return '--'
  try {
    return new Intl.DateTimeFormat(undefined, {
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

async function loadItems() {
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await AlibApi.listModerationSubmissions({
      statuses: statusFilter.value === 'all' ? undefined : [statusFilter.value],
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

function startEdit(item: ModerationItem) {
  item.editing = true
}

function cancelEdit(item: ModerationItem) {
  item.editing = false
  item.form = createForm(item)
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
    const response = await AlibApi.updateModerationSubmission(
      item.submission_id,
      buildUpsertRequest(item),
    )
    replaceItem(response.submission)
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
  } catch (e: any) {
    errorMsg.value = e?.message || t('mod.errModerate')
  } finally {
    item.saving = false
  }
}
</script>

<template>
  <UpTab :show-menu="false" :show-upload="false" />
  <LeftTab />

  <div class="area" :class="{ collapsed: leftHidden }" :style="{ '--layout-inset': layoutInset }">
    <div class="container">
      <div class="toolbar">
        <div>
          <h2>{{ t('mod.title') }}</h2>
          <p class="muted">{{ t('mod.queueHint') }}</p>
        </div>
        <div class="toolbar-actions">
          <select v-model="statusFilter" @change="loadItems">
            <option value="all">{{ t('papers.filter.all') }}</option>
            <option value="pending">{{ t('papers.status.pending') }}</option>
            <option value="approved">{{ t('papers.status.approved') }}</option>
            <option value="rejected">{{ t('papers.status.rejected') }}</option>
          </select>
          <button class="btn" type="button" @click="loadItems" :disabled="loading">
            {{ t('common.refresh') }}
          </button>
        </div>
      </div>

      <p class="err" v-if="errorMsg">{{ errorMsg }}</p>
      <p class="muted" v-else-if="loading">{{ t('common.loading') }}</p>

      <div class="list" v-if="visibleItems.length">
        <div class="card" v-for="it in visibleItems" :key="it.submission_id">
          <div class="row head">
            <div class="meta">
              <h3>{{ it.title || t('chat.untitled') }}</h3>
              <div class="sub">
                {{ t('mod.meta.author') }}: {{ it.created_by_user_id }} -
                {{ t('papers.updatedAt') }}: {{ formatDate(it.updated_at) }}
              </div>
            </div>
            <div class="actions">
              <span class="status" :class="statusTone(it.status)">
                {{ t(`papers.status.${it.status}`) }}
              </span>
              <button
                class="btn"
                type="button"
                v-if="it.status === 'pending' && !it.editing"
                @click="startEdit(it)"
              >
                {{ t('common.edit') }}
              </button>
            </div>
          </div>

          <div class="body" v-if="!it.editing">
            <p>{{ it.abstract || t('chat.noAbstract') }}</p>
            <p class="muted" v-if="it.best_oa_location">{{ it.best_oa_location }}</p>
            <p class="muted" v-if="it.moderation_comment">
              {{ t('papers.moderatorComment') }}: {{ it.moderation_comment }}
            </p>
          </div>

          <div class="editor" v-else>
            <label>
              <span>{{ t('paperAdd.title') }}</span>
              <input type="text" v-model="it.form.title" />
            </label>
            <label>
              <span>{{ t('paperAdd.abstract') }}</span>
              <textarea rows="4" v-model="it.form.abstract"></textarea>
            </label>
            <div class="row split">
              <label>
                <span>{{ t('paperAdd.year') }}</span>
                <input type="number" v-model="it.form.year" min="1900" max="2100" />
              </label>
              <label>
                <span>{{ t('paperAdd.pdfSource') }}</span>
                <input type="text" v-model="it.form.best_oa_location" />
              </label>
            </div>

            <section class="links">
              <div class="row">
                <strong>{{ t('paperAdd.related') }}</strong>
                <button class="btn" type="button" @click="addRelated(it)">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="link-list" v-if="it.form.related_works.length">
                <div
                  class="link-item"
                  v-for="(link, index) in it.form.related_works"
                  :key="`rel-${index}`"
                >
                  <input type="text" v-model="link.id" />
                  <button class="btn" type="button" @click="removeRelated(it, index)">
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>

            <section class="links">
              <div class="row">
                <strong>{{ t('paperAdd.referenced') }}</strong>
                <button class="btn" type="button" @click="addReferenced(it)">
                  {{ t('common.add') }}
                </button>
              </div>
              <div class="link-list" v-if="it.form.referenced_works.length">
                <div
                  class="link-item"
                  v-for="(link, index) in it.form.referenced_works"
                  :key="`ref-${index}`"
                >
                  <input type="text" v-model="link.id" />
                  <button class="btn" type="button" @click="removeReferenced(it, index)">
                    {{ t('common.remove') }}
                  </button>
                </div>
              </div>
            </section>

            <div class="actions">
              <button class="btn" type="button" @click="cancelEdit(it)">
                {{ t('common.cancel') }}
              </button>
              <button class="btn primary" type="button" @click="saveEdit(it)" :disabled="it.saving">
                {{ t('common.save') }}
              </button>
            </div>
          </div>

          <div class="moderation-actions" v-if="it.status === 'pending'">
            <label class="comment-box">
              <span>{{ t('papers.moderatorComment') }}</span>
              <textarea rows="3" v-model="it.draftComment"></textarea>
            </label>
            <div class="actions">
              <button
                class="btn success"
                type="button"
                :disabled="it.saving"
                @click="moderate(it, 'approve')"
              >
                {{ t('mod.action.approve') }}
              </button>
              <button
                class="btn danger"
                type="button"
                :disabled="it.saving"
                @click="moderate(it, 'reject')"
              >
                {{ t('mod.action.reject') }}
              </button>
            </div>
          </div>
        </div>
      </div>
      <p v-else-if="loaded" class="muted">{{ t('mod.noItems') }}</p>
    </div>
  </div>
</template>

<style scoped>
.area {
  position: fixed;
  inset: var(--layout-inset, 60px 20px 20px 310px);
  transition: all var(--transition-slow) ease;
  overflow-y: auto;
}
.area.collapsed {
  --layout-inset: 60px 20px 20px 80px;
}
.container {
  max-width: 1000px;
  margin: auto;
  display: grid;
  gap: var(--space-4);
}
.toolbar {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: center;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
}
.muted {
  color: var(--color-muted);
  margin: 0;
}
.err {
  color: var(--color-danger);
  margin: 0;
}
.list {
  display: grid;
  gap: var(--space-3);
}
.card {
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: var(--space-3);
  display: grid;
  gap: var(--space-3);
}
.row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.head .meta h3 {
  margin: 0;
}
.sub {
  color: var(--color-muted);
  font-size: 0.9rem;
}
.body p {
  margin: 0;
}
.editor {
  display: grid;
  gap: var(--space-3);
}
.split {
  align-items: flex-start;
}
.links {
  display: grid;
  gap: var(--space-2);
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
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  color: var(--color-text);
}
.actions {
  display: inline-flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}
.moderation-actions {
  display: grid;
  gap: var(--space-2);
}
.comment-box {
  width: 100%;
}
.btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  padding: 6px 12px;
  border-radius: 6px;
}
.btn.primary {
  background: var(--color-primary-secondary);
  border-color: var(--color-primary-secondary);
  color: #fff;
}
.btn.success {
  background: var(--color-success);
  border-color: var(--color-success);
  color: #fff;
}
.btn.danger {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: #fff;
}
select {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
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

@media (max-width: 1024px) {
  .area,
  .area.collapsed {
    position: static;
    inset: auto;
    margin: calc(60px + var(--space-3)) var(--space-3) var(--space-4);
  }
}

@media (max-width: 768px) {
  .row {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
  }
  .toolbar-actions,
  .actions {
    width: 100%;
    justify-content: flex-start;
  }
  .link-item {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .area,
  .area.collapsed {
    margin: calc(60px + var(--space-2)) var(--space-2) var(--space-3);
  }
  .card {
    padding: var(--space-2);
  }
}
</style>
