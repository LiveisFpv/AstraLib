<script lang="ts" setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    bottomPadding?: string
    trackBottom?: string
    contentGap?: string
    contentPaddingRight?: string
    thumbWidth?: string
    minThumbHeight?: number
    maxThumbHeight?: number
  }>(),
  {
    bottomPadding: '0px',
    trackBottom: undefined,
    contentGap: '0px',
    contentPaddingRight: '8px',
    thumbWidth: '4px',
    minThumbHeight: 24,
    maxThumbHeight: 64,
  },
)

const scrollViewportRef = ref<HTMLElement | null>(null)
const scrollContentRef = ref<HTMLElement | null>(null)
const scrollbarTrackRef = ref<HTMLElement | null>(null)
const isScrollable = ref(false)
const isDragging = ref(false)
const thumbHeight = ref(0)
const thumbTop = ref(0)

let dragStartY = 0
let dragStartScrollTop = 0
let resizeObserver: ResizeObserver | null = null
let mutationObserver: MutationObserver | null = null

const styleVars = computed(() => ({
  '--custom-scrollbar-bottom-padding': props.bottomPadding,
  '--custom-scrollbar-track-bottom': props.trackBottom ?? props.bottomPadding,
  '--custom-scrollbar-content-gap': props.contentGap,
  '--custom-scrollbar-content-padding-right': props.contentPaddingRight,
  '--custom-scrollbar-thumb-width': props.thumbWidth,
}))

function updateScrollbar() {
  const viewport = scrollViewportRef.value
  if (!viewport) return

  const maxScrollTop = viewport.scrollHeight - viewport.clientHeight
  isScrollable.value = maxScrollTop > 1
  if (!isScrollable.value) {
    thumbHeight.value = 0
    thumbTop.value = 0
    return
  }

  const trackHeight = scrollbarTrackRef.value?.clientHeight || viewport.clientHeight
  const nextThumbHeight = Math.min(
    props.maxThumbHeight,
    Math.max(
      props.minThumbHeight,
      Math.round((viewport.clientHeight / viewport.scrollHeight) * trackHeight),
    ),
  )
  const maxThumbTop = trackHeight - nextThumbHeight
  thumbHeight.value = nextThumbHeight
  thumbTop.value = Math.round((viewport.scrollTop / maxScrollTop) * maxThumbTop)
}

function handlePointerMove(event: PointerEvent) {
  const viewport = scrollViewportRef.value
  const track = scrollbarTrackRef.value
  if (!viewport || !track) return

  const maxScrollTop = viewport.scrollHeight - viewport.clientHeight
  const maxThumbTop = track.clientHeight - thumbHeight.value
  if (maxScrollTop <= 0 || maxThumbTop <= 0) return

  const deltaY = event.clientY - dragStartY
  viewport.scrollTop = dragStartScrollTop + (deltaY / maxThumbTop) * maxScrollTop
  updateScrollbar()
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('pointermove', handlePointerMove)
  document.removeEventListener('pointerup', stopDrag)
  document.removeEventListener('pointercancel', stopDrag)
}

function startDrag(event: PointerEvent) {
  const viewport = scrollViewportRef.value
  if (!viewport) return

  event.preventDefault()
  isDragging.value = true
  dragStartY = event.clientY
  dragStartScrollTop = viewport.scrollTop
  document.addEventListener('pointermove', handlePointerMove)
  document.addEventListener('pointerup', stopDrag)
  document.addEventListener('pointercancel', stopDrag)
}

onMounted(() => {
  window.addEventListener('resize', updateScrollbar)

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateScrollbar)
    if (scrollViewportRef.value) resizeObserver.observe(scrollViewportRef.value)
    if (scrollContentRef.value) resizeObserver.observe(scrollContentRef.value)
  }

  if (typeof MutationObserver !== 'undefined' && scrollContentRef.value) {
    mutationObserver = new MutationObserver(updateScrollbar)
    mutationObserver.observe(scrollContentRef.value, {
      childList: true,
      subtree: true,
      characterData: true,
    })
  }

  nextTick(updateScrollbar)
})

onBeforeUnmount(() => {
  stopDrag()
  window.removeEventListener('resize', updateScrollbar)
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
})
</script>

<template>
  <div class="custom-scrollbar" :class="{ dragging: isDragging }" :style="styleVars">
    <div ref="scrollViewportRef" class="custom-scrollbar-viewport" @scroll="updateScrollbar">
      <div ref="scrollContentRef" class="custom-scrollbar-content">
        <slot />
      </div>
    </div>
    <div
      v-show="isScrollable"
      ref="scrollbarTrackRef"
      class="custom-scrollbar-track"
      aria-hidden="true"
    >
      <span
        class="custom-scrollbar-thumb"
        :style="{
          height: `${thumbHeight}px`,
          transform: `translateY(${thumbTop}px)`,
        }"
        @pointerdown="startDrag"
      ></span>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.custom-scrollbar-viewport {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.custom-scrollbar-viewport::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.custom-scrollbar-content {
  display: flex;
  flex-direction: column;
  gap: var(--custom-scrollbar-content-gap);
  min-height: min-content;
  padding-right: var(--custom-scrollbar-content-padding-right);
  padding-bottom: var(--custom-scrollbar-bottom-padding);
}

.custom-scrollbar-track {
  position: absolute;
  top: 0;
  right: 1px;
  bottom: var(--custom-scrollbar-track-bottom);
  width: var(--custom-scrollbar-thumb-width);
  opacity: 0;
  pointer-events: auto;
  transition: opacity var(--transition-fast) ease;
}

.custom-scrollbar:hover .custom-scrollbar-track,
.custom-scrollbar:focus-within .custom-scrollbar-track,
.custom-scrollbar.dragging .custom-scrollbar-track {
  opacity: 1;
}

.custom-scrollbar-thumb {
  display: block;
  width: 100%;
  border-radius: 999px;
  background: var(--scrollbar-thumb);
  touch-action: none;
  user-select: none;
}

.custom-scrollbar.dragging .custom-scrollbar-thumb {
  background: var(--scrollbar-thumb-hover);
}
</style>
