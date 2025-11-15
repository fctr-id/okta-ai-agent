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

// Detect ReAct mode from URL parameter
const urlParams = new URLSearchParams(window.location.search)
const isReActMode = urlParams.get('mode') === 'react'

// ChatInterfaceV2 handles ReAct mode internally based on ?mode=react URL parameter
// ReAct mode takes precedence over realtime mode
const currentChatComponent = computed(() => {
  // If ?mode=react is set, always use ChatInterfaceV2 (it will activate ReAct mode internally)
  if (isReActMode) {
    console.log('🚀 [ChatContainer] Loading ChatInterfaceV2 with ReAct mode')
    return ChatInterfaceV2
  }
  // Otherwise, check isRealtimeMode for Tako Modern vs Tako Legacy
  else if (isRealtimeMode.value) {
    console.log('🤖 [ChatContainer] Loading RealtimeChatInterface (Tako Modern Execution)')
    return RealtimeChatInterface
  } else {
    console.log('📊 [ChatContainer] Loading ChatInterfaceV2 (Tako Legacy mode)')
    return ChatInterfaceV2
  }
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