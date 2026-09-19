<template>
  <section class="activity" aria-label="Tool activity">
    <button type="button" class="activity-toggle" :aria-expanded="isExpanded"
      :aria-controls="contentId" @click="isExpanded = !isExpanded">
      <svg class="chevron" :class="{ expanded: isExpanded }" width="14" height="14"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="m9 5 7 7-7 7" />
      </svg>
      <span class="activity-label">Activity</span>
      <span v-if="tools.length" class="activity-count">{{ tools.length }} tool {{ tools.length === 1 ? 'call' : 'calls' }}</span>
      <span v-if="error || (isWorking && showWorkingStatus)" class="activity-state">
        <span v-if="isWorking" class="busy-dot" aria-hidden="true"></span>
        {{ error ? 'Stopped' : 'Working' }}
      </span>
      <span v-if="failedRequests" class="failed-count">{{ failedRequests }} failed {{ failedRequests === 1 ? 'attempt' : 'attempts' }}</span>
    </button>
    <div v-show="isExpanded" :id="contentId" class="activity-body">
      <p v-if="!tools.length" class="activity-placeholder">
        {{ isWorking ? 'Preparing your request…' : 'No tool calls recorded.' }}
      </p>
      <ol v-else class="tool-list">
        <li v-for="entry in tools" :key="entry.key" class="tool-entry">
          <div class="tool-heading">
            <svg class="tool-symbol" width="14" height="14" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-12-2 18" />
            </svg>
            <div class="tool-copy">
              <span class="tool-label">{{ toolLabel(entry.tool) }}</span>
              <p v-if="entry.tool.description && entry.tool.description !== toolLabel(entry.tool)" class="tool-description">{{ entry.tool.description }}</p>
            </div>
            <span class="tool-source" :data-source="toolSource(entry.tool)">{{ toolSource(entry.tool) }}</span>
          </div>
          <ul v-if="entry.tool.requests?.length" class="request-list" aria-label="Tested endpoints">
            <li v-for="request in entry.tool.requests" :key="request.id" :class="['request', request.status]">
              <span class="request-indicator" aria-hidden="true"></span>
              <span class="endpoint-name">{{ request.operation }}</span>
              <span class="request-status">{{ requestStatusLabels[request.status] }}</span>
            </li>
          </ul>
          <span v-else-if="entry.tool.testId" class="request-placeholder">No endpoint calls recorded.</span>
        </li>
      </ol>
      <p v-if="error && showError" class="activity-error">{{ error }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, useId, watch } from 'vue'
import { requestStatusLabels } from '../../composables/apiTestProgress'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  isThinking: { type: Boolean, default: false },
  isComplete: { type: Boolean, default: false },
  error: { type: String, default: null },
  showError: { type: Boolean, default: true },
  collapseRevision: { type: Number, default: 0 },
  executionStarted: { type: Boolean, default: false },
  shouldAutoCollapse: { type: Boolean, default: false },
  showWorkingStatus: { type: Boolean, default: true },
})
const contentId = `activity-${useId()}`
const isExpanded = ref(Boolean(props.error) || (!props.isComplete && !props.shouldAutoCollapse))
watch(() => props.collapseRevision, () => { isExpanded.value = false })
const isWorking = computed(() => !props.isComplete && !props.error)
// Only display tool activity. Step titles/text/reasoning may contain internal
// supervisor deliberation, including in previously saved conversations.
const tools = computed(() => props.steps.flatMap((step, stepIndex) =>
  (step.tools || []).map((tool, toolIndex) => ({
    tool, key: tool.testId || `${step.id || stepIndex}-${toolIndex}`,
  })),
))
const failedRequests = computed(() => tools.value.reduce((count, entry) =>
  count + (entry.tool.requests || []).filter(request => request.status === 'failed').length, 0,
))
watch(() => props.isComplete || props.shouldAutoCollapse, (finished) => {
  if (finished) isExpanded.value = false
})
watch(() => props.error, (error) => {
  if (error) isExpanded.value = true
})
const toolLabels = {
  get_sql_context: 'Read database schema',
  load_comprehensive_api_endpoints: 'Find available API endpoints',
  filter_endpoints_by_operations: 'Select API endpoints',
  execute_test_query_api: 'Test API endpoints',
  execute_test_query_sql: 'Test database query',
  load_artifacts: 'Read saved results',
  save_artifact: 'Save results',
}
const formatToolName = (name = 'Tool call') => toolLabels[name] || name.replace(/_/g, ' ').replace(/^okta /, '')
const toolLabel = (tool) => tool.testId
  ? tool.description || 'Test API endpoints'
  : tool.name && tool.name !== 'unknown' ? formatToolName(tool.name) : tool.description || 'Tool call'
const toolSource = (tool) => {
  if (tool.name?.includes('sql')) return 'Database'
  if (tool.testId || /api|endpoint/.test(tool.name || '')) return 'API'
  if (/artifact/.test(tool.name || '')) return 'Results'
  return ''
}
</script>

<style scoped>
.activity { width: 100%; margin: 0; border: 1px solid var(--workspace-outline, #d6dce5); border-radius: 10px; background: #fff; color: var(--text-secondary, #61646c); font-size: 14px; line-height: 1.5; overflow: hidden; }
.activity-toggle { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; width: 100%; padding: 11px 14px; background: #fff; border: 0; border-radius: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.activity-toggle:hover { background: rgba(127, 127, 127, 0.06); }
.activity-toggle:focus-visible { outline: 2px solid var(--primary, #6366f1); outline-offset: -2px; }
.activity-label { font-weight: 600; color: var(--text-primary, #27272a); }
.activity-count { color: #626b79; }
.activity-state { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.failed-count { color: #a15c0b; }
.chevron { flex-shrink: 0; transition: transform 0.15s ease; }
.chevron.expanded { transform: rotate(90deg); }
.activity-body { margin: 0; padding: 4px 16px 12px; border-top: 1px solid var(--workspace-outline, #d6dce5); font-size: 13px; }
.tool-list, .request-list { list-style: none; padding: 0; margin: 0; }
.tool-entry { padding: 10px 0; border-top: 1px solid #e8ecf1; }
.tool-entry:first-child { border-top: 0; }
.tool-heading { display: flex; align-items: flex-start; gap: 8px; }
.tool-symbol { flex-shrink: 0; margin-top: 2px; opacity: 0.7; }
.tool-copy { flex: 1; min-width: 0; }
.tool-label { overflow-wrap: anywhere; color: var(--text-primary, #27272a); }
.tool-description { margin: 3px 0 0; font-size: 13px; overflow-wrap: anywhere; color: var(--text-secondary, #61646c); }
.tool-source { flex-shrink: 0; font-size: 12px; font-weight: 500; color: #626b79; background: var(--bg-page, #f7f7f8); padding: 2px 7px; border-radius: 5px; }
.tool-source[data-source="Database"] { color: #6d43a5; background: #f1ebfa; }
.tool-source[data-source="API"] { color: #285eab; background: #eaf2fd; }
.tool-source[data-source="Results"] { color: #17736a; background: #e7f5f1; }
.tool-source:empty { display: none; }
.request-list { margin: 5px 0 0 22px; }
.request { display: flex; align-items: baseline; flex-wrap: wrap; gap: 5px 8px; padding: 3px 0; }
.request-indicator, .busy-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #8b8e97; flex-shrink: 0; }
.endpoint-name { min-width: 0; overflow-wrap: anywhere; color: var(--text-primary, #27272a); }
.request-status { font-size: 12px; color: #626b79; }
.success .request-indicator { background: #16834a; }
.empty .request-indicator { background: #b7791f; }
.failed .request-indicator { background: #d13f3f; }
.failed .request-status, .activity-error { color: #b42318; }
.running .request-indicator, .busy-dot { background: var(--primary, #6366f1); animation: pulse 1.4s ease-in-out infinite; }
.activity-placeholder, .activity-error { margin: 6px 0; overflow-wrap: anywhere; }
.request-placeholder { display: block; margin: 4px 0 0 22px; font-size: 12px; color: #626b79; }
@keyframes pulse { 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) {
  .running .request-indicator, .busy-dot { animation: none; }
  .chevron { transition: none; }
}
@media (max-width: 480px) {
  .activity-count { display: none; }
  .failed-count { flex-basis: 100%; padding-left: 22px; }
}
</style>
