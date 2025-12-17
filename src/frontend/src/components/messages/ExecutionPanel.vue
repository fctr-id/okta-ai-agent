<template>
  <div v-if="validationStep || executionStarted || subprocessProgress.length > 0" class="exec-glass">
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
      <span class="header-text">Running</span>
      
      <div class="header-spacer"></div>
      
      <!-- Result count -->
      <span v-if="isComplete && resultCount > 0" class="result-badge">{{ resultCount.toLocaleString() }} records</span>
      
      <!-- Status badges - right aligned -->
      <span v-if="isExecuting && !isComplete" class="status-badge processing">
        <span class="badge-pulse"></span>
        RUNNING
      </span>
      <span v-if="isComplete && !executionError" class="status-badge completed">COMPLETED</span>
      <span v-if="executionError" class="status-badge error">ERROR</span>
    </button>

    <!-- Content -->
    <transition name="slide">
      <div v-show="isExpanded" class="glass-content">
        <!-- Generated Script -->
        <div v-if="generatedScript" class="script-section">
          <div class="script-toggle" @click="isScriptExpanded = !isScriptExpanded">
            <svg 
              class="chevron small" 
              :class="{ expanded: isScriptExpanded }" 
              width="12" height="12" 
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="currentColor" 
              stroke-width="2"
            >
              <path d="M9 18l6-6-6-6"/>
            </svg>
            <span class="script-title">Generated script</span>
            <span class="script-size">{{ scriptLength }} chars</span>
            <span class="copy-btn" role="button" tabindex="0" @click.stop="copyScript" @keydown.enter.stop="copyScript" :title="showCopied ? 'Copied!' : 'Copy'">
              <svg v-if="!showCopied" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </span>
          </div>
          <div v-show="isScriptExpanded" class="script-code">
            <pre><code>{{ generatedScript }}</code></pre>
          </div>
        </div>

        <!-- Steps -->
        <div class="steps-list">
          <!-- Validation -->
          <div v-if="validationStep" class="step-row" :class="getValidationClass">
            <span class="step-indicator">
              <span v-if="validationStep.status === 'complete'" class="indicator-dot success"></span>
              <span v-else-if="validationStep.status === 'failed'" class="indicator-dot error"></span>
              <span v-else class="indicator-spinner"></span>
            </span>
            <span class="step-label">{{ validationStep.message || 'Validating script...' }}</span>
          </div>

          <!-- Execution -->
          <div v-if="executionStarted" class="step-row" :class="getExecutionClass">
            <span class="step-indicator">
              <span v-if="isComplete && !executionError" class="indicator-dot success"></span>
              <span v-else-if="executionError" class="indicator-dot error"></span>
              <span v-else class="indicator-spinner"></span>
            </span>
            <span class="step-label">
              {{ isComplete ? 'Script executed successfully' : executionError ? 'Execution failed' : executionMessage }}
            </span>
          </div>

          <!-- Progress -->
          <div v-if="isExecuting && !isComplete" class="progress-section">
            <div class="progress-track">
              <div 
                class="progress-fill" 
                :class="{ indeterminate: progressValue === 0 }"
                :style="progressValue > 0 ? { width: progressValue + '%' } : {}"
              ></div>
            </div>
            <span v-if="progressValue > 0" class="progress-pct">{{ progressValue.toFixed(0) }}%</span>
          </div>

          <!-- Subprocess -->
          <div v-if="hasActualSubprocessProgress" class="subprocess-section">
            <div v-for="(progress, index) in subprocessProgress" :key="index" class="subprocess-row">
              <span class="subprocess-indicator">
                <span v-if="progress.success" class="indicator-dot success small"></span>
                <span v-else class="indicator-spinner small"></span>
              </span>
              <span class="subprocess-label">{{ progress.label }}</span>
              <span v-if="progress.message" class="subprocess-note">{{ progress.message }}</span>
            </div>
          </div>

          <!-- Error -->
          <div v-if="executionError" class="error-msg">{{ executionError }}</div>
        </div>

        <!-- Token footer -->
        <div v-if="tokenUsage && tokenUsage.total > 0" class="token-footer">
          {{ tokenUsage.total.toLocaleString() }} tokens
          <span class="token-breakdown">({{ tokenUsage.input.toLocaleString() }} in • {{ tokenUsage.output.toLocaleString() }} out)</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  validationStep: { type: Object, default: null },
  executionStarted: { type: Boolean, default: false },
  isExecuting: { type: Boolean, default: false },
  isComplete: { type: Boolean, default: false },
  executionError: { type: String, default: null },
  executionMessage: { type: String, default: 'Executing script...' },
  progressValue: { type: Number, default: 0 },
  subprocessProgress: { type: Array, default: () => [] },
  resultCount: { type: Number, default: 0 },
  tokenUsage: { type: Object, default: null },
  rateLimitWarning: { type: Number, default: 0 },
  generatedScript: { type: String, default: null }
})

const isExpanded = ref(true)
const isScriptExpanded = ref(false)
const showCopied = ref(false)

// Collapse when complete
watch(() => props.isComplete, (val) => {
  if (val) isExpanded.value = false
})

const scriptLength = computed(() => props.generatedScript?.length || 0)

const copyScript = async () => {
  if (!props.generatedScript) return
  try {
    await navigator.clipboard.writeText(props.generatedScript)
    showCopied.value = true
    setTimeout(() => showCopied.value = false, 2000)
  } catch (err) {
    console.error('Copy failed:', err)
  }
}

const hasActualSubprocessProgress = computed(() => {
  return props.subprocessProgress?.some(item => item.label?.trim().length > 0) || false
})

const getValidationClass = computed(() => {
  if (!props.validationStep) return ''
  if (props.validationStep.status === 'failed') return 'failed'
  if (props.validationStep.status === 'complete') return 'success'
  return 'active'
})

const getExecutionClass = computed(() => {
  if (props.executionError) return 'failed'
  if (props.isComplete) return 'success'
  if (props.isExecuting) return 'active'
  return ''
})
</script>

<style scoped>
/* Frosted glass container */
.exec-glass {
  margin: 0.75rem auto;
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

.chevron.small {
  width: 12px;
  height: 12px;
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

.result-badge {
  font-size: 11px;
  font-weight: 500;
  color: #666;
  padding: 3px 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 20px;
  margin-right: 8px;
}

/* Content */
.glass-content {
  padding: 16px 20px;
}

/* Script section */
.script-section {
  margin-bottom: 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.5);
  overflow: hidden;
}

.script-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: #666;
  transition: background 0.15s ease;
}

.script-toggle:hover {
  background: rgba(255, 255, 255, 0.4);
}

.script-title {
  font-weight: 600;
  color: #444;
}

.script-size {
  color: #888;
  font-size: 11px;
}

.copy-btn {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  color: #666;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.copy-btn:hover {
  opacity: 1;
}

.script-code {
  padding: 14px;
  background: rgba(0, 0, 0, 0.03);
  max-height: 300px;
  overflow-y: auto;
}

.script-code pre {
  margin: 0;
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 11px;
  line-height: 1.6;
  color: #333;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Steps list */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 10px;
  transition: all 0.2s ease;
}

.step-row.active {
  background: rgba(255, 255, 255, 0.95);
}

.step-row.success {
  background: rgba(34, 197, 94, 0.08);
}

.step-row.failed {
  background: rgba(229, 57, 53, 0.08);
}

.step-indicator {
  flex-shrink: 0;
  width: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.indicator-dot.success {
  background: #22c55e;
}

.indicator-dot.error {
  background: #e53935;
}

.indicator-dot.small {
  width: 6px;
  height: 6px;
}

.indicator-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(76, 100, 226, 0.2);
  border-top-color: #4C64E2;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.indicator-spinner.small {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.step-label {
  flex: 1;
  font-size: 13px;
  color: #444;
  font-weight: 450;
}

.step-row.active .step-label {
  color: #222;
}

.step-row.failed .step-label {
  color: #c62828;
}

/* Progress section */
.progress-section {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 10px;
}

.progress-track {
  flex: 1;
  height: 4px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #4C64E2;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.progress-fill.indeterminate {
  width: 30%;
  animation: indeterminate 1.5s ease-in-out infinite;
}

@keyframes indeterminate {
  0% { margin-left: 0; }
  50% { margin-left: 70%; }
  100% { margin-left: 0; }
}

.progress-pct {
  font-size: 11px;
  color: #666;
  font-weight: 500;
  min-width: 32px;
}

/* Subprocess section */
.subprocess-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
  padding-left: 20px;
}

.subprocess-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
}

.subprocess-indicator {
  width: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.subprocess-label {
  color: #555;
}

.subprocess-note {
  color: #999;
  font-style: italic;
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

/* Token footer */
.token-footer {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  font-size: 11px;
  color: #888;
  text-align: center;
}

.token-breakdown {
  color: #aaa;
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
