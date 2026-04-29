<script lang="ts" setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingStore } from '@/stores/settingStore'
import { useChatStore } from '@/stores/chatStore'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/authStore'
import { useI18n } from '@/i18n'
import ChatHistory from '@/components/ChatHistory.vue'
const authStore = useAuthStore()
const { t } = useI18n()
const router = useRouter()
const settingStore = useSettingStore()
const chatStore = useChatStore()
const { LeftTabHidden } = storeToRefs(settingStore)
const leftTabHidden = LeftTabHidden
const canAuthorAccess = computed(() => !!authStore.User)
const historyCancelToken = ref(0)
function toggleLeftTab() {
  settingStore.HideLeftTab()
}
function RedirecttoSettings() {
  router.push('/settings')
}
function RedirecttoHome() {
  router.push('/')
}
function RedirecttoMyPapers() {
  router.push('/paper/my')
}
function RedirecttoAdmin() {
  router.push('/admin')
}
function RedirecttoModerator() {
  router.push('/moderator')
}

function handleNewSearch() {
  historyCancelToken.value += 1
  chatStore.clearActiveChat()
  router.push('/')
}

const props = defineProps<{
  hidden?: boolean
}>()

const hidden = computed(() => props.hidden)

watch(
  hidden,
  (val) => {
    if (typeof val === 'boolean' && val !== LeftTabHidden.value) {
      LeftTabHidden.value = val
    }
  },
  { immediate: true },
)
</script>
<template>
  <div class="left-tab" :class="{ hidden: leftTabHidden }">
    <div class="header" :class="{ hidden: leftTabHidden }">
      <button class="btn btn-icon" type="button" @click="RedirecttoHome" aria-label="Home">
        <img src="/src/assets/book-logo.svg" alt="L" class="logo brand-logo" />
      </button>
      <button
        class="btn btn-icon sidebar-toggle"
        type="button"
        @click="toggleLeftTab"
        :aria-expanded="!leftTabHidden"
        aria-label="Toggle sidebar"
      >
        <svg class="chevron" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
          <path
            d="M4 2l4 4-4 4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>
    <div class="menu">
      <!-- Author access -->
      <!-- <button class="btn-menu btn" v-if="canAuthorAccess" @click="RedirecttoWriterCabinet">
        <div class="icon-text">
          <img src="/src/assets/papers-icon.svg" alt="|=|" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.addPaper') }}</p>
        </div>
      </button> -->
      <button class="btn-menu btn" v-if="canAuthorAccess" @click="RedirecttoMyPapers">
        <div class="icon-text">
          <img src="/src/assets/papers-icon.svg" alt="|=|" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.myPapers') }}</p>
        </div>
      </button>

      <!-- Moderator access -->
      <button
        class="btn-menu btn"
        v-if="authStore.User && (authStore.isModerator || authStore.isAdmin)"
        @click="RedirecttoModerator"
      >
        <div class="icon-text">
          <img src="/src/assets/papers-icon.svg" alt="M" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.moderation') }}</p>
        </div>
      </button>

      <!-- Admin access -->
      <button
        class="btn-menu btn"
        v-if="authStore.User && authStore.isAdmin"
        @click="RedirecttoAdmin"
      >
        <div class="icon-text">
          <img src="/src/assets/manage-icon.svg" alt="A" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.adminPanel') }}</p>
        </div>
      </button>

      <button class="btn-menu btn" @click="handleNewSearch">
        <div class="icon-text">
          <img src="/src/assets/plus-line-icon.svg" alt="" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.newSearch') }}</p>
        </div>
      </button>
      <button class="btn-menu btn">
        <div class="icon-text">
          <img src="/src/assets/search-icon.svg" alt="" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.searchChats') }}</p>
        </div>
      </button>
    </div>
    <ChatHistory v-if="!leftTabHidden" :cancel-token="historyCancelToken" />
    <div class="footer">
      <button class="btn-menu btn" @click="RedirecttoSettings">
        <div class="icon-text">
          <img src="/src/assets/manage-icon.svg" alt="S" class="logo" />
          <p v-if="!leftTabHidden">{{ t('nav.settings') }}</p>
        </div>
      </button>
    </div>
  </div>
</template>
<style lang="css" scoped>
.left-tab {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 250px;
  height: 100vh;
  background-color: var(--color-bg-secondary);
  border-right: 1px solid var(--color-border);
  border-bottom-right-radius: 25px;
  border-top-right-radius: 25px;
  padding: 15px 5px;
  padding-bottom: 5px;
  overflow: hidden;
  transition: all var(--transition-slow) ease;
}

.left-tab.hidden {
  width: 60px;
  border-bottom-right-radius: 0px;
  border-top-right-radius: 0px;
}

.header {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0px 10px;
  transition: all var(--transition-slow) ease;
}

.header.hidden {
  justify-content: center;
  flex-direction: column;
  padding: 0px 5px;
  gap: 10px;
}

.icon-text {
  display: inline-flex;
  align-items: center;
  gap: 0.5em;
}

.icon-text p {
  margin: 0;
  line-height: 1.2;
}

.icon-text .logo {
  width: 1em;
  height: 1em;
}

.menu {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.btn-menu {
  text-align: left;
  font-size: medium;
  width: 100%;
  appearance: none;
  border: 1px solid var(--color-bg-secondary);
  background: var(--color-bg-secondary);
  color: var(--color-text);
  padding: 0.55rem 0.9rem;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition:
    background var(--transition-base),
    border-color var(--transition-base),
    transform var(--transition-fast);
}
.btn-menu:hover {
  border-color: var(--color-border);
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 3%);
}
.btn-menu:active {
  transform: translateY(1px);
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
.btn.btn-icon:hover {
  border-color: var(--color-border);
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 3%);
}
.btn.btn-icon:active {
  transform: translateY(1px);
}
.btn-icon .logo {
  width: 40px;
  height: 40px;
}
.brand-logo {
  filter: none;
}
.sidebar-toggle .chevron {
  width: 14px;
  height: 14px;
  transition: transform var(--transition-fast) ease;
  transform: rotate(180deg);
}
.left-tab.hidden .sidebar-toggle .chevron {
  transform: rotate(0deg);
}
.footer {
  position: absolute;
  right: 5px;
  bottom: 5px;
  left: 5px;
  display: flex;
  justify-content: center;
  padding: 10px 0;
  background: var(--color-bg-secondary);
  z-index: 100;
}

.footer::before {
  content: '';
  position: absolute;
  right: 0;
  bottom: 100%;
  left: 0;
  height: 54px;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    color-mix(in oklab, var(--color-bg-secondary), transparent 28%) 62%,
    var(--color-bg-secondary) 100%
  );
}
</style>
