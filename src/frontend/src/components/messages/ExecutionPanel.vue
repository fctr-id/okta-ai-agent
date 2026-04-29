<template>
  <div v-if="validationStep || executionStarted || subprocessProgress.length > 0" class="exec-glass">
    <!-- Minimal Header -->
    <button class="glass-header" @click="isExpanded = !isExpanded">
      <div class="header-main">
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
      </div>

      <div class="header-badges">
        <!-- Result count -->
        <span v-if="isComplete && resultCount > 0" class="result-badge">{{ resultCount.toLocaleString() }} records</span>

        <!-- Status badges - right aligned -->
        <span v-if="isExecuting && !isComplete" class="status-badge processing">
          <span class="badge-pulse"></span>
          RUNNING
        </span>
        <span v-if="isComplete && !executionError" class="status-badge completed">COMPLETED</span>
        <span v-if="executionError" class="status-badge error">ERROR</span>
      </div>
    </button>

    <!-- Content -->
    <transition name="slide">
      <div v-show="isExpanded" class="glass-content">
        <!-- Generated Script -->
        <div v-if="generatedScript" class="script-section">
          <div class="script-toggle" :class="{ expanded: isScriptExpanded }" @click="isScriptExpanded = !isScriptExpanded">
            <div class="script-summary">
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
            </div>

            <div class="script-actions">
              <span class="script-hint">{{ isScriptExpanded ? 'Hide code' : 'Show code' }}</span>
              <span class="copy-btn" role="button" tabindex="0" @click.stop="copyScript" @keydown.enter.stop="copyScript" :title="showCopied ? 'Copied!' : 'Copy'">
                <svg v-if="!showCopied" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </span>
            </div>
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
/* Execution surface - structured and lined */
.exec-glass {
  margin: 0.75rem auto;
  max-width: 900px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid rgba(var(--primary-rgb), 0.18);
  box-shadow: none;
  overflow: hidden;
}

.glass-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  width: 100%;
  padding: 12px 16px;
  background: linear-gradient(180deg, rgba(var(--primary-rgb), 0.18), rgba(var(--primary-rgb), 0.1));
  border: none;
  border-bottom: 1px solid rgba(var(--primary-rgb), 0.18);
  cursor: pointer;
  transition: background 0.15s ease;
}

.glass-header:hover {
  background: linear-gradient(180deg, rgba(var(--primary-rgb), 0.22), rgba(var(--primary-rgb), 0.12));
}

.chevron {
  color: var(--primary-dark);
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

.header-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.header-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0;
}

.header-badges {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

/* Status badges - right aligned with backgrounds */
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
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.24);
  color: #166534;
}

.status-badge.error {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.14);
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
  color: var(--primary-dark);
  padding: 3px 10px;
  background: rgba(var(--primary-rgb), 0.08);
  border: 1px solid rgba(var(--primary-rgb), 0.16);
  border-radius: 20px;
  margin-right: 8px;
}

/* Content */
.glass-content {
  padding: 0 16px 16px;
}

/* Script section */
.script-section {
  margin-top: 8px;
  margin-bottom: 0;
  border: 1px solid rgba(var(--primary-rgb), 0.14);
  border-radius: 12px;
  background: #ffffff;
  overflow: hidden;
}

.script-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  width: 100%;
  padding: 12px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: var(--primary-dark);
  transition: background 0.15s ease;
}

.script-toggle:hover {
  background: rgba(15, 23, 42, 0.025);
}

.script-toggle.expanded {
  background: rgba(15, 23, 42, 0.035);
}

.script-title {
  font-weight: 600;
  color: var(--text-primary);
}

.script-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.script-size {
  color: var(--primary-dark);
  font-size: 11px;
}

.script-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.script-hint {
  margin-left: auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid rgba(var(--primary-rgb), 0.18);
  color: var(--primary-dark);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.copy-btn {
  margin-left: 0;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  color: var(--primary-dark);
  opacity: 0.6;
  transition: opacity 0.15s;
}

.copy-btn:hover {
  opacity: 1;
}

@media (max-width: 720px) {
  .script-actions {
    width: 100%;
    justify-content: space-between;
    margin-left: 0;
  }

  .header-badges {
    width: 100%;
    justify-content: flex-start;
  }
}

.script-code {
  padding: 0 14px 14px;
  background: transparent;
  border-top: 1px solid rgba(var(--primary-rgb), 0.14);
  max-height: 300px;
  overflow-y: auto;
}

.script-code pre {
  margin: 12px 0 0;
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafafa;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
}

/* Steps list */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.step-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 12px 14px 18px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 10px;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.step-row::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 12px;
  bottom: 12px;
  width: 2px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.28);
}

.step-row.active {
  background: #ffffff;
  border-color: rgba(15, 23, 42, 0.18);
}

.step-row.active::before {
  background: rgba(15, 23, 42, 0.44);
}

.step-row.success {
  background: rgba(34, 197, 94, 0.06);
  border-color: rgba(34, 197, 94, 0.22);
}

.step-row.success::before {
  background: rgba(34, 197, 94, 0.58);
}

.step-row.failed {
  background: #ffffff;
  border-color: rgba(239, 68, 68, 0.12);
}

.step-row.failed::before {
  background: rgba(239, 68, 68, 0.68);
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
  background: #16a34a;
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
  border: 2px solid rgba(15, 23, 42, 0.14);
  border-top-color: rgba(15, 23, 42, 0.55);
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
  color: var(--text-primary);
  font-weight: 500;
}

.step-row.active .step-label {
  color: var(--text-primary);
}

.step-row.failed .step-label {
  color: #b91c1c;
}

.step-row.success .step-label {
  color: #166534;
}

/* Progress section */
.progress-section {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 12px 14px 18px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 10px;
}

.progress-track {
  flex: 1;
  height: 4px;
  background: rgba(15, 23, 42, 0.08);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: rgba(15, 23, 42, 0.56);
  border-radius: 99px;
  box-shadow: none;
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
  color: var(--text-muted);
  font-weight: 500;
  min-width: 32px;
}

/* Subprocess section */
.subprocess-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 12px 2px 18px;
  margin-top: 0;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 10px;
}

.subprocess-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  padding-bottom: 10px;
}

.subprocess-indicator {
  width: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.subprocess-label {
  color: var(--text-secondary);
}

.subprocess-note {
  color: var(--text-muted);
  font-style: italic;
}

/* Error message */
.error-msg {
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.12);
  color: #b91c1c;
  border-radius: 10px;
  font-size: 12px;
  margin-top: 8px;
}

/* Token footer */
.token-footer {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
  text-align: center;
}

.token-breakdown {
  color: var(--text-secondary);
  font-weight: 500;
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
