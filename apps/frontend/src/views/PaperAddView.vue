<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useI18n } from '@/i18n'
import { usePaperStore } from '@/stores/paperStore'

type Related = { id: string }
type Referenced = { id: string }

const props = withDefaults(
  defineProps<{
    open: boolean
    importMode?: boolean
  }>(),
  {
    importMode: false,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: [id: string]
  submitted: [id: string]
}>()

const form = reactive({
  source_identifier: '',
  title: '',
  abstract: '',
  year: new Date().getFullYear(),
  best_oa_location: '',
  related_paper: [] as Related[],
  referenced_paper: [] as Referenced[],
})

const saving = ref(false)
const successMsg = ref('')
const errorMsg = ref('')
const currentSubmissionId = ref<string | null>(null)
const { t } = useI18n()
const paperStore = usePaperStore()

watch(
  () => props.open,
  (open) => {
    if (open) resetForm()
  },
)

function resetForm() {
  form.source_identifier = ''
  form.title = ''
  form.abstract = ''
  form.year = new Date().getFullYear()
  form.best_oa_location = ''
  form.related_paper = []
  form.referenced_paper = []
  currentSubmissionId.value = null
  successMsg.value = ''
  errorMsg.value = ''
}

function closeModal() {
  if (saving.value) return
  emit('update:open', false)
}

function addRelated() {
  form.related_paper.push({ id: '' })
}
function removeRelated(i: number) {
  form.related_paper.splice(i, 1)
}
function addReferenced() {
  form.referenced_paper.push({ id: '' })
}
function removeReferenced(i: number) {
  form.referenced_paper.splice(i, 1)
}

function buildPayload() {
  return {
    id: currentSubmissionId.value || undefined,
    source_identifier: form.source_identifier.trim() || undefined,
    title: form.title.trim() || undefined,
    abstract: form.abstract.trim() || undefined,
    year: Number(form.year) || undefined,
    best_oa_location: form.best_oa_location.trim() || undefined,
    related_paper: form.related_paper.filter((r) => r.id.trim()).map((r) => ({ id: r.id.trim() })),
    referenced_paper: form.referenced_paper
      .filter((r) => r.id.trim())
      .map((r) => ({ id: r.id.trim() })),
  }
}

async function saveDraft() {
  successMsg.value = ''
  errorMsg.value = ''
  try {
    saving.value = true
    const isNewDraft = !currentSubmissionId.value
    const submission = await paperStore.saveDraft(buildPayload())
    currentSubmissionId.value = submission.id
    if (isNewDraft) {
      emit('saved', submission.id)
    }
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
  if (!form.title.trim()) {
    errorMsg.value = t('paperAdd.errNoTitle')
    return
  }
  try {
    saving.value = true
    const submission = await paperStore.submitPaper(buildPayload())
    currentSubmissionId.value = submission.id
    successMsg.value = t('paperAdd.okSubmitted')
    emit('submitted', submission.id)
    emit('update:open', false)
  } catch (e: any) {
    errorMsg.value = e?.message || t('paperAdd.errSubmit')
  } finally {
    saving.value = false
  }
}
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="closeModal">
      <section class="paper-modal" role="dialog" aria-modal="true" :aria-label="t('paperAdd.header')">
        <header class="modal-head">
          <div>
            <p v-if="importMode" class="modal-eyebrow">{{ t('papers.action.importIdentifier') }}</p>
            <h2>{{ t('paperAdd.header') }}</h2>
            <p>{{ t('paperAdd.subtitle') }}</p>
          </div>
          <button class="icon-button" type="button" :aria-label="t('common.cancel')" @click="closeModal">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </header>

      <form class="form" @submit.prevent="submitForReview">
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
          <input type="text" v-model="form.title" :placeholder="t('paperAdd.placeholderTitle')" />
        </label>
        <label>
          <span>{{ t('paperAdd.abstract') }}</span>
          <textarea v-model="form.abstract" rows="5" :placeholder="t('paperAdd.placeholderAbstract')"></textarea>
        </label>
        <div class="grid">
          <label>
            <span>{{ t('paperAdd.year') }}</span>
            <input type="number" v-model="form.year" min="1900" max="2100" />
          </label>
          <label>
            <span>{{ t('paperAdd.pdfSource') }}</span>
            <input type="text" v-model="form.best_oa_location" :placeholder="t('paperAdd.placeholderUrl')" />
          </label>
        </div>

        <div class="subsection">
          <div class="row">
            <h3>{{ t('paperAdd.related') }}</h3>
            <button type="button" class="btn" @click="addRelated">{{ t('common.add') }}</button>
          </div>
          <div class="list" v-if="form.related_paper.length">
            <div class="item" v-for="(r, i) in form.related_paper" :key="i">
              <input type="text" v-model="r.id" placeholder="Paper ID" />
              <button type="button" class="btn" @click="removeRelated(i)">
                {{ t('common.remove') }}
              </button>
            </div>
          </div>
        </div>

        <div class="subsection">
          <div class="row">
            <h3>{{ t('paperAdd.referenced') }}</h3>
            <button type="button" class="btn" @click="addReferenced">{{ t('common.add') }}</button>
          </div>
          <div class="list" v-if="form.referenced_paper.length">
            <div class="item" v-for="(r, i) in form.referenced_paper" :key="i">
              <input type="text" v-model="r.id" placeholder="Paper ID" />
              <button type="button" class="btn" @click="removeReferenced(i)">
                {{ t('common.remove') }}
              </button>
            </div>
          </div>
        </div>

        <div class="feedback">
          <span class="ok" v-if="successMsg">{{ successMsg }}</span>
          <span class="err" v-else-if="errorMsg">{{ errorMsg }}</span>
        </div>

        <div class="actions">
          <button class="btn" type="button" :disabled="saving" @click="closeModal">
            {{ t('common.cancel') }}
          </button>
          <button class="btn" type="button" :disabled="saving" @click="saveDraft">
            {{ saving ? t('common.loading') : t('common.save') }}
          </button>
          <button class="btn primary" type="submit" :disabled="saving">
            {{ saving ? t('common.submitting') : t('common.submit') }}
          </button>
        </div>
      </form>
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
  width: min(840px, 100%);
  max-height: min(820px, calc(100vh - 48px));
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
}
.modal-head p {
  margin: 8px 0 0;
  color: var(--color-muted);
  line-height: 1.45;
}
.modal-eyebrow {
  margin: 0 0 6px !important;
  color: var(--color-primary-secondary) !important;
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
.form {
  display: grid;
  gap: var(--space-4);
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
  grid-template-columns: 1fr 1fr;
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
}
.btn.primary {
  background: var(--color-primary-secondary);
  border-color: var(--color-primary-secondary);
  color: #fff;
}

@media (max-width: 768px) {
  .modal-backdrop {
    padding: 12px;
  }
  .paper-modal {
    max-height: calc(100vh - 24px);
    padding: 16px;
  }
  .grid,
  .item {
    grid-template-columns: 1fr;
  }
  .actions {
    flex-direction: column-reverse;
  }
  .btn {
    width: 100%;
  }
}
</style>
