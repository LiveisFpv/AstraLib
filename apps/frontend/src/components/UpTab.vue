<script lang="ts" setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useSettingStore } from '@/stores/settingStore'
import { useChatStore } from '@/stores/chatStore'
import { useToastStore } from '@/stores/toastStore'
import { useSettingsModalStore } from '@/stores/settingsModalStore'
import { useI18n } from '@/i18n'
import ToastCenter from '@/components/ToastCenter.vue'
import { copyToClipboard } from '@/utils/copyToClipboard'
const authStore = useAuthStore()
const router = useRouter()
function RedirecttoAuth() {
  router.push('/auth')
}

async function handleLogout() {
  await authStore.logout()
  await router.replace('/auth')
}

const useSetting = useSettingStore()
const { t } = useI18n()
const chatStore = useChatStore()
const toastStore = useToastStore()
const settingsModal = useSettingsModalStore()

const props = defineProps<{
  showUpload?: boolean
  showMenu?: boolean
}>()

const showUpload = computed(() => props.showUpload ?? true)
// const showMenu = computed(() => props.showMenu ?? true)
const avatarUrl = computed(() => authStore.User?.photo || '')
const avatarLetter = computed(() => {
  const user = authStore.User
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email || ''
  const trimmed = name.trim()
  return trimmed ? trimmed[0].toUpperCase() : 'U'
})

const { activeChatId } = storeToRefs(chatStore)

function openMobileSidebar() {
  useSetting.OpenMobileSidebar()
}

async function handleCopyActiveChat() {
  if (typeof window === 'undefined') return
  const chatId = activeChatId.value
  if (!chatId) {
    toastStore.show(t('history.copyNoChat'), { variant: 'error' })
    return
  }
  const route = router.resolve({ path: '/', query: { chat: chatId } })
  const { origin } = window.location
  let url = route.href
  try {
    url = new URL(route.href, origin).toString()
  } catch {
    url = `${origin}${route.href}`
  }
  const copied = await copyToClipboard(url)
  toastStore.show(copied ? t('history.copyOk') : t('history.copyFail'), {
    variant: copied ? 'success' : 'error',
  })
}
</script>
<template>
  <div class="up-tab" :class="{ collapsed: useSetting.LeftTabHidden }">
    <button
      class="btn btn-icon mobile-menu-button"
      type="button"
      :aria-expanded="useSetting.MobileSidebarOpen"
      aria-label="Toggle sidebar"
      @click="openMobileSidebar"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M4 7h16" />
        <path d="M4 12h16" />
        <path d="M4 17h16" />
      </svg>
    </button>
    <img class="logo brand-logo" src="/src/assets/text-logo.svg" alt="Astralib" />
    <div class="button-group">
      <button
        class="btn avatar"
        @click="settingsModal.open('profile')"
        v-if="authStore.isAuthenticated"
        :aria-label="t('profile.title')"
      >
        <img v-if="avatarUrl" :src="avatarUrl" alt="" class="avatar-image" />
        <span v-else>{{ avatarLetter }}</span>
      </button>
      <button
        class="btn btn-icon"
        type="button"
        v-if="showUpload"
        @click="handleCopyActiveChat"
        :aria-label="t('history.menu.share')"
      >
        <img class="logo" src="/src/assets/upload-icon.svg" />
      </button>
      <!-- <button class="btn btn-icon" v-if="showMenu">&ctdot;</button> -->
      <button class="btn btn-icon" @click="RedirecttoAuth" v-if="!authStore.isAuthenticated">
        {{ t('auth.login') }}
      </button>
      <button
        class="btn btn-icon"
        v-if="authStore.isAuthenticated"
        :disabled="authStore.isLoggingOut"
        @click="handleLogout"
      >
        <img class="logo" src="/src/assets/logout-icon.svg" alt="[->" />
      </button>
    </div>
  </div>
  <ToastCenter />
</template>
<style lang="css" scoped>
.up-tab {
  position: fixed;
  display: inline-flex;
  align-items: center;
  top: 0;
  left: 310px;
  right: 0;
  z-index: 50;
  height: 60px;
  background-color: var(--color-panel);
  border-bottom: 1px solid var(--color-border-soft);
  border-left: 1px solid var(--color-border-soft);
  border-bottom-left-radius: 30px;
  padding: 8px 22px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.08);
  transition: all var(--transition-slow) ease;
}
.up-tab.collapsed {
  left: 120px;
}
.mobile-menu-button {
  display: none !important;
}
.btn.btn-icon {
  min-width: 50px;
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
  font-size: medium;
}
.btn.btn-icon:hover {
  border-color: var(--color-border);
  background: color-mix(in oklab, var(--color-surface), var(--color-text) 3%);
}
.btn.btn-icon:active {
  transform: translateY(1px);
}
.btn-icon .logo {
  width: 1.2em;
  height: 1.2em;
}
.btn-icon svg {
  width: 1.2em;
  height: 1.2em;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}
.brand-logo {
  width: auto;
  height: 44px;
  filter: none;
}
.btn.avatar {
  width: 40px;
  height: 40px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-primary-secondary);
  background: var(--color-surface);
  color: var(--color-text);
  border-radius: 50%;
  font-weight: 600;
  font-size: 1em;
  line-height: 1;
}
.btn.avatar .avatar-image {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}
.btn.avatar:hover {
  border-color: var(--color-primary);
  background: color-mix(in oklab, var(--color-surface), var(--color-primary) 5%);
  color: var(--color-primary);
}

.button-group {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.up-tab h3 {
  margin: 0;
  line-height: 1.2;
  color: var(--color-text-primary);
}

@media (max-width: 900px) {
  .up-tab,
  .up-tab.collapsed {
    left: 0;
    right: 0;
    border-left: 0;
    border-bottom-left-radius: 0;
    padding: 8px 12px;
    gap:12px;
  }

  .mobile-menu-button {
    display: inline-flex !important;
    min-width: 40px;
  }

  .brand-logo {
    height: 38px;
  }

  .button-group {
    gap: 6px;
  }

  .btn.btn-icon {
    min-width: 40px;
  }
}
</style>
