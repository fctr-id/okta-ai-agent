<template>
    <div class="data-display">
        <!-- Text Message Display -->
        <div v-if="isTextData" class="text-content">
            {{ content }}
        </div>

        <!-- JSON Data Display -->
        <div v-else-if="isJsonData" class="json-content">
            <pre>{{ formattedJson }}</pre>
        </div>

        <!-- Error Message Display -->
        <div v-else-if="isError" class="error-content">
            {{ content }}
        </div>

        <!-- Data Table Display -->
        <div v-else-if="hasResults">
            <v-data-table :headers="formattedHeaders" :items="tableItems" :loading="loading" :items-per-page="10"
                :search="search" :sort-by="sortBy" hover>
                <template v-slot:top>
                    <div class="table-header-container">
                        <div class="search-row pl-4">
                            <v-text-field v-model="search" prepend-inner-icon="mdi-magnify" label="Search" single-line
                                hide-details density="comfortable" variant="underlined" class="search-field" />
                        </div>
                        <div class="info-row py-4 pl-4">
                            <div class="table-info">
                                <div class="sync-info">
                                    <v-icon icon="mdi-sync" size="small" class="sync-icon" />
                                    <span>Last synchronized: {{ props.metadata?.last_sync || 'Never' }}</span>
                                </div>
                                <div class="results-count">
                                    <span>{{ tableItems.length }} {{ tableItems.length === 1 ? 'result' : 'results'
                                        }}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </template>
            </v-data-table>
        </div>

        <!-- No Results Message -->
        <div v-else-if="!loading && !hasResults" class="no-results">
            No results found
        </div>
    </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { MessageType } from './messageTypes'

const props = defineProps({
    type: String,
    content: {
        required: true
    },
    metadata: {
        default: () => ({})
    },
    loading: {
        type: Boolean,
        default: false
    }
})

// Search and sort state
const search = ref('')
const sortBy = ref([
    {
        key: '',
        order: 'asc'
    }
])


// Type checks
const isStreamData = computed(() => props.type === MessageType.STREAM)
const isJsonData = computed(() => props.type === MessageType.JSON)
const isError = computed(() => props.type === MessageType.ERROR)
const isTextData = computed(() => props.type === MessageType.TEXT)
const isDataType = computed(() => props.type === 'data')

// Table data formatting
const formattedHeaders = computed(() => {
    if (props.metadata?.headers && Array.isArray(props.metadata.headers)) {
        return props.metadata.headers.map(header => ({
            title: header.text,
            key: header.value,
            align: header.align || 'start',
            sortable: true,
            width: header.width || 'auto'
        }))
    }

    if (hasResults.value && tableItems.value.length > 0) {
        return Object.keys(tableItems.value[0]).map(key => ({
            title: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            key: key,
            align: 'start',
            sortable: true,
            width: 'auto'
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

.info-row {
    margin-bottom: 0px;
    display: flex;
    justify-content: flex-start;
}

/* Content Type Styles */
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
    border-radius: 4px;
    padding: 12px;
}

.text-content {
    white-space: pre-line;
    padding: 12px 0;
}

.query-info {
    padding: 12px;
    background-color: #f4f4f4;
    border-radius: 4px;
}

.no-results {
    padding: 12px;
    background-color: #f8f9fa;
    border-radius: 4px;
    font-style: italic;
    color: #707070;
}

/* Data Table Styles */
::v-deep .v-data-table {
    background: transparent;
    box-shadow: none;
}

::v-deep .v-data-table__th {
    background-color: #F3F4F6 !important;
    color: #4B5563 !important;
    font-weight: 600 !important;
    font-size: 0.813rem !important;
    letter-spacing: 0.01em;
    text-transform: none;
    padding: 8px 16px !important;
    cursor: pointer;
    transition: background-color 0.2s ease;
    border-bottom: 1px solid #E5E7EB;
}

::v-deep .v-data-table__th:hover {
    background-color: #E5E7EB !important;
}

::v-deep .v-data-table-header__content {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

::v-deep .v-data-table-header__sort-icon {
    color: #4B5563 !important;
    opacity: 0.7;
    margin-left: 4px;
    font-size: 1rem;
}

::v-deep .v-data-table__wrapper {
    overflow-x: auto;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    background: white;
}

/* Toolbar and Search Styles */
::v-deep .table-toolbar {
    padding: 0 0 16px 0 !important;
    background: transparent !important;
}

::v-deep .search-field {
    max-width: 280px;
}

::v-deep .search-field .v-field__input {
    padding: 4px 12px;
    color: #374151;
}

::v-deep .search-field .v-field__append-inner {
    padding-top: 8px;
}

::v-deep .search-field .v-field__input input::placeholder {
    color: #9CA3AF;
}

.table-info {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 24px;
    padding: 8px 0;
    margin-bottom: 8px;
}

.sync-info {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #6B7280;
    font-size: 0.813rem;
}

.sync-icon {
    color: #6B7280;
    font-size: 16px;
}

.results-count {
    color: #6B7280;
    font-size: 0.813rem;
    min-width: 80px;
    text-align: right;
}

/* Row Styles */
::v-deep .v-data-table .v-data-table-row {
    border-bottom: 1px solid #E5E7EB;
    transition: background-color 0.2s ease;
}

::v-deep .v-data-table .v-data-table-row:hover {
    background-color: #F9FAFB !important;
}

::v-deep .v-data-table .v-data-table-row td {
    padding: 12px 16px;
    font-size: 0.875rem;
    color: #374151;
    background: white;
}

/* Pagination Styles */
::v-deep .v-data-table-footer {
    padding: 12px 16px;
    background: transparent;
}

/* Loading and Empty States */
::v-deep .v-data-table__progress {
    display: none;
}

::v-deep .v-data-table__empty-wrapper {
    color: #6B7280;
    font-size: 0.875rem;
    padding: 24px;
    text-align: center;
    background: white;
    border-radius: 8px;
    border: 1px solid #E5E7EB;
}

/* Responsive Styles */
@media (max-width: 600px) {
    ::v-deep .search-field {
        max-width: 100%;
    }

    .table-info {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
    }

    .results-count {
        text-align: left;
    }

    ::v-deep .table-toolbar {
        padding: 0 0 12px 0 !important;
    }
}
</style>