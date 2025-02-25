<template>
    <div class="data-display">
        <!-- Text Message Display -->
        <div v-if="isTextData" class="text-content">
            <p>{{ content }}</p>
        </div>

        <!-- Combined Data Table Display -->
        <div v-if="isStreamData || isDataType" class="sql-results">
            <!-- Query Info -->
            <div v-if="metadata?.query" class="query-info mb-2">
                <div class="font-weight-medium">Query: <span class="font-weight-regular">{{ metadata.query }}</span></div>
                <div v-if="metadata?.explanation" class="text-body-2 text-grey-darken-1 mt-1">{{ metadata.explanation }}</div>
            </div>

            <!-- Results Count -->
            <div v-if="hasResults" class="results-info mb-1">
                <span class="text-caption">{{ tableItems.length }} {{ tableItems.length === 1 ? 'result' : 'results' }}</span>
            </div>

            <!-- Data Table -->
            <v-data-table 
                v-if="hasResults"
                :headers="metadata?.headers || []"
                :items="tableItems"
                :loading="loading"
                class="mt-2 elevation-1"
                density="comfortable"
                :items-per-page="10"
                :footer-props="{
                    'items-per-page-options': [10, 25, 50, 100, -1],
                    'items-per-page-text': 'Rows per page'
                }"
            />

            <div v-else-if="!loading" class="no-results">
                <p>No results found for this query.</p>
            </div>
        </div>

        <!-- JSON Display -->
        <div v-else-if="isJsonData" class="json-content">
            <pre>{{ formattedJson }}</pre>
        </div>

        <!-- Simple Error Display -->
        <div v-else-if="isError" class="error-content">
            {{ typeof content === 'string' ? content : content.message }}
        </div>

    </div>
</template>

<script setup>
import { computed } from 'vue'
import { MessageType } from './messageTypes'

const props = defineProps({
    type: String,
    content: {
        type: [Array, Object, String],
        required: true
    },
    metadata: {
        type: Object,
        default: () => ({})
    },
    loading: {
        type: Boolean,
        default: false
    }
})

const isStreamData = computed(() => props.type === MessageType.STREAM)
const isJsonData = computed(() => props.type === MessageType.JSON)
const isError = computed(() => props.type === MessageType.ERROR)
const isTextData = computed(() => props.type === MessageType.TEXT)
const isDataType = computed(() => props.type === 'data')

const tableItems = computed(() => {
    // Include both stream and data type checks
    if ((isStreamData.value || isDataType.value) && Array.isArray(props.content)) {
        return props.content
    }
    return []
})

const hasResults = computed(() => {
    // Simplify the check to just verify content exists and is non-empty
    return Array.isArray(props.content) && props.content.length > 0
})

const formattedJson = computed(() =>
    JSON.stringify(props.content, null, 2)
)
</script>

<style scoped>
.data-display {
    width: 100%;
    margin: 8px 0;
}

.json-content {
    background: #f5f5f5;
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
}

.json-content pre {
    margin: 0;
    font-family: monospace;
    font-size: 14px;
    white-space: pre-wrap;
    word-break: break-word;
}

.error-content {
    color: #DC2626;
    background-color: #FEF2F2;
    border: 0px solid #FCA5A5;
    padding: 0px;
    border-radius: 4px;
}

.text-content {
    white-space: pre-line;
    padding: 8px 0;
}

.query-info {
    padding: 8px 12px;
    background-color: #f8f9fa;
    border-radius: 4px;
}

.no-results {
    padding: 12px;
    background-color: #f8f9fa;
    border-radius: 4px;
    font-style: italic;
    color: #707070;
}

.results-info {
    display: flex;
    justify-content: flex-end;
    font-style: italic;
}
</style>