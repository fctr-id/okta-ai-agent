<template>
  <div v-if="validationStep || executionStarted || subprocessProgress.length > 0" class="exec-glass">
    <!-- Minimal Header -->
    <button type="button" class="glass-header" :aria-expanded="isExpanded" :aria-controls="contentId" @click="isExpanded = !isExpanded">
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
        <span class="header-text">Execution details</span>
      </div>

      <div class="header-badges">
        <!-- Result count -->

        <!-- Status badges - right aligned -->
        <span v-if="isExecuting && !isComplete" class="status-badge processing">
          <span class="badge-pulse"></span>
          Running
        </span>
        <span v-if="isComplete && !executionError" class="status-badge completed">Completed</span>
        <span v-if="executionError" class="status-badge error">Failed</span>
      </div>
    </button>

    <!-- Content -->
    <transition name="slide">
      <div v-show="isExpanded" :id="contentId" class="glass-content">
        <!-- Generated Script -->
        <div v-if="generatedScript" class="script-section">
          <div class="script-toggle" :class="{ expanded: isScriptExpanded }">
            <button type="button" class="script-open" :aria-expanded="isScriptExpanded" @click="isScriptExpanded = !isScriptExpanded">
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
              <span class="script-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-12-2 18" />
                </svg>
                Generated script
              </span>
              <span class="script-size">{{ scriptLength }} chars</span>
            </div>

              <span class="script-hint">{{ isScriptExpanded ? 'Hide code' : 'Show code' }}</span>
            </button>
            <div class="script-actions">
              <button type="button" class="copy-btn" @click="copyScript" :aria-label="showCopied ? 'Script copied' : 'Copy script'" :title="showCopied ? 'Copied!' : 'Copy'">
                <svg v-if="!showCopied" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </button>
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
            <span class="step-label">{{ !showError && validationStep.message === executionError ? 'Validation failed' : validationStep.message || 'Validating script...' }}</span>
          </div>

          <!-- Execution -->
          <div v-if="executionStarted" class="step-row" :class="getExecutionClass">
            <span class="step-indicator">
              <span v-if="isComplete && !executionError" class="indicator-dot success"></span>
              <span v-else-if="executionError" class="indicator-dot error"></span>
              <span v-else class="indicator-spinner"></span>
            </span>
            <span class="step-label">
              {{ executionError ? 'Execution failed' : isComplete ? 'Script executed successfully' : executionMessage }}
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

          <p v-if="rateLimitWarning > 0" class="rate-limit-note">Rate limit reached. Resuming in {{ rateLimitWarning }}s.</p>
          <!-- Error -->
          <div v-if="executionError && showError" class="error-msg">{{ executionError }}</div>
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
import { ref, computed, watch, useId } from 'vue'

const props = defineProps({
  validationStep: { type: Object, default: null },
  executionStarted: { type: Boolean, default: false },
  isExecuting: { type: Boolean, default: false },
  isComplete: { type: Boolean, default: false },
  executionError: { type: String, default: null },
  showError: { type: Boolean, default: true },
  collapseRevision: { type: Number, default: 0 },
  executionMessage: { type: String, default: 'Executing script...' },
  progressValue: { type: Number, default: 0 },
  subprocessProgress: { type: Array, default: () => [] },
  resultCount: { type: Number, default: 0 },
  tokenUsage: { type: Object, default: null },
  rateLimitWarning: { type: Number, default: 0 },
  generatedScript: { type: String, default: null },
  shouldAutoCollapse: { type: Boolean, default: false }
})

const contentId = `execution-${useId()}`
const isExpanded = ref(Boolean(props.executionError) || (!props.isComplete && !props.shouldAutoCollapse))
const isScriptExpanded = ref(false)
watch(() => props.collapseRevision, () => {
  isExpanded.value = false
  isScriptExpanded.value = false
})
const showCopied = ref(false)

watch(() => props.shouldAutoCollapse || props.isComplete, (shouldAutoCollapse) => {
  if (shouldAutoCollapse && !props.executionError) {
    isExpanded.value = false
  }
}, { immediate: true })
watch(() => props.executionError, error => { if (error) isExpanded.value = true })

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
.exec-glass { width: 100%; margin: 0; border: 1px solid var(--workspace-outline, #d6dce5); border-radius: 10px; background: #fff; overflow: hidden; }
.glass-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; padding: 11px 14px; background: #fff; border: 0; color: var(--text-secondary, #61646c); cursor: pointer; }
.glass-header:hover, .script-open:hover { background: #f8f9fa; }
button:focus-visible { outline: 2px solid var(--primary, #4c64e2); outline-offset: -2px; }
.header-main, .header-badges, .script-summary, .script-actions { display: flex; align-items: center; gap: 8px; }
.header-main { min-width: 0; }
.header-text { font-size: 14px; font-weight: 600; color: var(--text-primary, #27272a); }
.header-badges { flex-wrap: wrap; justify-content: flex-end; font-size: 12px; }
.status-badge { padding: 2px 7px; border-radius: 5px; display: inline-flex; align-items: center; gap: 6px; }
.status-badge.completed { padding: 4px 8px; border-radius: 6px; font-size: 12px; line-height: 1.3; color: #24694b; background: #e2f3e9; }
.status-badge.completed::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.status-badge.error { color: #b42318; }
.chevron { flex-shrink: 0; transition: transform .15s; }
.chevron.expanded { transform: rotate(90deg); }
.glass-content { margin: 0; padding: 4px 16px 14px; border-top: 1px solid var(--workspace-outline, #d6dce5); }
.script-section { margin-bottom: 8px; }
.script-toggle { display: flex; align-items: center; gap: 8px; }
.script-open { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 8px; flex: 1; padding: 10px 0; border: 0; background: transparent; cursor: pointer; font-size: 13px; color: var(--text-secondary, #61646c); }
.script-title { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 6px; background: #edf3ff; color: #385ea9; font-size: 12px; font-weight: 500; }
.script-title svg { flex-shrink: 0; }
.script-size { color: #626b79; }
.script-hint { color: var(--primary, #4c64e2); }
.copy-btn { padding: 6px; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary, #61646c); cursor: pointer; }
.copy-btn:hover { background: #f3f4f6; }
.script-code { max-height: 300px; overflow: auto; }
.script-code pre { margin: 0 0 12px; padding: 12px; background: #f6f7f9; border-radius: 8px; font: 13px/1.6 Consolas, monospace; white-space: pre; color: var(--text-primary, #27272a); }
.steps-list { display: flex; flex-direction: column; gap: 8px; }
.step-row, .subprocess-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; color: var(--text-secondary, #61646c); }
.step-label, .subprocess-label, .subprocess-note { overflow-wrap: anywhere; min-width: 0; }
.step-row.failed { color: #b42318; }
.step-indicator, .subprocess-indicator { display: flex; justify-content: center; flex-shrink: 0; width: 14px; }
.indicator-dot, .badge-pulse { width: 6px; height: 6px; border-radius: 50%; background: #8b8e97; }
.indicator-dot.success { background: #16834a; }
.indicator-dot.error { background: #b42318; }
.indicator-spinner { width: 12px; height: 12px; border: 2px solid #e4e4e7; border-top-color: var(--primary, #4c64e2); border-radius: 50%; animation: spin .8s linear infinite; }
.progress-section { display: flex; align-items: center; gap: 8px; }
.progress-track { flex: 1; height: 3px; background: #e4e4e7; border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--primary, #4c64e2); transition: width .3s; }
.progress-fill.indeterminate { width: 30%; animation: indeterminate 1.5s ease-in-out infinite; }
.progress-pct, .subprocess-note { font-size: 12px; color: #626b79; }
.subprocess-row { flex-wrap: wrap; }
.error-msg, .rate-limit-note { margin-top: 8px; padding: 10px; border-radius: 8px; background: #fff5f3; color: #b42318; font-size: 13px; overflow-wrap: anywhere; }
.rate-limit-note { background: #fffbeb; color: #92400e; }
.token-footer { margin-top: 16px; color: #626b79; font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes indeterminate { 50% { margin-left: 70%; } }
@media (prefers-reduced-motion: reduce) { .indicator-spinner, .progress-fill.indeterminate { animation: none; } .chevron { transition: none; } }
@media (max-width: 480px) { .glass-header { flex-wrap: wrap; } .script-size { display: none; } }
</style>
