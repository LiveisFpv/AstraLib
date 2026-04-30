<script setup lang="ts">
import UpTab from '@/components/UpTab.vue'
import LeftTab from '@/components/LeftTab.vue'
import { useI18n } from '@/i18n'
import { useLayoutInset } from '@/composables/useLayoutInset'
const { t } = useI18n()
const { LeftTabHidden: leftHidden } = useLayoutInset()
</script>

<template>
  <UpTab :show-menu="false" :show-upload="false" />
  <LeftTab />
  <main class="search-area" :class="{ collapsed: leftHidden }">
    <h2>{{ t('search.title') }}</h2>
    <p>{{ t('search.placeholder') }}</p>
  </main>
</template>

<style scoped>
.search-area {
  position: fixed;
  top: 80px;
  right: 20px;
  bottom: 20px;
  left: 310px;
  overflow: auto;
  transition: all var(--transition-slow) ease;
}

.search-area.collapsed {
  left: 120px;
}

@media (max-width: 900px) {
  .search-area,
  .search-area.collapsed {
    top: 70px;
    right: 12px;
    bottom: 12px;
    left: 12px;
  }
}
</style>
