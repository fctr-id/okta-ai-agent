<template>
  <div class="exec-wrapper">
    <div class="exec-card">
      <button class="exec-header" @click="isExpanded = !isExpanded">
        <v-icon size="18" :class="{ rotated: isExpanded }">mdi-chevron-right</v-icon>
        <span class="title">Agent reasoning </span>
        <div class="spacer"></div>
        <span class="status-badge" :class="statusClass" :title="error || ''">{{ statusText }}</span>
      </button>

      <transition name="expand">
        <div v-show="isExpanded" class="exec-body">
          <!-- Thinking loader -->
          <div v-if="isThinking && steps.length === 0" class="thinking-state">
            <div class="dots"><span></span><span></span><span></span></div>
          </div>

          <!-- Continuous thinking stream -->
          <div v-if="steps.length > 0" class="thinking-stream">
            <div
              v-for="(step, index) in steps"
              :key="step.id || index"
              class="stream-item"
              :class="step.status"
            >
              <div class="step-line">
                <v-icon class="step-icon" size="13" :color="step.status === 'failed' ? '#C62828' : '#4C64E2'">mdi-assistant</v-icon>
                <span class="stream-text">
                  {{ step.reasoning || step.text || step.title }}
                  <!-- Show spinner inline only on the last/active step (when discovery not complete and execution hasn't started) -->
                  <span v-if="index === steps.length - 1 && !isComplete && !error && !executionStarted" class="step-spinner"></span>
                </span>
              </div>
              
              <!-- Tool lines with tree structure -->
              <div v-if="step.tools && step.tools.length > 0" class="tool-lines">
                <div v-for="(tool, i) in step.tools" :key="i" class="tool-line">
                  <span class="tool-branch">└─</span>
                  <v-icon class="tool-icon" size="11" color="#666">mdi-tools</v-icon>
                  <span class="tool-name">{{ tool.name.replace(/_/g, ' ') }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  },
  isThinking: {
    type: Boolean,
    default: false
  },
  isComplete: {
    type: Boolean,
    default: false
  },
  error: {
    type: String,
    default: null
  },
  executionStarted: {
    type: Boolean,
    default: false
  }
})

const isExpanded = ref(true)

// Auto-expand when processing, collapse when complete
watch([() => props.isThinking, () => props.isComplete], ([thinking, complete]) => {
  if (thinking || (props.steps.length > 0 && !complete)) {
    isExpanded.value = true
  } else if (complete) {
    isExpanded.value = false
  }
})

const statusText = computed(() => {
  if (props.error) return 'Error'
  if (props.isComplete) return 'Complete'
  // Show "Working" while agent works through ReAct loop
  if (props.isThinking || props.steps.length > 0) return 'Working'
  return 'Ready'
})

const statusClass = computed(() => {
  if (props.error) return 'error'
  if (props.isComplete) return 'ok'
  // Only show run state while actively working (not complete)
  if ((props.isThinking || props.steps.length > 0) && !props.isComplete) return 'run'
  return 'idle'
})

const completedCount = computed(() => {
  return props.steps.filter(s => s.status === 'complete').length
})
</script>

<style scoped>
.exec-wrapper {
  margin: 3rem 0;
}

.exec-card {
  background: white;
  border-radius: 12px;
  border: 1px solid rgba(76, 100, 226, 0.15);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  transition: all 0.3s ease;
}

.exec-card:hover {
  box-shadow: 0 6px 24px rgba(76, 100, 226, 0.12);
  border-color: rgba(76, 100, 226, 0.25);
}

.exec-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 14px 20px;
  background: rgba(76, 100, 226, 0.03);
  border: none;
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.exec-header:hover {
  background: rgba(76, 100, 226, 0.06);
}

.exec-header .v-icon {
  color: #4C64E2;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.exec-header .v-icon.rotated {
  transform: rotate(90deg);
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a1a;
  letter-spacing: -0.01em;
}

.status-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.status-badge.idle { background: #e0e0e0; color: #666; }
.status-badge.run { background: #E3F2FD; color: #1976D2; }
.status-badge.ok { background: #E8F5E9; color: #388E3C; }
.status-badge.error { background: #FFEBEE; color: #C62828; }

.spacer {
  flex: 1;
}

.exec-body {
  padding: 20px;
  background: white;
}

.thinking-state {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40px 0;
}

.dots {
  display: flex;
  gap: 8px;
}

.dots span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #4C64E2;
  animation: bounce 1.2s ease-in-out infinite;
}

.dots span:nth-child(2) {
  animation-delay: 0.15s;
}

.dots span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: translateY(0);
  }
  40% {
    transform: translateY(-12px);
  }
}

/* Continuous Thinking Stream */
.thinking-stream {
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  background: white;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

.stream-item {
  margin-bottom: 14px;
  padding: 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(76, 100, 226, 0.02);
  border-radius: 6px;
  transition: all 0.2s ease;
}

.stream-item:last-child {
  margin-bottom: 0;
  padding-bottom: 10px;
  border-bottom: none;
}

.step-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}

.step-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  margin-left: 8px;
  border: 2.5px solid rgba(76, 100, 226, 0.25);
  border-top-color: #4C64E2;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  vertical-align: middle;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.step-icon {
  flex-shrink: 0;
  margin-top: 2px;
  opacity: 0.8;
}

.stream-item.in-progress .step-icon {
  opacity: 1;
}

.stream-text {
  color: #555;
  font-weight: 500;
  line-height: 1.6;
  flex: 1;
  letter-spacing: -0.005em;
}

.stream-item.in-progress .stream-text {
  color: #4C64E2;
  font-weight: 600;
  background: linear-gradient(90deg, rgba(76, 100, 226, 0.08) 0%, rgba(76, 100, 226, 0.03) 100%);
  padding: 4px 10px;
  margin: -4px -10px;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(76, 100, 226, 0.1);
}

.stream-item.failed {
  background: rgba(198, 40, 40, 0.03);
  border-color: rgba(198, 40, 40, 0.1);
}

.stream-item.failed .stream-text {
  color: #C62828;
  font-weight: 600;
}

.dots-header {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: 8px;
}

.dots-header span {
  width: 6px;
  height: 6px;
  background: #4C64E2;
  border-radius: 50%;
  animation: bounce 1.2s ease-in-out infinite;
}

.dots-header span:nth-child(2) {
  animation-delay: 0.15s;
}

.dots-header span:nth-child(3) {
  animation-delay: 0.3s;
}

.loading-spinner-header {
  width: 16px;
  height: 16px;
  margin-right: 8px;
  border: 2px solid rgba(76, 100, 226, 0.2);
  border-top-color: #4C64E2;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Tool tree structure */
.tool-lines {
  margin-top: 6px;
  padding-left: 20px;
  border-left: 2px solid rgba(76, 100, 226, 0.1);
}

.tool-line {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #666;
  line-height: 1.7;
  padding: 1px 0;
}

.tool-branch {
  color: rgba(76, 100, 226, 0.3);
  margin-right: 8px;
  font-family: monospace;
  font-size: 14px;
}

.tool-icon {
  margin-right: 6px;
  flex-shrink: 0;
}

.tool-name {
  color: #4C64E2;
  font-style: italic;
  font-weight: 500;
}

/* Transitions */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 2000px;
}
</style>
