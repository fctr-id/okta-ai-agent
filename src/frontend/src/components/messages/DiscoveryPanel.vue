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
      <span class="header-text">Planning & Tools</span>
      
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
  },
  shouldAutoCollapse: {
    type: Boolean,
    default: false
  }
})

const isExpanded = ref(true)

watch(() => props.shouldAutoCollapse, (shouldAutoCollapse) => {
  if (shouldAutoCollapse) {
    isExpanded.value = false
  }
}, { immediate: true })

const formatToolName = (name) => {
  return name.replace(/_/g, ' ').replace(/^okta /, '')
}
</script>

<style scoped>
/* Thinking surface - structured, text-first */
.thinking-glass {
  margin: 1.25rem auto;
  max-width: 900px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid rgba(var(--primary-rgb), 0.16);
  box-shadow: none;
  overflow: hidden;
}

.glass-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 16px;
  background: linear-gradient(180deg, rgba(var(--primary-rgb), 0.14), rgba(var(--primary-rgb), 0.08));
  border: none;
  border-bottom: 1px solid rgba(var(--primary-rgb), 0.16);
  cursor: pointer;
  transition: background 0.15s ease;
}

.glass-header:hover {
  background: linear-gradient(180deg, rgba(var(--primary-rgb), 0.18), rgba(var(--primary-rgb), 0.1));
}

.chevron {
  color: var(--primary-dark);
  transition: transform 0.25s ease;
  flex-shrink: 0;
}

.chevron.expanded {
  transform: rotate(90deg);
}

.header-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0;
}

.header-spacer {
  flex: 1;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.status-badge.processing {
  background: rgba(15, 23, 42, 0.035);
  border-color: rgba(15, 23, 42, 0.08);
  color: var(--text-secondary);
}

.status-badge.completed {
  background: #ffffff;
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.status-badge.error {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.14);
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
  padding: 14px 16px 16px;
}

/* Shimmer loading */
.loading-shimmer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shimmer-bar {
  height: 10px;
  background: linear-gradient(90deg, 
    rgba(15, 23, 42, 0.04) 0%, 
    rgba(15, 23, 42, 0.08) 50%, 
    rgba(15, 23, 42, 0.04) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
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
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.steps-list::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 18px;
  bottom: 18px;
  width: 1px;
  background: rgba(var(--primary-rgb), 0.28);
}

.step-item {
  position: relative;
  padding: 10px 12px 10px 32px;
  background: transparent;
  border: none;
  border-radius: 10px;
  transition: background 0.15s ease, color 0.15s ease;
}

.step-item::before {
  content: '';
  position: absolute;
  left: 11px;
  top: 8px;
  width: 14px;
  height: 12px;
  border-left: 1px solid rgba(var(--primary-rgb), 0.28);
  border-bottom: 1px solid rgba(var(--primary-rgb), 0.28);
}

.step-item.current {
  background: rgba(var(--primary-rgb), 0.05);
}

.step-item.current::before {
  border-left-color: rgba(var(--primary-rgb), 0.62);
  border-bottom-color: rgba(var(--primary-rgb), 0.62);
}

.step-item.error {
  background: rgba(239, 68, 68, 0.05);
}

.step-item.error::before {
  border-left-color: rgba(239, 68, 68, 0.48);
  border-bottom-color: rgba(239, 68, 68, 0.48);
}

.step-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-primary);
  font-weight: 500;
}

.step-item.current .step-text {
  color: var(--text-primary);
}

.step-item.error .step-text {
  color: #b91c1c;
}

/* Typing cursor */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: rgba(15, 23, 42, 0.5);
  margin-left: 4px;
  vertical-align: middle;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Tool chips - structured events, not prose */
.tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
}

.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: #ffffff;
  border: 1px solid rgba(var(--primary-rgb), 0.24);
  border-radius: 8px;
  font-size: 11.5px;
  color: var(--text-primary);
  font-weight: 500;
  transition: all 0.2s ease;
}

.tool-chip:hover {
  border-color: rgba(var(--primary-rgb), 0.38);
}

.tool-chip.active {
  background: rgba(var(--primary-rgb), 0.08);
  border-color: rgba(var(--primary-rgb), 0.48);
  color: var(--primary-dark);
  box-shadow: none;
}

.tool-chip.active .tool-icon {
  animation: spin-slow 3s linear infinite;
}

.tool-chip.done {
  background: rgba(34, 197, 94, 0.04);
  border-color: rgba(34, 197, 94, 0.24);
  color: var(--text-primary);
}

.tool-chip.done:hover {
  border-color: rgba(34, 197, 94, 0.34);
}

.tool-icon.done {
  color: #16a34a;
}

.tool-separator {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 400;
  margin: 0 2px;
  opacity: 0.9;
}

@keyframes spin-slow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.tool-icon {
  flex-shrink: 0;
  opacity: 0.9;
}

.tool-label {
  white-space: nowrap;
}

.error-msg {
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.12);
  color: #b91c1c;
  border-radius: 10px;
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
