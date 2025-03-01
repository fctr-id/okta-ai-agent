<template>
    <div class="data-display">
        <!-- Text Message Display -->
        <div v-if="isTextData" class="text-content">
            {{ props.content }}
        </div>

        <!-- JSON Data Display -->
        <div v-else-if="isJsonData" class="json-content">
            <pre>{{ formattedJson }}</pre>
        </div>

        <!-- Error Message Display -->
        <div v-if="isError" class="error-content">
            {{ getErrorContent }}
        </div>

        <!-- Data Table Display -->
        <div v-else-if="displayedItems.length > 0" class="table-content">
            <v-data-table :key="`table-${displayedItems.length}`" :headers="formattedHeaders" :items="displayedItems"
                :loading="loading" :items-per-page="10" :search="search" :sort-by="sortBy" density="compact" hover>
                <template v-slot:top>
                    <div class="table-header-container pb-6">
                        <div class="search-row pl-4">
                            <div class="header-actions">
                                <div class="left-section">
                                    <v-btn class="download-btn" @click="downloadCSV" variant="tonal">
                                        <v-icon size="small" start>mdi-download</v-icon>
                                        Download CSV
                                    </v-btn>

                                    <div class="sync-info">
                                        <v-icon class="sync-icon" size="small">mdi-update</v-icon>
                                        <span>Updated at: {{ getLastSyncTime }}</span>
                                    </div>
                                </div>

                                <div class="right-section">
                                    <!--<div class="results-count" v-if="displayedItems.length">
                                        {{ displayedItems.length }} {{ displayedItems.length === 1 ? 'result' :
                                        'results' }}
                                    </div>-->

                                    <v-text-field v-model="search" density="comfortable" hide-details
                                        placeholder="Search results" prepend-inner-icon="mdi-magnify" single-line clearable
                                        variant="outlined" class="search-field"></v-text-field>
                                </div>
                            </div>
                        </div>
                        <!-- Remove the info-row div completely -->
                    </div>
                </template>
            </v-data-table>
        </div>

        <!-- No Results Message -->
        <div v-else-if="!loading && !displayedItems.length" class="no-results">
            <v-icon icon="mdi-information-outline" color="#4C64E2" size="large" class="mb-3"></v-icon>
            <div class="no-results-message">No results found</div>
            <div class="no-results-hint">Try adjusting your query or search terms</div>
        </div>
    </div>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { MessageType } from './messageTypes'

const clearSearch = () => {
    search.value = ''
}

// Props with improved type definitions
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

// State management

const search = ref('')
const sortBy = ref([{ key: 'email', order: 'asc' }])

// Type checks with simplified logic
const isStreamData = computed(() => props.type === MessageType.STREAM)
const isJsonData = computed(() => props.type === MessageType.JSON)
const isError = computed(() => props.type === MessageType.ERROR)
//const isTextData = computed(() => props.type === MessageType.TEXT)
const isMetadata = computed(() => props.type === MessageType.METADATA)


const isTextData = computed(() =>
    props.type === 'text' ||
    (typeof props.content === 'object' && props.content?.type === 'text')
)

const displayedItems = computed(() => {
    //console.log('Computing displayedItems:', {
    //    type: props.type,
    //    content: props.content
    //});

    if (props.type === MessageType.STREAM || props.type === MessageType.BATCH) {
        return Array.isArray(props.content) ? props.content : [];
    }
    return [];
});



// Formatted Headers
const formattedHeaders = computed(() => {
    // Use metadata headers if available
    if (props.metadata?.headers && Array.isArray(props.metadata.headers)) {
        return props.metadata.headers.map(header => ({
            title: header.text,
            key: header.value,
            align: header.align || 'start',
            sortable: true,
            width: header.width || 'auto'
        }))
    }

    // Generate headers from data if available
    if (displayedItems.value.length > 0) {
        return Object.keys(displayedItems.value[0]).map(key => ({
            title: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            key: key,
            align: 'start',
            sortable: true,
            width: 'auto'
        }))
    }

    return []
})

// Formatted JSON content
const formattedJson = computed(() => {
    try {
        return JSON.stringify(props.content, null, 2)
    } catch (error) {
        console.error('JSON formatting error:', error)
        return String(props.content)
    }
})

const getLastSyncTime = computed(() => {
    // Check multiple possible locations
    if (props.metadata?.last_sync) {
        return props.metadata.last_sync;
    }
    
    // Check with brackets notation (case sensitive)
    if (props.metadata?.['last_sync']) {
        return props.metadata['last_sync'];
    }
    
    // Check if it might be inside a nested structure
    if (props.metadata?.headers && 
        props.metadata?.timestamp && 
        props.metadata?.query) {
        // This appears to be the backend metadata structure
        return props.metadata.last_sync || 'Never';
    }
    
    // Log what we have for debugging
    console.log('Last sync not found in:', props.metadata);
    
    return 'Never';
});

//Display error content
const getErrorContent = computed(() => {
    if (!isError.value) return '';

    if (typeof props.content === 'string') {
        return props.content;
    }

    if (typeof props.content === 'object') {
        return props.content.message || String(props.content);
    }

    return 'An error occurred';
});

// Cleanup
onBeforeUnmount(() => {
    search.value = ''
    sortBy.value = [{ key: 'email', order: 'asc' }]

    // Clear table data
    //displayedContent.value = []
    //headerCache.value = []
})


// Add CSV download functionality
const downloadCSV = () => {
    if (!displayedItems.value?.length) {
        console.warn('No items to download')
        return
    }

    try {
        // Generate headers from first item
        const firstItem = displayedItems.value[0]
        const headers = Object.keys(firstItem).map(key => ({
            text: key.replace(/_/g, ' ').toUpperCase(),
            value: key
        }))

        // Create CSV content
        const headerRow = headers
            .map(h => `"${h.text}"`)
            .join(',')

        const dataRows = displayedItems.value.map(item =>
            headers
                .map(h => {
                    const value = item[h.value]
                    return `"${value ?? ''}"`
                })
                .join(',')
        )

        const csvContent = [headerRow, ...dataRows].join('\n')

        // Create local timestamp for filename
        const now = new Date()
        const localTimestamp = now.toLocaleString('en-US', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).replace(/[/:]/g, '-').replace(',', '')

        const filename = `okta-data-${localTimestamp}.csv`

        // Create and trigger download
        const blob = new Blob([csvContent], {
            type: 'text/csv;charset=utf-8'
        })

        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.setAttribute('href', url)
        link.setAttribute('download', filename)
        link.style.display = 'none'

        document.body.appendChild(link)
        link.click()

        // Cleanup
        setTimeout(() => {
            document.body.removeChild(link)
            URL.revokeObjectURL(url)
        }, 100)

    } catch (error) {
        console.error('CSV generation error:', error)
    }
}

// Use this to debu streaming data udates sent from backend
/*
watch(() => props.content, (newContent) => {
    console.log('Content updated:', {
        length: Array.isArray(newContent) ? newContent.length : 0,
        type: props.type
    });
}, { deep: true });
*/

</script>

<style scoped>
.data-display {
    margin: 0;
    width: 100%;
    padding: 24px;
}

.text-content {
    padding: 16px;
    line-height: 1.6;
    font-size: 15px;
    color: #374151;
    border-radius: 8px;
    background: #f9faff;
    margin: 0 auto;
    max-width: 800px;
    text-align: center; /* Center the text */
    box-shadow: 0 2px 8px rgba(76, 100, 226, 0.05);
}

/* Streamlined header */
.header-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 0 0 12px 0;
}

.left-section {
    display: flex;
    align-items: center;
    gap: 16px;
}

.right-section {
    display: flex;
    align-items: center;
    gap: 16px;
}

.download-btn {
    color: #4C64E2;
    text-transform: none;
    font-size: 14px;
    font-weight: 500;
    padding: 0 16px !important;
    height: 36px;
    border: 1px solid #eef1ff !important;
}

.download-btn:hover {
    background: #f8f9ff !important;
}

.sync-info {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #5d6b8a;
    font-size: 0.813rem;
    white-space: nowrap;
}

.sync-icon {
    color: #4C64E2;
    font-size: 16px;
}

.results-count {
    color: #6B7280;
    font-size: 0.813rem;
}

/* Content Type Styles */
.json-content {
    padding: 16px;
    overflow-x: auto;
    margin: 0 auto;
    max-width: 800px;
    background: #f9faff;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(76, 100, 226, 0.05);
}

.json-content pre {
    margin: 0;
    font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: 14px;
    white-space: pre-wrap;
    word-break: break-word;
    color: #374151;
}

.error-content {
    color: #991B1B;
    border-left: 3px solid #DC2626;
    padding: 14px 18px;
    font-size: 15px;
    background: #FEF2F2;
    border-radius: 8px;
    margin: 0 auto; /* Already centered, but reinforcing */
    max-width: 600px;
    line-height: 1.5;
    box-shadow: 0 8px 16px rgba(220, 38, 38, 0.08),
                0 2px 4px rgba(220, 38, 38, 0.08),
                0 0 1px rgba(0, 0, 0, 0.08);
    width: fit-content;
    min-width: 300px;
    display: flex;
    flex-direction: column;
    align-items: center; /* Center content inside */
    text-align: center; /* Center text */
}

.no-results {
  padding: 24px 16px;
  text-align: center;
  color: #6b7280;
  font-size: 15px;
  margin: 0 auto;
  max-width: 600px;
  background: transparent; /* Remove background */
  border-radius: 0;        /* Remove border radius */
  box-shadow: none;        /* Remove shadow */
}


.table-header-container {
    padding: 16px 0 8px 0;
}

.header-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 0;
}

.left-section {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: nowrap;
}

.right-section {
    display: flex;
    align-items: center;
    gap: 16px;
    flex: 1;
    justify-content: flex-end;
}

.search-field {
    min-width: 280px;
    max-width: 400px;
    flex-grow: 1;
}

:deep(.search-field .v-field__input) {
    font-size: 14px;
}

:deep(.search-field .v-field) {
    border-radius: 6px;
    border: 1px solid #eef1ff;
}

/* Minimalist Table Styles */
:deep(.v-data-table) {
    background: transparent;
    box-shadow: none;
}

:deep(.v-data-table__wrapper) {
    overflow-x: auto;
    border: 1px solid #eef1ff;
    border-radius: 8px;
}

/* More aggressive table header styling */
:deep(.v-data-table) th,
:deep(.v-data-table-header th),
:deep(.v-data-table-header__cell),
:deep(.v-data-table) .v-data-table-header th {
  transition: all 0.2s ease !important;
  font-weight: 500 !important;
  color: #374151 !important;
  font-size: 13px !important;
  letter-spacing: 0.3px !important;
  text-transform: uppercase !important;
  position: relative !important;
  background-color: #FAFBFF !important;
}

/* Stronger hover selectors */
:deep(.v-data-table) th:hover,
:deep(.v-data-table-header th:hover),
:deep(.v-data-table-header__cell:hover),
:deep(.v-data-table) .v-data-table-header th:hover {
  background-color: #f0f3ff !important; 
  color: #4C64E2 !important;
  cursor: pointer !important;
}

/* Bottom indicator using multiple selectors */
:deep(.v-data-table) th:hover::after,
:deep(.v-data-table-header th:hover::after),
:deep(.v-data-table-header__cell:hover::after) {
  content: '' !important;
  position: absolute !important;
  bottom: 0 !important;
  left: 0 !important;
  right: 0 !important;
  height: 2px !important;
  background: #4C64E2 !important;
  opacity: 0.7 !important;
}

/* Alternative approach using direct style attributes */
:deep([role="columnheader"]) {
  transition: background-color 0.2s ease !important;
}

:deep([role="columnheader"]:hover) {
  background-color: #f0f3ff !important;
  color: #4C64E2 !important;
}



/* Clean row styles */
:deep(.v-data-table-row:hover) {
    background-color: #f9faff !important;
}

:deep(.v-data-table .v-data-table-row td) {
    padding: 12px 16px !important;
    font-size: 0.875rem;
    color: #374151;
    border-bottom: 1px solid #f5f7ff;
}

/* Simplified Pagination */
:deep(.v-data-table-footer) {
    padding: 6px 8px;
    border-top: 1px solid #eef1ff;
}

/* Responsive adjustments */
@media (max-width: 992px) {
    .header-actions {
        flex-wrap: wrap;
        gap: 16px;
    }
    
    .right-section {
        flex: 1 0 100%;
        order: 1;
    }
    
    .left-section {
        order: 2;
    }
}

@media (max-width: 768px) {
    .right-section {
        flex-direction: row-reverse;
    }
    
    .search-field {
        min-width: 0;
        flex: 1;
    }
}

@media (max-width: 480px) {
    .left-section {
        flex-wrap: wrap;
        gap: 8px;
    }
    
    .right-section {
        flex-direction: column;
        align-items: flex-start;
    }
    
    .search-field {
        width: 100%;
    }
}
</style>