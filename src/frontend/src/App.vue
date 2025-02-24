<template>
  <v-app>
    <v-main>
      <chat-interface />
    </v-main>
  </v-app>
</template>

<script setup>
import ChatInterface from '@/components/ChatInterface.vue'
</script>

<style>
html, body {
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden
}
</style>