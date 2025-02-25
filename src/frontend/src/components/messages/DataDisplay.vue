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
                <div v-if="metadata?.last_sync" class="text-caption text-grey-darken-1 mt-1">
                    Last synced: {{ metadata.last_sync }}
                </div>
            </div>

            <!-- Data Table -->
            <v-data-table
                v-if="hasResults"
                :headers="formattedHeaders"
                :items="tableItems"
                :loading="loading"
                :items-per-page="10"
                class="elevation-1"
                hover
            >
                <template v-slot:top>
                    <div class="d-flex justify-end pa-2">
                        <span class="text-caption">{{ tableItems.length }} {{ tableItems.length === 1 ? 'result' : 'results' }}</span>
                    </div>
                </template>
            </v-data-table>

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

// Updated header formatting for Vuetify 3
const formattedHeaders = computed(() => {
    if (props.metadata?.headers && Array.isArray(props.metadata.headers)) {
        return props.metadata.headers.map(header => ({
            title: header.text,
            key: header.value,
            align: header.align || 'start',
            sortable: true
        }))
    }
    
    if (hasResults.value && tableItems.value.length > 0) {
        return Object.keys(tableItems.value[0]).map(key => ({
            title: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            key: key,
            align: 'start',
            sortable: true
        }))
    }
    
    return []
})

const tableItems = computed(() => {
    if ((isStreamData.value || isDataType.value) && Array.isArray(props.content)) {
        return props.content
    }
    return []
})

const hasResults = computed(() => {
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

:deep(.v-data-table) {
    border-radius: 8px;
    overflow: hidden;
}

:deep(.v-data-table-header) {
    background-color: #f8f9fa;
}

:deep(.v-data-table-header th) {
    font-weight: 600 !important;
    color: #374151 !important;
}

:deep(.v-data-table__wrapper) {
    overflow-x: auto;
}

:deep(.v-data-table__wrapper table) {
    width: 100%;
    border-spacing: 0;
}
</style>