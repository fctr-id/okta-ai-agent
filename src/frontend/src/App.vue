<template>
  <v-app>
    <v-main>
      <!-- Fixed structure: router-view outside, transition inside -->
      <router-view v-slot="{ Component, route }">
        <transition name="smooth" mode="out-in">
          <component :is="Component" :key="route.name || route.path" />
        </transition>
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

/* Search container - converted from SCSS to CSS variables */
.search-container {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: 0 24px;
}

/* Smoother transitions that don't cause scrollbar issues */
.smooth-enter-active,
.smooth-leave-active {
  transition: opacity 0.50s ease;
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
  right: 0;
}

.smooth-enter-from,
.smooth-leave-to {
  opacity: 0;
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

  .smooth-enter-active,
  .smooth-leave-active {
    transition-duration: 0.25s;
  }
}
</style>