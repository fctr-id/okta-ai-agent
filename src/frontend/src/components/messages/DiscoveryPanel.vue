<template>
  <div class="thinking-glass">
    <!-- Minimal Header -->
    <button class="glass-header" @click="isExpanded = !isExpanded">
      <svg 
        class="chevron" 
        :class="{ expanded: isExpanded }" 
        width="14" height="14" 
        viewBox="0 0 24 24" 
        fill="none" 
        stroke="currentColor" 
        stroke-width="2.5"
      >
        <path d="M9 18l6-6-6-6"/>
      </svg>
      <span class="header-text">Thinking</span>
      
      <div class="header-spacer"></div>
      
      <!-- Status badges - right aligned -->
      <span v-if="isThinking && steps.length === 0" class="status-badge processing">
        <span class="badge-dots"><span></span><span></span><span></span></span>
        PROCESSING
      </span>
      <span v-else-if="!isComplete && !error && steps.length > 0" class="status-badge processing">
        <span class="badge-pulse"></span>
        PROCESSING
      </span>
      <span v-if="isComplete && !error" class="status-badge completed">COMPLETED</span>
      <span v-if="error" class="status-badge error">ERROR</span>
    </button>

    <!-- Content -->
    <transition name="slide">
      <div v-show="isExpanded" class="glass-content">
        <!-- Loading shimmer -->
        <div v-if="isThinking && steps.length === 0" class="loading-shimmer">
          <div class="shimmer-bar"></div>
          <div class="shimmer-bar short"></div>
        </div>

        <!-- Steps -->
        <div v-else-if="steps.length > 0" class="steps-list">
          <div 
            v-for="(step, index) in steps" 
            :key="step.id || index" 
            class="step-item"
            :class="{ 
              current: index === steps.length - 1 && !isComplete && !error,
              error: step.status === 'failed'
            }"
          >
            <p class="step-text">
              {{ step.reasoning || step.text || step.title }}
              <span 
                v-if="index === steps.length - 1 && !isComplete && !error && !executionStarted" 
                class="typing-cursor"
              ></span>
            </p>
            
            <!-- Tool calls - modern 2026 animated chips -->
            <div v-if="step.tools && step.tools.length > 0" class="tool-chips">
              <template v-for="(tool, i) in step.tools" :key="i">
                <!-- Chevron separator between sequential tools -->
                <span v-if="i > 0" class="tool-separator">›</span>
                <div 
                  class="tool-chip"
                  :class="{ 
                    active: !isComplete && index === steps.length - 1 && i === step.tools.length - 1,
                    done: isComplete || index < steps.length - 1 || i < step.tools.length - 1
                  }"
                >
                  <!-- Spinning sun when active, checkmark when done -->
                  <svg v-if="!isComplete && index === steps.length - 1 && i === step.tools.length - 1" class="tool-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
                  </svg>
                  <svg v-else class="tool-icon done" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  <span class="tool-label">{{ tool.description || formatToolName(tool.name) }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- Error -->
        <div v-if="error" class="error-msg">{{ error }}</div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

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

watch([() => props.isThinking, () => props.isComplete], ([thinking, complete]) => {
  if (thinking || (props.steps.length > 0 && !complete)) {
    isExpanded.value = true
  } else if (complete) {
    isExpanded.value = false
  }
})

const formatToolName = (name) => {
  return name.replace(/_/g, ' ').replace(/^okta /, '')
}
</script>

<style scoped>
/* Frosted glass container */
.thinking-glass {
  margin: 1.5rem auto;
  max-width: 900px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

/* Header - more white */
.glass-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 14px 20px;
  background: rgba(255, 255, 255, 0.85);
  border: none;
  cursor: pointer;
  transition: background 0.2s ease;
}

.glass-header:hover {
  background: rgba(255, 255, 255, 0.95);
}

.chevron {
  color: #666;
  transition: transform 0.25s ease;
  flex-shrink: 0;
}

.chevron.expanded {
  transform: rotate(90deg);
}

.header-text {
  font-size: 13px;
  font-weight: 600;
  color: #333;
  letter-spacing: -0.01em;
}

.header-spacer {
  flex: 1;
}

/* Status badges - right aligned with backgrounds */
.status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 4px 10px;
  border-radius: 6px;
}

.status-badge.processing {
  background: rgba(76, 100, 226, 0.12);
  color: #4C64E2;
}

.status-badge.completed {
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
}

.status-badge.error {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.badge-dots {
  display: flex;
  gap: 2px;
}

.badge-dots span {
  width: 4px;
  height: 4px;
  background: currentColor;
  border-radius: 50%;
  animation: fade-pulse 1.4s ease-in-out infinite;
}

.badge-dots span:nth-child(2) { animation-delay: 0.2s; }
.badge-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes fade-pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.badge-pulse {
  width: 6px;
  height: 6px;
  background: currentColor;
  border-radius: 50%;
  animation: soft-pulse 2s ease-in-out infinite;
}

@keyframes soft-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Content */
.glass-content {
  padding: 16px 20px;
}

/* Shimmer loading */
.loading-shimmer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shimmer-bar {
  height: 12px;
  background: linear-gradient(90deg, 
    rgba(0,0,0,0.04) 0%, 
    rgba(0,0,0,0.08) 50%, 
    rgba(0,0,0,0.04) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
  width: 80%;
}

.shimmer-bar.short {
  width: 50%;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Steps list */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-item {
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 12px;
  transition: all 0.2s ease;
}

.step-item.current {
  background: rgba(255, 255, 255, 0.95);
}

.step-item.error {
  background: rgba(229, 57, 53, 0.08);
}

.step-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #444;
  font-weight: 450;
}

.step-item.current .step-text {
  color: #222;
}

.step-item.error .step-text {
  color: #c62828;
}

/* Typing cursor */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: #4C64E2;
  margin-left: 4px;
  vertical-align: middle;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Tool chips - 2026 modern style */
.tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: rgba(76, 100, 226, 0.08);
  border-radius: 100px;
  font-size: 11px;
  color: #5a6acf;
  font-weight: 500;
  transition: all 0.2s ease;
}

.tool-chip:hover {
  background: rgba(76, 100, 226, 0.14);
}

.tool-chip.active {
  background: rgba(76, 100, 226, 0.12);
  box-shadow: 0 0 0 1px rgba(76, 100, 226, 0.2);
}

.tool-chip.active .tool-icon {
  animation: spin-slow 3s linear infinite;
}

/* Done state - subtle purple */
.tool-chip.done {
  background: rgba(142, 84, 233, 0.08);
  color: #9b7ed4;
}

.tool-chip.done:hover {
  background: rgba(142, 84, 233, 0.12);
}

.tool-icon.done {
  color: #a98eda;
}

/* Chevron separator between sequential tools */
.tool-separator {
  color: #c4b5d8;
  font-size: 14px;
  font-weight: 300;
  margin: 0 2px;
  opacity: 0.7;
}

@keyframes spin-slow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.tool-icon {
  flex-shrink: 0;
  opacity: 0.8;
}

.tool-label {
  white-space: nowrap;
}

/* Error message */
.error-msg {
  padding: 12px 16px;
  background: rgba(229, 57, 53, 0.1);
  color: #c62828;
  border-radius: 12px;
  font-size: 12px;
  margin-top: 8px;
}

/* Slide transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.slide-enter-to,
.slide-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>
