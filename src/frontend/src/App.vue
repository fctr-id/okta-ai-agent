<template>
  <v-app>
    <v-main class="app-main">
      <router-view v-slot="{ Component, route }">
        <div class="route-stage">
          <transition name="page-swap" mode="out-in">
            <div :key="route.name || route.path" class="route-layer">
              <component :is="Component" />
            </div>
          </transition>
        </div>
      </router-view>
    </v-main>
  </v-app>
</template>

<script setup>
import { onMounted } from 'vue'

onMounted(() => {
  // Preload key assets
  const images = ['/src/assets/fctr-logo.png']
  images.forEach(src => {
    const img = new Image()
    img.src = src
  })
})
</script>

<style>
/* Global styles */
html,
body {
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden;
}

.app-main {
  min-height: 100dvh;
  background: var(--bg-page, #fbfbfa);
}

.route-stage {
  position: relative;
  min-height: 100dvh;
  isolation: isolate;
}

.route-layer {
  min-height: 100dvh;
  width: 100%;
  will-change: opacity, transform, filter;
}

/* Search container - converted from SCSS to CSS variables */
.search-container {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: 0 24px;
}

/* App-level route swaps */
.page-swap-enter-active,
.page-swap-leave-active {
  transition:
    opacity 0.34s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.42s cubic-bezier(0.22, 1, 0.36, 1),
    filter 0.42s cubic-bezier(0.22, 1, 0.36, 1);
}

.page-swap-enter-from {
  opacity: 0;
  transform: translateY(14px) scale(0.992);
  filter: blur(10px);
}

.page-swap-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(1.004);
  filter: blur(4px);
}

/* Alternative fade transition if needed for specific components */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Subtle scale transition (alternative option) */
.scale-enter-active,
.scale-leave-active {
  transition: opacity 0.3s ease, transform 0.5s ease;
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
  right: 0;
}

.scale-enter-from {
  opacity: 0;
  transform: scale(0.98);
}

.scale-leave-to {
  opacity: 0;
  transform: scale(1.02);
}

/* For mobile devices */
@media (max-width: 768px) {

  .page-swap-enter-active,
  .page-swap-leave-active {
    transition-duration: 0.24s;
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-swap-enter-active,
  .page-swap-leave-active {
    transition: opacity 0.18s ease;
  }

  .page-swap-enter-from,
  .page-swap-leave-to {
    transform: none;
    filter: none;
  }
}
</style>