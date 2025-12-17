<template>
  <div class="chat-container">
    <!-- Dynamically render chat interface based on mode -->
    <transition name="fade" mode="out-in">
      <component :is="currentChatComponent" />
    </transition>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import ChatInterfaceV2 from '@/components/ChatInterfaceV2.vue'
import RealtimeChatInterface from '@/components/views/RealtimeChatInterface.vue'

// ChatInterfaceV2 handles ReAct mode internally
// We default to ChatInterfaceV2 unless mode=realtime is explicitly requested
const currentChatComponent = computed(() => {
  const urlParams = new URLSearchParams(window.location.search)
  const modeParam = urlParams.get('mode')
  
  // Only load RealtimeChatInterface if explicitly requested
  if (modeParam === 'realtime') {
    return RealtimeChatInterface
  }
  
  // Default to ChatInterfaceV2 (which defaults to ReAct mode)
  return ChatInterfaceV2
})
</script>

<style scoped>
.chat-container {
  position: relative;
  height: 100%;
  width: 100%;
}

/* Use the fade transition defined in App.vue */
</style>