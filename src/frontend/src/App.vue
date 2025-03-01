<template>
  <v-app>
    <v-main>
      <router-view />
    </v-main>
  </v-app>
</template>

<script setup>
// Remove the import for ChatInterface since we're using router-view now
</script>

<style>
html, body {
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden
}
</style>