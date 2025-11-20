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
import { isRealtimeMode } from '@/state/chatMode.js'

// ChatInterfaceV2 handles ReAct mode internally
// We default to ChatInterfaceV2 unless mode=realtime is explicitly requested
const currentChatComponent = computed(() => {
  const urlParams = new URLSearchParams(window.location.search)
  const modeParam = urlParams.get('mode')
  
  // Only load RealtimeChatInterface if explicitly requested
  if (modeParam === 'realtime') {
    console.log('🤖 [ChatContainer] Loading RealtimeChatInterface (Explicit Realtime Mode)')
    return RealtimeChatInterface
  }
  
  // Default to ChatInterfaceV2 (which defaults to ReAct mode)
  console.log('🚀 [ChatContainer] Loading ChatInterfaceV2 (Default)')
  return ChatInterfaceV2
})
</script>

<style scoped>
.chat-container {
  position: relative;
  height: 100%;
  width: 100%;
}

.mode-toggle-container {
  position: absolute;
  top: 20px;
  right: 20px;
  z-index: 10;
  background-color: rgba(255, 255, 255, 0.9);
  padding: 6px 12px;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
}

/* Use the fade transition defined in App.vue */
</style>