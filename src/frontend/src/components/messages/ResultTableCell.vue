<template>
    <div class="result-cell">
        <div :id="contentId" ref="contentRef" class="cell-value" :class="{ 'is-collapsed': !isList && !expanded }">
            <ul v-if="isList" class="cell-list">
                <li v-for="(entry, index) in visibleValues" :key="index">{{ resultValueText(entry) }}</li>
            </ul>
            <template v-else>{{ resultValueText(value) }}</template>
        </div>
        <button
            v-if="canExpand"
            type="button"
            class="cell-toggle"
            :aria-expanded="expanded"
            :aria-controls="contentId"
            :aria-label="`${expanded ? 'Show less' : 'View all'} ${label}`"
            @click="expanded = !expanded"
        >{{ expanded ? 'Show less' : isList ? `Show ${value.length - 5} more` : 'View all' }}</button>
    </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { resultValueText } from './resultTable.js'

const props = defineProps({
    value: { default: null },
    label: { type: String, default: 'values' },
})
const contentId = `result-cell-${useId()}`
const contentRef = ref(null)
const expanded = ref(false)
const hasOverflow = ref(false)
const isList = computed(() => Array.isArray(props.value))
const visibleValues = computed(() => expanded.value ? props.value : props.value.slice(0, 5))
const canExpand = computed(() => isList.value ? props.value.length > 5 : hasOverflow.value)
let observer

const measureOverflow = () => {
    const element = contentRef.value
    // Hidden conversation cards are measured when they become visible again.
    if (!element?.clientWidth) return
    const previewHeight = parseFloat(getComputedStyle(element).lineHeight) * 3
    hasOverflow.value = element.scrollHeight > previewHeight + 1
}

onMounted(() => {
    observer = new ResizeObserver(measureOverflow)
    observer.observe(contentRef.value)
    measureOverflow()
})

watch(() => props.value, () => {
    expanded.value = false
    measureOverflow()
}, { deep: true, flush: 'post' })

onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.result-cell { min-width: 0; }
.cell-value { line-height: 1.6; overflow-wrap: anywhere; }
.cell-list { margin: 0; padding-left: 16px; }
.cell-list li + li { margin-top: 3px; }
.cell-value.is-collapsed {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
    overflow: hidden;
}
.cell-toggle {
    display: block;
    margin-top: 4px;
    padding: 3px 0;
    border: 0;
    background: transparent;
    color: #365bb3;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 1.5;
    text-align: left;
    cursor: pointer;
}
.cell-toggle:hover { text-decoration: underline; text-underline-offset: 3px; }
.cell-toggle:focus-visible { outline: 2px solid var(--primary, #3e63dd); outline-offset: 3px; border-radius: 2px; }
</style>
