<script lang="ts" setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useI18n } from '@/i18n'
import { useChatStore } from '@/stores/chatStore'
import { useToastStore } from '@/stores/toastStore'
import { AlibApi } from '@/api/useAlibApi'
import { copyToClipboard } from '@/utils/copyToClipboard'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import CustomScrollbar from '@/components/CustomScrollbar.vue'

const props = defineProps<{
  cancelToken?: number
}>()

const { t } = useI18n()
const router = useRouter()
const chatStore = useChatStore()
const toastStore = useToastStore()
const { history: chats, activeChatId } = storeToRefs(chatStore)

const openHistoryMenuId = ref<number | null>(null)
const isDeleteDialogOpen = ref(false)
const deleteCandidateId = ref<number | null>(null)
const editingChatId = ref<number | null>(null)
const editTitle = ref('')
const editInputRef = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

function getEditInput() {
  const input = editInputRef.value
  if (Array.isArray(input)) {
    return input[0] ?? null
  }
  return input ?? null
}

function getChatById(chatId: number) {
  return chats.value.find((item) => item.id === chatId)
}

function selectChat(id: number) {
  cancelInlineRename()
  chatStore.setActiveChat(id)
  router.push('/')
}

function toggleHistoryMenu(chatId: number) {
  openHistoryMenuId.value = openHistoryMenuId.value === chatId ? null : chatId
}

function closeHistoryMenu() {
  openHistoryMenuId.value = null
}

function handleOutsideClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (!target) return
  if (target.closest('[data-history-menu]')) return
  closeHistoryMenu()
}

async function handleShareChat(chatId: number) {
  const chat = getChatById(chatId)
  if (!chat || typeof window === 'undefined') return
  const route = router.resolve({ path: '/', query: { chat: chatId } })
  const { origin } = window.location
  let url = route.href
  try {
    url = new URL(route.href, origin).toString()
  } catch {
    url = `${origin}${route.href}`
  }
  const copied = await copyToClipboard(url)
  closeHistoryMenu()
  toastStore.show(copied ? t('history.copyOk') : t('history.copyFail'), {
    variant: copied ? 'success' : 'error',
  })
}

function startInlineRename(chatId: number) {
  const chat = getChatById(chatId)
  if (!chat) return
  editingChatId.value = chatId
  editTitle.value = chat.title
  closeHistoryMenu()
  nextTick(() => {
    const input = getEditInput()
    input?.focus()
    input?.select()
  })
}

function cancelInlineRename() {
  editingChatId.value = null
  editTitle.value = ''
}

async function submitInlineRename(chatId: number) {
  const chat = getChatById(chatId)
  if (!chat) {
    cancelInlineRename()
    return
  }
  const trimmed = editTitle.value.trim()
  if (!trimmed) {
    toastStore.show(t('history.renameValidation'), { variant: 'error' })
    nextTick(() => {
      const input = getEditInput()
      input?.focus()
      input?.select()
    })
    return
  }
  try {
    const updated = await AlibApi.update_chat(chatId, trimmed)
    chatStore.upsertChatFromApi(updated)
    cancelInlineRename()
  } catch (error) {
    toastStore.show((error as { message?: string })?.message || t('chat.error.failed'), {
      variant: 'error',
    })
    nextTick(() => {
      const input = getEditInput()
      input?.focus()
      input?.select()
    })
  }
}

function handleRenameBlur(chatId: number) {
  if (editingChatId.value !== chatId) return
  submitInlineRename(chatId)
}

function requestDeleteChat(chatId: number) {
  const chat = getChatById(chatId)
  if (!chat) return
  deleteCandidateId.value = chatId
  isDeleteDialogOpen.value = true
  closeHistoryMenu()
}

function handleDeleteCancel() {
  isDeleteDialogOpen.value = false
  deleteCandidateId.value = null
}

async function handleDeleteConfirm() {
  const chatId = deleteCandidateId.value
  if (!chatId) {
    isDeleteDialogOpen.value = false
    return
  }
  try {
    await AlibApi.delete_chat(chatId)
    const wasActive = activeChatId.value === chatId
    const deleted = chatStore.deleteChat(chatId)
    deleteCandidateId.value = null
    isDeleteDialogOpen.value = false
    if (!deleted) return
    if (wasActive) {
      router.push('/')
    }
  } catch (error) {
    toastStore.show((error as { message?: string })?.message || t('chat.error.failed'), {
      variant: 'error',
    })
    isDeleteDialogOpen.value = false
    deleteCandidateId.value = null
  }
}

watch(
  () => props.cancelToken,
  () => {
    cancelInlineRename()
    closeHistoryMenu()
  },
)

onMounted(() => {
  document.addEventListener('click', handleOutsideClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleOutsideClick)
})
</script>

<template>
  <div class="menu history">
    <label for="menu" class="label">{{ t('nav.history') }}</label>
    <CustomScrollbar
      bottom-padding="72px"
      track-bottom="72px"
      content-gap="4px"
      content-padding-right="8px"
      class="history-scrollbar"
    >
      <template v-if="chats.length">
        <div
          class="history-elem"
          v-for="chat in chats"
          :key="chat.id"
          :class="{
            active: chat.id === activeChatId,
            'menu-open': openHistoryMenuId === chat.id,
          }"
          data-history-menu
        >
          <form
            v-if="editingChatId === chat.id"
            class="history-edit"
            @submit.prevent="submitInlineRename(chat.id)"
          >
            <input
              ref="editInputRef"
              v-model="editTitle"
              type="text"
              class="history-edit-input"
              :placeholder="t('history.renamePrompt')"
              @blur="handleRenameBlur(chat.id)"
              @keydown.esc.prevent="cancelInlineRename"
            />
          </form>
          <button v-else class="btn-history btn" type="button" @click="selectChat(chat.id)">
            <span class="history-title">{{ chat.title }}</span>
          </button>
          <button
            class="btn-icon btn-history btn"
            type="button"
            @click.stop="toggleHistoryMenu(chat.id)"
            :aria-expanded="openHistoryMenuId === chat.id"
            aria-haspopup="menu"
            :aria-label="t('history.menu.more')"
          >
            &ctdot;
          </button>
          <ul v-if="openHistoryMenuId === chat.id" class="history-menu" role="menu" @click.stop>
            <li role="none">
              <button
                type="button"
                class="history-menu-item"
                role="menuitem"
                @click="handleShareChat(chat.id)"
              >
                {{ t('history.menu.share') }}
              </button>
            </li>
            <li role="none">
              <button
                type="button"
                class="history-menu-item"
                role="menuitem"
                @click="startInlineRename(chat.id)"
              >
                {{ t('history.menu.rename') }}
              </button>
            </li>
            <li role="none">
              <button
                type="button"
                class="history-menu-item destructive"
                role="menuitem"
                @click="requestDeleteChat(chat.id)"
              >
                {{ t('history.menu.delete') }}
              </button>
            </li>
          </ul>
        </div>
      </template>
      <p v-else class="placeholder">{{ t('nav.noChats') }}</p>
    </CustomScrollbar>
    <ConfirmDialog
      v-model="isDeleteDialogOpen"
      :title="t('history.deletePromptTitle')"
      :message="t('history.deleteConfirm')"
      :confirm-text="t('common.delete')"
      :cancel-text="t('common.cancel')"
      @confirm="handleDeleteConfirm"
      @cancel="handleDeleteCancel"
    />
  </div>
</template>

<style lang="css" scoped>
.menu {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.menu.history {
  flex: 1 1 auto;
  align-items: stretch;
  min-height: 0;
  overflow: hidden;
}

.label {
  align-self: flex-start;
  margin-bottom: 10px;
  font-size: medium;
  padding-left: 16px;
  color: var(--color-text-secondary);
}

.history-scrollbar {
  flex: 1 1 auto;
  min-height: 0;
}

.history-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-color: transparent;
}

.history-elem {
  position: relative;
  display: flex;
  justify-content: space-between;
  flex-direction: row;
  align-items: stretch;
  gap: 0;
  border-color: transparent;
  margin-right: 5px;
  z-index: 0;

  width: 100%;
  min-width: 0;
  appearance: none;
  border: 1px solid var(--color-bg-secondary);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    border-color var(--transition-base),
    transform var(--transition-fast);
}

.history-elem:hover {
  border-color: var(--color-border);
}

.history-elem.active {
  transform: translateY(1px);
  border-color: var(--color-primary-secondary);
}

.history-elem:active {
  transform: translateY(2px);
}

.history-elem.menu-open {
  z-index: 50;
}

.history-actions {
  position: relative;
  display: inline-flex;
  align-items: stretch;
  border-radius: var(--radius-md);
  border: 0px;
}

.history-edit {
  appearance: none;
  margin: 0px;
  padding: 0px;
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
  border-top-left-radius: var(--radius-md);
  border-bottom-left-radius: var(--radius-md);
}

.history-edit-input {
  appearance: none;
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
  border-top-left-radius: var(--radius-md);
  border-bottom-left-radius: var(--radius-md);
  cursor: text;
  height: 100%;
  border: 0px;
  width: 100%;
  text-align: left;
  font-size: medium;
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0.55rem 0.9rem;
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 6%);
}

.history-edit-input:focus-visible {
  outline: none;
}

.history-edit-input::placeholder {
  color: var(--color-text-secondary);
}

.history-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  display: flex;
  flex-direction: column;
  min-width: 160px;
  padding: 4px 0;
  margin: 0;
  list-style: none;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-dropdown, 0 8px 16px rgba(15, 23, 42, 0.15));
  z-index: 100;
}

.history-menu-item {
  width: 100%;
  padding: 0.45rem 0.9rem;
  background: transparent;
  border: none;
  color: var(--color-text);
  text-align: left;
  font-size: 0.85rem;
  line-height: 1.3;
  cursor: pointer;
  transition:
    background var(--transition-base),
    color var(--transition-base);
}

.history-menu-item:hover,
.history-menu-item:focus-visible {
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 6%);
  outline: none;
}

.history-menu-item.destructive {
  color: var(--color-danger, #d14343);
}

.history-menu-item.destructive:hover,
.history-menu-item.destructive:focus-visible {
  background: color-mix(in oklab, var(--color-surface), var(--color-danger, #d14343) 12%);
  color: var(--color-danger, #d14343);
}

.history-elem .btn-history:first-child {
  border-top-right-radius: 0px;
  border-bottom-right-radius: 0px;
}

.history-elem .btn-history:nth-child(2) {
  border-top-left-radius: 0px;
  border-bottom-left-radius: 0px;
}

.history-elem .btn-history:nth-child(2):hover {
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 5%);
}

.history-elem .btn-icon,
.history-elem .btn-history,
.history-elem .btn {
  border: 0px !important;
}

.history-elem .btn-icon:active,
.history-elem .btn-history:active,
.history-elem .btn:active {
  transform: translateY(0px) !important;
}

.btn.btn-icon {
  width: 40px;
  height: 40px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-bg-secondary);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  border-radius: var(--radius-md);
  line-height: 1;
}

.btn-history {
  text-align: left;
  font-size: medium;
  width: 100%;
  min-width: 0;
  appearance: none;
  border: 1px solid var(--color-bg-secondary);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0.55rem 0.9rem;
  border-radius: var(--radius-md);
  cursor: pointer;
}

.history-title {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item .history-title {
  font-size: 0.95rem;
  line-height: 1.2;
  color: inherit;
}

.history-item .history-meta {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.history-item.active {
  border-color: var(--color-primary-secondary);
}

.history-item.active .history-meta {
  color: var(--color-primary-secondary);
}

.placeholder {
  margin: 0;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  padding: 0 16px;
  text-align: center;
}
</style>
