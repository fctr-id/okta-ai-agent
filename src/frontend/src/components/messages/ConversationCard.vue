<template>
    <section class="response-card" :class="{ 'is-collapsed': collapsed, 'is-follow-up': followUp }">
        <button
            type="button"
            class="turn-header"
            v-hint="question"
            :aria-expanded="!collapsed"
            :aria-controls="bodyId"
            @click="$emit('update:collapsed', !collapsed)"
        >
            <svg class="turn-chevron" :class="{ expanded: !collapsed }" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="m6 4 4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span class="turn-heading-copy">
                <span class="turn-question">{{ question }}</span>
                <span v-if="timestamp" class="turn-author">{{ timestamp }}</span>
            </span>
            <span class="turn-heading-summary">
                <span v-if="resultSummary" class="turn-record-count">{{ resultSummary }}</span>
                <span v-if="status" class="turn-header-status" :data-tone="statusTone" role="status">
                    <span class="turn-status-dot" aria-hidden="true"></span>{{ status }}
                </span>
            </span>
        </button>
        <!-- Keep children mounted so table state survives closing a turn. -->
        <div v-show="!collapsed" :id="bodyId" class="response-body">
            <slot />
        </div>
    </section>
</template>

<script setup>
import { useId } from 'vue'

defineProps({
    question: { type: String, default: '' },
    timestamp: { type: String, default: '' },
    status: { type: String, default: 'Working' },
    statusTone: { type: String, default: 'active' },
    resultSummary: { type: String, default: '' },
    collapsed: { type: Boolean, default: false },
    followUp: { type: Boolean, default: false },
})
defineEmits(['update:collapsed'])
const bodyId = `turn-body-${useId()}`
</script>

<style scoped>
.response-card { min-width: 0; border: 1px solid #b8c2cf; border-radius: 12px; background: #fff; overflow: hidden; }
.turn-header { display: flex; align-items: center; gap: 12px; width: 100%; padding: 12px 22px; border: 0; background: #eef3fc; color: #243957; font: inherit; text-align: left; cursor: pointer; transition: background .15s ease; }
.is-follow-up .turn-header { padding-block: 8px; }
.turn-header:hover { background: #e6edfa; }
.is-collapsed .turn-header { background: #f7f9fd; }
.is-collapsed .turn-header:hover { background: #eef3fc; }
.turn-header:focus-visible { outline: 2px solid var(--primary, #3e63dd); outline-offset: -3px; }
.turn-chevron { flex-shrink: 0; color: #4c67a1; transition: transform .15s ease; }
.turn-chevron.expanded { transform: rotate(90deg); }
.turn-heading-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.turn-question { font-size: 14px; font-weight: 500; line-height: 1.5; overflow-wrap: anywhere; }
.is-collapsed .turn-question { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.turn-author { font-size: 12px; color: #596b82; line-height: 1.5; }
.turn-heading-summary { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px 12px; flex-shrink: 0; max-width: 35%; font-size: 12px; }
.turn-record-count { color: #52627a; font-variant-numeric: tabular-nums; }
.turn-header-status { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 6px; background: #e4eaf4; color: #52627a; line-height: 1.3; }
.turn-header-status[data-tone="success"] { background: #e2f3e9; color: #24694b; }
.turn-header-status[data-tone="error"] { background: #fce8e8; color: #a13333; }
.turn-header-status[data-tone="active"] { background: #bcd2ff; color: #173f87; font-weight: 600; box-shadow: inset 0 0 0 1px #8baeea; }
.turn-status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.turn-header-status[data-tone="active"] .turn-status-dot { animation: status-pulse 1.5s ease-in-out infinite; }
.response-body { border-top: 1px solid #b8c2cf; min-width: 0; }
.response-body :deep(.transcript-react-panels) { gap: 0; }
.response-body :deep(.activity),
.response-body :deep(.exec-glass),
.response-body :deep(.results-table) { border: 0; border-radius: 0; box-shadow: none; }
.response-body :deep(.activity-toggle),
.response-body :deep(.glass-header) { padding: 11px 22px; background: #fcfdff; }
.response-body :deep(.activity-toggle:hover),
.response-body :deep(.glass-header:hover) { background: #f3f6fa; }
.response-body :deep(.exec-glass) { border-top: 1px solid var(--workspace-outline); }
.response-body :deep(.transcript-react-panels + *) { border-top: 1px solid var(--workspace-outline); }
.response-body :deep(.results-container) { border-radius: 0; }
.response-body :deep(.compact-results) { padding: 20px 22px; align-items: flex-start; }
.response-body :deep(.compact-results .data-display) { max-width: var(--turn-content-max-width, 860px); }
.response-body :deep(.turn-loading-card),
.response-body :deep(.turn-summary-card) { max-width: none; margin: 0; border: 0; border-radius: 0; }
.response-body :deep(.transcript-react-panels + .turn-loading-card),
.response-body :deep(.transcript-react-panels + .turn-summary-card) { border-top: 1px solid var(--workspace-outline); }
@keyframes status-pulse { 50% { opacity: .65; } }
@media (prefers-reduced-motion: reduce) { .turn-chevron { transition: none; } .turn-header-status .turn-status-dot { animation: none; } }
@media (max-width: 600px) {
    .turn-header { flex-wrap: wrap; gap: 8px; padding: 12px 14px; }
    .is-follow-up .turn-header { padding-block: 10px; }
    .turn-chevron { align-self: flex-start; margin-top: 3px; }
    .turn-heading-summary { width: 100%; max-width: none; justify-content: flex-start; padding-left: 24px; }
    .response-body :deep(.activity-toggle), .response-body :deep(.glass-header) { padding: 11px 14px; }
}
</style>
