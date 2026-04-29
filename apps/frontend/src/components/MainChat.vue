<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useSettingStore } from '@/stores/settingStore'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore, type PaperCard } from '@/stores/chatStore'
import { useToastStore } from '@/stores/toastStore'
import { AlibApi } from '@/api/useAlibApi'
import type { ChatPaperResponse} from '@/api/types'
import { useI18n } from '@/i18n'
import { copyToClipboard } from '@/utils/copyToClipboard'
import CustomScrollbar from '@/components/CustomScrollbar.vue'

type CustomScrollbarExpose = {
  getViewport: () => HTMLElement | null
  scrollTo: (options: ScrollToOptions) => void
  updateScrollbar: () => void
}

const useSetting = useSettingStore()
const auth = useAuthStore()
const chatStore = useChatStore()
const toastStore = useToastStore()
const { t } = useI18n()

const query = ref('')
const loading = ref(false)
const errorMsg = ref('')
const isChatsLoading = ref(false)

const selectedMessageId = ref<string | null>(null)
const selectedPaperKey = ref<string | null>(null)
const logRef = ref<CustomScrollbarExpose | null>(null)
const endSpacerRef = ref<HTMLElement | null>(null)
const previewAbstractExpanded = ref(false)
const endSpacerHeight = ref(0)
let layoutResizeObserver: ResizeObserver | null = null
let observedLogViewport: HTMLElement | null = null

const messages = computed(() => chatStore.activeChat?.messages ?? [])
const hasMessages = computed(() => messages.value.length > 0)
const searchBlocked = computed(() =>
  Boolean((auth as any).isAdmin?.value || (auth as any).isModerator?.value),
)

const activeMessage = computed(() => {
  if (!selectedMessageId.value) return null
  return messages.value.find((item) => item.id === selectedMessageId.value) ?? null
})

const activePaper = computed(() => {
  const message = activeMessage.value
  if (!message || !selectedPaperKey.value) return null
  return message.results.find((paper) => paper.key === selectedPaperKey.value) ?? null
})

const activePaperMeta = computed(() => {
  const paper = activePaper.value
  if (!paper) return []
  const items: Array<{ label: string; value: string | number }> = []
  if (paper.authors.length) {
    items.push({ label: t('chat.preview.authors'), value: paper.authors.join(', ') })
  }
  if (paper.year) items.push({ label: t('chat.preview.year'), value: paper.year })
  if (paper.sourceName) items.push({ label: t('chat.preview.source'), value: paper.sourceName })
  if (paper.institutions.length) {
    items.push({
      label: t('chat.preview.institutions'),
      value: paper.institutions.slice(0, 3).join(', '),
    })
  }
  if (typeof paper.citedByCount === 'number' && paper.citedByCount > 0) {
    items.push({ label: t('chat.preview.citations'), value: paper.citedByCount })
  }
  if (paper.referencedWorks.length) {
    items.push({ label: t('chat.preview.references'), value: paper.referencedWorks.length })
  }
  if (paper.relatedWorks.length) {
    items.push({ label: t('chat.preview.related'), value: paper.relatedWorks.length })
  }
  const primaryIdentifier =
    paper.identifiers.find((item) => item.type?.toLowerCase() === 'doi') ??
    paper.identifiers.find((item) => item.value)
  if (primaryIdentifier?.value) {
    const label = primaryIdentifier.type?.toUpperCase() || t('chat.preview.identifier')
    items.push({ label, value: primaryIdentifier.value })
  } else if (paper.id && !paper.sourceName) {
    items.push({ label: t('chat.preview.identifier'), value: paper.id })
  }
  return items
})

const canTogglePreviewAbstract = computed(() => (activePaper.value?.abstract.length ?? 0) > 520)

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
})

function formatTime(ts: number) {
  return timeFormatter.format(new Date(ts))
}

function getLogViewport() {
  return logRef.value?.getViewport() ?? null
}

function getSelectedTurn() {
  const log = getLogViewport()
  const selectedId = selectedMessageId.value
  if (!log || !selectedId) return null
  return (
    Array.from(log.querySelectorAll<HTMLElement>('[data-chat-turn]')).find(
      (item) => item.dataset.messageId === selectedId,
    ) ?? null
  )
}

function getTurnScrollTop(log: HTMLElement, turn: HTMLElement) {
  const logRect = log.getBoundingClientRect()
  const turnRect = turn.getBoundingClientRect()
  return log.scrollTop + turnRect.top - logRect.top
}

function scrollSelectedTurnIntoView() {
  const log = getLogViewport()
  const turn = getSelectedTurn()
  if (!log || !turn) return
  logRef.value?.scrollTo({
    top: getTurnScrollTop(log, turn),
    behavior: 'auto',
  })
}

function updateEndSpacerHeight() {
  const log = getLogViewport()
  const turn = getSelectedTurn()
  if (!log || !turn) {
    endSpacerHeight.value = 0
    return
  }
  const currentSpacerHeight = endSpacerRef.value?.offsetHeight ?? 0
  const naturalScrollHeight = log.scrollHeight - currentSpacerHeight
  const requiredScrollHeight = getTurnScrollTop(log, turn) + log.clientHeight
  const requiredSpace = requiredScrollHeight - naturalScrollHeight
  endSpacerHeight.value = Math.max(0, Math.ceil(requiredSpace))
}

async function alignSelectedTurn() {
  await nextTick()
  updateEndSpacerHeight()
  await nextTick()
  scrollSelectedTurnIntoView()
  logRef.value?.updateScrollbar()
}

function observeLogViewport() {
  if (!layoutResizeObserver) return
  const viewport = getLogViewport()
  if (observedLogViewport === viewport) return
  if (observedLogViewport) {
    layoutResizeObserver.unobserve(observedLogViewport)
  }
  observedLogViewport = viewport
  if (observedLogViewport) {
    layoutResizeObserver.observe(observedLogViewport)
  }
}

function toTimestamp(value?: string | number | null) {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0
  }
  if (typeof value === 'string' && value) {
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

function normalizeBestLocation(raw: unknown): Record<string, any> | null {
  if (!raw) return null
  if (typeof raw === 'object') {
    return raw as Record<string, any>
  }
  if (typeof raw === 'string') {
    try {
      const prepared = raw
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\bNone\b/g, 'null')
      return JSON.parse(prepared)
    } catch {
      try {
        return JSON.parse(raw)
      } catch {
        return null
      }
    }
  }
  return null
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
}

const CHAT_TITLE_MAX = 60

function buildChatTitle(raw: string) {
  const normalized = raw.replace(/\s+/g, ' ').trim()
  if (!normalized) return 'New search'
  if (normalized.length <= CHAT_TITLE_MAX) return normalized
  return `${normalized.slice(0, CHAT_TITLE_MAX).trimEnd()}...`
}

function toPaperCard(paper: ChatPaperResponse, index: number): PaperCard | null {
  const title = paper.title?.trim()
  const abstract = paper.abstract?.trim()
  if (!title && !abstract) return null
  const best = normalizeBestLocation(paper.best_oa_location)
  return {
    key: `${paper.id || title || 'paper'}-${index}`,
    id: paper.id,
    title: title || t('chat.untitled'),
    abstract: abstract || t('chat.noAbstract'),
    year: paper.year,
    pdfUrl: best?.pdf_url,
    landingUrl: best?.landing_page_url || paper.best_oa_location, // Надо что-то подумать
    isOpenAccess: best?.is_oa || paper.best_oa_location != '',
    sourceName: best?.source?.display_name,
    authors: normalizeStringArray(paper.authors),
    institutions: normalizeStringArray(paper.institutions),
    identifiers: paper.identifiers ?? [],
    referencedWorks: normalizeStringArray(paper.referenced_works),
    relatedWorks: normalizeStringArray(paper.related_works),
    citedByCount: paper.cited_by_count,
    score: paper.score
  }
}

async function ensureActiveChat(searchText: string) {
  if (chatStore.activeChatId) return chatStore.activeChatId
  const title = buildChatTitle(searchText)
  const created = await AlibApi.create_chat(title)
  const chat = chatStore.upsertChatFromApi(created)
  return chat.id
}

async function runSearch(text?: string) {
  const searchText = (text ?? query.value).trim()
  errorMsg.value = ''
  if (searchBlocked.value) {
    errorMsg.value = t('chat.blockedNote')
    return
  }
  if (!searchText) {
    errorMsg.value = t('chat.error.enterQuery')
    return
  }
  query.value = searchText
  loading.value = true
  try {
    const chatId = await ensureActiveChat(searchText)
    const response = await AlibApi.search(searchText, chatId)
    const mapped = (response.papers ?? [])
      .map((paper, index) => toPaperCard(paper, index))
      .filter((item): item is PaperCard => !!item)
    const message = chatStore.addMessage(chatId, response.search_query, mapped, response.created_at)
    if (!message) {
      throw new Error(t('chat.error.failed'))
    }
    if (!mapped.length) {
      errorMsg.value = t('chat.error.noResults')
    }
    selectedMessageId.value = message.id
    selectedPaperKey.value = mapped[0]?.key ?? null
    await alignSelectedTurn()
  } catch (error: any) {
    errorMsg.value = error?.message || t('chat.error.failed')
  } finally {
    loading.value = false
  }
}

function onSubmit() {
  runSearch()
}

function selectPaper(messageId: string, paperKey: string) {
  selectedMessageId.value = messageId
  selectedPaperKey.value = paperKey
  previewAbstractExpanded.value = false
  void alignSelectedTurn()
}

function buildCitation(paper: PaperCard) {
  const authors = paper.authors.length ? `${paper.authors.join(', ')}. ` : ''
  const details = [paper.sourceName, paper.year].filter(Boolean).join(', ')
  return details ? `${authors}${paper.title}. ${details}.` : `${authors}${paper.title}.`
}

async function copyCitation() {
  const paper = activePaper.value
  if (!paper) return
  const copied = await copyToClipboard(buildCitation(paper))
  toastStore.show(copied ? t('chat.citation.copyOk') : t('chat.citation.copyFail'), {
    variant: copied ? 'success' : 'error',
  })
}

async function loadChats() {
  if (!auth.isAuthenticated || isChatsLoading.value) return
  isChatsLoading.value = true
  try {
    const response = await AlibApi.get_all_user_chats()
    chatStore.setChatsFromApi(response.chats ?? [])
  } catch (error) {
    // leave chat list empty on load failure
  } finally {
    isChatsLoading.value = false
  }
}

let historyRequestId = 0
async function loadChatHistory(chatId: number) {
  const chat = chatStore.activeChat
  if (!chat || chat.historyLoaded) return
  const reqId = ++historyRequestId
  try {
    const response = await AlibApi.get_chat_history(chatId)
    if (reqId !== historyRequestId) return
    const mappedMessages = (response.chat_messages ?? []).map((message, msgIndex) => {
      const createdAt = toTimestamp(message.created_at)
      const updatedAt = toTimestamp(message.updated_at || message.created_at)
      const results = (message.papers ?? [])
        .map((paper, index) => toPaperCard(paper, index))
        .filter((item): item is PaperCard => !!item)
      return {
        id: `${chatId}-${createdAt || msgIndex}-${msgIndex}`,
        query: message.search_query?.trim() || '',
        createdAt,
        updatedAt,
        results,
      }
    })
    chatStore.setMessages(chatId, mappedMessages)
  } catch (error) {
    chatStore.markHistoryLoaded(chatId)
  }
}

onMounted(() => {
  if (auth.isAuthenticated) {
    loadChats()
  }
  if (typeof ResizeObserver !== 'undefined') {
    layoutResizeObserver = new ResizeObserver(() => {
      void alignSelectedTurn()
    })
    nextTick(observeLogViewport)
  }
})

watch(
  logRef,
  async () => {
    await nextTick()
    observeLogViewport()
  },
  { flush: 'post' },
)

watch(
  () => auth.isAuthenticated,
  (isAuthed) => {
    if (isAuthed) {
      loadChats()
    } else {
      chatStore.reset()
    }
  },
)

watch(
  () => chatStore.activeChatId,
  async (chatId) => {
    if (!chatId) {
      selectedMessageId.value = null
      selectedPaperKey.value = null
      previewAbstractExpanded.value = false
      return
    }
    await loadChatHistory(chatId)
    const msgs = chatStore.activeChat?.messages ?? []
    if (msgs.length) {
      const last = msgs[msgs.length - 1]
      selectedMessageId.value = last.id
      selectedPaperKey.value = last.results[0]?.key ?? null
      previewAbstractExpanded.value = false
      await alignSelectedTurn()
    } else {
      selectedMessageId.value = null
      selectedPaperKey.value = null
      previewAbstractExpanded.value = false
    }
  },
  { immediate: true },
)

watch(
  messages,
  async () => {
    await alignSelectedTurn()
  },
  { deep: true },
)

watch(
  previewAbstractExpanded,
  async () => {
    await alignSelectedTurn()
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  layoutResizeObserver?.disconnect()
  observedLogViewport = null
})
</script>
<template>
  <div class="chat" :class="{ collapsed: useSetting.LeftTabHidden }">
    <div class="main-chat" :class="{ collapsed: useSetting.LeftTabHidden }">
      <div class="status" v-if="loading || errorMsg">
        <span v-if="loading" class="status__loading">{{ t('chat.status.searching') }}</span>
        <span v-else class="status__error">{{ errorMsg }}</span>
      </div>

      <CustomScrollbar
        ref="logRef"
        class="chat-log"
        bottom-padding="var(--space-3)"
        track-bottom="var(--space-3)"
        content-gap="var(--space-4)"
        content-padding-right="6px"
        thumb-width="6px"
        :min-thumb-height="28"
        :max-thumb-height="72"
      >
        <template v-if="hasMessages">
          <section
            v-for="message in messages"
            :key="message.id"
            :data-message-id="message.id"
            data-chat-turn
            class="chat-turn"
            :class="{ active: message.id === selectedMessageId }"
          >
            <header class="chat-turn__header">
              <span class="chat-turn__prompt">{{ message.query }}</span>
              <span class="chat-turn__time">{{ formatTime(message.createdAt) }}</span>
            </header>

            <div v-if="message.results.length" class="results-grid">
              <div class="cards">
                <article
                  v-for="paper in message.results"
                  :key="paper.key"
                  :class="[
                    'paper-card',
                    {
                      'paper-card--active':
                        message.id === selectedMessageId && paper.key === selectedPaperKey,
                    },
                  ]"
                  tabindex="0"
                  @click="selectPaper(message.id, paper.key)"
                  @keydown.enter.prevent="selectPaper(message.id, paper.key)"
                  @keydown.space.prevent="selectPaper(message.id, paper.key)"
                >
                  <header class="paper-card__header">
                    <span v-if="paper.year" class="paper-card__year">{{ paper.year }}</span>
                    <span v-if="paper.score" class="paper-card__score">{{t('paper.score').replace('{score}', String(paper.score.toFixed(3)))}}</span>
                    <h3 class="paper-card__title">{{ paper.title }}</h3>
                  </header>
                  <p class="paper-card__abstract">{{ paper.abstract }}</p>
                  <footer class="paper-card__footer">
                    <span v-if="paper.sourceName" class="paper-card__source">{{
                      paper.sourceName
                    }}</span>
                    <span v-if="paper.isOpenAccess" class="paper-card__badge">{{
                      t('chat.openAccess')
                    }}</span>
                  </footer>
                </article>
              </div>

              <aside v-if="message.id === selectedMessageId && activePaper" class="paper-preview">
                <header class="paper-preview__header">
                  <h3>{{ activePaper.title }}</h3>
                  <div v-if="activePaperMeta.length" class="paper-preview__meta">
                    <span
                      v-for="item in activePaperMeta"
                      :key="item.label"
                      class="paper-preview__meta-item"
                    >
                      <span class="paper-preview__meta-label">{{ item.label }}</span>
                      <span class="paper-preview__meta-value">{{ item.value }}</span>
                    </span>
                  </div>
                </header>
                <p
                  class="paper-preview__abstract"
                  :class="{ expanded: previewAbstractExpanded }"
                >
                  {{ activePaper.abstract }}
                </p>
                <button
                  v-if="canTogglePreviewAbstract"
                  type="button"
                  class="paper-preview__toggle"
                  @click="previewAbstractExpanded = !previewAbstractExpanded"
                >
                  {{
                    previewAbstractExpanded
                      ? t('chat.preview.showLess')
                      : t('chat.preview.showMore')
                  }}
                </button>
                <div class="paper-preview__links">
                  <a
                    v-if="activePaper.landingUrl"
                    :href="activePaper.landingUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="btn btn--tiny btn--primary-action"
                  >
                    {{ t('chat.link.openArticle') }}
                  </a>
                  <a
                    v-if="activePaper.pdfUrl"
                    :href="activePaper.pdfUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="btn btn--tiny"
                  >
                    {{ t('chat.link.openPdf') }}
                  </a>
                  <button
                    type="button"
                    class="btn btn--tiny btn--secondary-action"
                    @click="copyCitation"
                  >
                    {{ t('chat.action.copyCitation') }}
                  </button>
                </div>
              </aside>
            </div>

            <p v-else class="no-results">{{ t('chat.noResultsForTurn') }}</p>
          </section>
        </template>
        <div v-else class="empty-state">
          <p>{{ t('chat.empty') }}</p>
        </div>
        <div
          v-if="hasMessages"
          ref="endSpacerRef"
          class="chat-log__end-spacer"
          :style="{ height: `${endSpacerHeight}px` }"
          aria-hidden="true"
        ></div>
      </CustomScrollbar>
    </div>

    <form class="input-area" @submit.prevent="onSubmit">
      <span v-if="searchBlocked" class="blocked-note">{{ t('chat.blockedNote') }}</span>
      <input
        v-model="query"
        type="search"
        :placeholder="t('chat.input.placeholder')"
        :disabled="loading || searchBlocked"
      />
      <button class="btn btn-icon" type="submit" :disabled="loading || searchBlocked">
        {{
          searchBlocked
            ? t('chat.input.blocked')
            : loading
              ? t('chat.input.searching')
              : t('chat.input.search')
        }}
      </button>
    </form>
  </div>
</template>
<style lang="css" scoped>
.chat {
  position: fixed;
  top: 80px;
  left: 310px;
  right: 60px;
  bottom: 20px;
  background:
    linear-gradient(
      180deg,
      color-mix(in oklab, var(--color-panel), var(--color-surface) 4%),
      var(--color-panel)
    );
  border: 1px solid var(--color-border-soft);
  border-radius: 18px;
  padding: var(--space-4);
  display: grid;
  grid-template-rows: 1fr auto;
  gap: var(--space-3);
  box-shadow: var(--shadow-elevated);
  transition: all var(--transition-slow) ease;
}
.chat.collapsed {
  left: 120px;
}

.main-chat {
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: var(--space-3);
  min-height: 0;
  overflow: hidden;
}

.main-header h2 {
  margin: 0;
  font-size: 1.4rem;
}
.main-header p {
  margin: 4px 0 0;
  color: var(--color-muted);
  font-size: 0.95rem;
}

.chat-log {
  position: relative;
  grid-row: 2;
  min-height: 0;
}
.chat-log__end-spacer {
  min-height: 0;
  pointer-events: none;
}
.chat-log:first-child {
  grid-row: 1 / -1;
}

.chat-turn {
  background: var(--color-panel-elevated);
  border-radius: 18px;
  padding: var(--space-4);
  display: grid;
  gap: var(--space-3);
  border: 1px solid var(--color-border-soft);
  box-shadow: var(--shadow-card);
  transition:
    border-color var(--transition-fast) ease,
    box-shadow var(--transition-fast) ease,
    background var(--transition-fast) ease;
}
.chat-turn.active {
  border-color: var(--color-primary-secondary);
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-primary) 4%);
  box-shadow: var(--shadow-elevated);
}
.chat-turn__header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  align-items: baseline;
}
.chat-turn__prompt {
  font-weight: 600;
  font-size: 1.05rem;
}
.chat-turn__time {
  font-size: 0.8rem;
  color: var(--color-muted);
}

.status {
  font-size: 0.95rem;
  min-height: 1.4rem;
}
.status__loading {
  color: var(--color-muted);
}
.status__error {
  color: var(--color-danger);
}

.results-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.9fr);
  gap: var(--space-4);
  align-items: start;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-3);
  align-content: start;
  position: relative;
  z-index: 1;
}

.paper-card {
  position: relative;
  min-width: 240px;
  min-height: 168px;
  background: var(--color-card);
  border-radius: 16px;
  padding: 14px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  box-shadow: var(--shadow-card);
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 32%);
  transition:
    transform var(--transition-fast) ease,
    box-shadow var(--transition-fast) ease,
    border-color var(--transition-fast) ease,
    background var(--transition-fast) ease;
  cursor: pointer;
  outline: none;
}
.paper-card:hover,
.paper-card:focus-visible {
  transform: translateY(-2px);
  box-shadow: var(--shadow-elevated);
  border-color: var(--color-primary-secondary);
  z-index: 2;
}

.paper-card--active {
  background: var(--color-card-active);
  border-color: var(--color-primary-secondary);
  box-shadow: var(--shadow-elevated);
  transform: translateY(-1px);
  z-index: 3;
}

.paper-card__header {
  display: grid;
  gap: 4px;
}
.paper-card__year {
  width: fit-content;
  font-size: 0.75rem;
  color: var(--color-accent-muted);
  text-transform: uppercase;
  letter-spacing: 0;
  font-weight: 700;
}
.paper-card__score {
  width: fit-content;
  font-size: 0.75rem;
  color: var(--color-accent-muted);
  text-transform: uppercase;
  letter-spacing: 0;
  font-weight: 700;
}
.paper-card__title {
  margin: 0;
  font-size: 1.075rem;
  font-weight: 700;
  line-height: 1.28;
}
.paper-card__abstract {
  margin: var(--space-2) 0 var(--space-3);
  color: var(--color-muted);
  font-size: 0.875rem;
  line-height: 1.5;
  display: -webkit-box;
  max-height: none;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.paper-card__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.8rem;
  color: var(--color-muted);
}
.paper-card__source {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.paper-card__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  padding: 0.18rem 0.5rem;
  border: 1px solid var(--color-success-border);
  border-radius: 999px;
  background: var(--color-success-soft);
  color: var(--color-success);
  font-weight: 600;
  line-height: 1.2;
}

.no-results {
  margin: 0;
  color: var(--color-muted);
  font-size: 0.95rem;
}

.paper-preview {
  position: sticky;
  top: var(--space-4);
  min-width: 0;
  max-width: 100%;
  background: var(--color-preview);
  border-radius: 18px;
  padding: var(--space-4);
  box-shadow: var(--shadow-elevated);
  border: 1px solid var(--color-border-soft);
  max-height: calc(100vh - 180px);
  min-height: min(420px, calc(100vh - 180px));
  overflow-y: auto;
  overflow-x: hidden;
  align-self: start;
  backdrop-filter: blur(12px);
}
.paper-preview__header {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
  margin-bottom: var(--space-3);
}
.paper-preview h3 {
  margin: 0;
  font-size: 1.15rem;
  line-height: 1.3;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.paper-preview__abstract {
  margin: 0 0 var(--space-3);
  color: var(--color-text-secondary);
  font-size: 0.94rem;
  line-height: 1.58;
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 8;
}
.paper-preview__abstract.expanded {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 15;
}
.paper-preview__meta {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
  font-size: 0.85rem;
  color: var(--color-muted);
}
.paper-preview__meta-item {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 0.35rem;
  min-width: 0;
  max-width: 100%;
  padding: 0.25rem 0.55rem;
  border: 1px solid color-mix(in oklab, var(--color-border-soft), transparent 26%);
  border-radius: 999px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 22%);
}
.paper-preview__meta-label {
  flex: 0 0 auto;
  color: var(--color-accent-muted);
  font-size: 0.72rem;
  font-weight: 700;
}
.paper-preview__meta-value {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.paper-preview__toggle {
  width: fit-content;
  margin: -0.25rem 0 var(--space-3);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-accent-muted);
  font: inherit;
  font-size: 0.86rem;
  font-weight: 700;
  cursor: pointer;
}
.paper-preview__toggle:hover,
.paper-preview__toggle:focus-visible {
  color: var(--color-primary-secondary);
  text-decoration: underline;
  outline: none;
}
.paper-preview__links {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
}

.btn--tiny {
  font-size: 0.8rem;
  padding: 7px 11px;
  border-radius: 999px;
  border-color: color-mix(in oklab, var(--color-border-soft), transparent 15%);
  background: color-mix(in oklab, var(--color-panel-elevated), var(--color-primary) 7%);
  color: var(--color-text);
}
.btn--primary-action {
  border-color: transparent;
  background: var(--color-primary-secondary);
  color: var(--color-primary-contrast);
}
.btn--secondary-action {
  font: inherit;
  font-size: 0.8rem;
}

.empty-state {
  text-align: center;
  color: var(--color-muted);
  min-height: 45vh;
  display: grid;
  place-items: center;
  padding: var(--space-4) 0;
  border: 1px dashed var(--color-border-soft);
  border-radius: 18px;
  background: color-mix(in oklab, var(--color-panel-elevated), transparent 28%);
}
.empty-state p {
  color: inherit;
  margin: 0;
}

.input-area {
  border: 1px solid var(--color-border-soft);
  border-radius: 20px;
  background-color: var(--color-panel-elevated);
  color: var(--color-text);
  display: flex;
  gap: var(--space-2);
  padding: 10px;
  align-items: center;
  box-shadow: var(--shadow-elevated);
}

.input-area input {
  border: none;
  outline: none;
  background: transparent;
  flex: 1;
  padding: 12px 14px;
  font-size: 1rem;
  color: var(--color-text);
}

.input-area input::placeholder {
  color: color-mix(in oklab, var(--color-muted), transparent 22%);
}

.input-area button {
  min-width: 100px;
  min-height: 40px;
  border-color: transparent;
  background: var(--color-primary-secondary);
  color: var(--color-primary-contrast);
  font-weight: 700;
}
.blocked-note {
  color: var(--color-danger);
  margin-left: 8px;
}

@media (max-width: 1200px) {
  .results-grid {
    grid-template-columns: 1fr;
  }
  .paper-preview {
    position: relative;
    top: auto;
    max-height: none;
    min-height: 0;
    margin-bottom: var(--space-3);
    margin-top: var(--space-3);
  }
}

@media (max-width: 960px) {
  .main-chat {
    grid-template-rows: auto 1fr;
  }
  .results-grid {
    gap: var(--space-3);
  }
  .paper-preview {
    box-shadow: none;
  }
}

@media (max-width: 720px) {
  .chat-turn {
    padding: var(--space-3);
  }
  .chat-turn__header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1, 4px);
  }
  .paper-card {
    min-width: auto;
  }
  .paper-preview__links {
    flex-direction: column;
    align-items: stretch;
  }
  .input-area {
    flex-direction: column;
    align-items: stretch;
    padding: var(--space-2);
  }
  .input-area button {
    width: 100%;
    min-width: 0;
  }
}
</style>
