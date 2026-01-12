<template>
  <div class="chat-container">
    <!-- Always use ChatInterfaceV2 for multi-agent architecture -->
    <transition name="fade" mode="out-in">
      <ChatInterfaceV2 />
    </transition>
  </div>
</template>

<script setup>
import ChatInterfaceV2 from '@/components/ChatInterfaceV2.vue'

// ChatInterfaceV2 handles multi-agent ReAct mode
// Realtime mode has been deprecated in favor of the multi-agent architecture
</script>

<style scoped>
.chat-container {
  position: relative;
  height: 100%;
  width: 100%;
}

/* Use the fade transition defined in App.vue */
</style>