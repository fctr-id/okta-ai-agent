<template>
    <div class="data-display">
        <p v-if="resultSummary" class="result-explanation">
            <strong class="result-explanation-label"><v-icon size="16" class="result-explanation-icon" aria-hidden="true">mdi-creation</v-icon> AI Summary:</strong> {{ resultSummary }}
        </p>
        <!-- Text Message Display -->
        <div v-if="isTextData" class="markdown-shell">
            <div class="markdown-content" v-html="renderedMarkdown"></div>
        </div>

        <!-- JSON Data Display -->
        <div v-else-if="isJsonData" class="json-content">
            <pre>{{ formattedJson }}</pre>
        </div>

        <!-- Empty streaming table - show loading state -->
        <div v-else-if="shouldShowEmptyStreamingTable" class="table-content">
            <div class="d-flex justify-center align-center" style="min-height: 200px;">
                <div class="text-center">
                    <v-progress-circular
                        indeterminate
                        color="primary"
                        size="64"
                        class="mb-4"
                    ></v-progress-circular>
                    <p class="text-subtitle-1 mb-0">Preparing results...</p>
                    <p class="text-caption text-grey">Table will appear when data arrives</p>
                </div>
            </div>
        </div>

        <!-- Error Message Display -->
        <div v-if="isError" class="error-content">
            {{ getErrorContent }}
        </div>

        <!-- Data Table Display -->
        <div v-else-if="displayedItems.length > 0 || (isStreaming && (props.type === MessageType.TABLE || props.type === MessageType.STREAM))" class="table-content">
            <v-data-table class="results-table" :style="{ '--results-table-min-width': `${tableMinWidth}px` }"
                :headers="tableHeaders" :items="searchedItems" :item-value="rowKey"
                :loading="loading" :items-per-page="10" v-model:sort-by="sortBy" multi-sort
                v-model:page="tablePage" :group-by="groupBy" v-model:opened="openedGroups"
                items-per-page-text="Rows per page" density="compact" hover>
                <template v-slot:top>
                    <div class="table-header-container" :class="{ 'is-preview': isResultsPreview }">
                        <div class="results-heading">
                            <div class="results-title">
                                <h3>{{ isResultsPreview ? 'Results preview' : 'Results' }}</h3>
                                <span class="record-count">{{ recordCountLabel }}</span>
                            </div>
                            <div class="sync-info">
                                <span class="source-badge" :class="`source-${props.metadata?.data_source_type || 'api'}`">
                                    <v-icon size="14" aria-hidden="true">{{ getDataSourceDisplay.showRealtime ? 'mdi-cloud-outline' : 'mdi-database-outline' }}</v-icon>
                                    {{ getDataSourceDisplay.source }}{{ getDataSourceDisplay.suffix || '' }}
                                </span>
                                <span v-if="!getDataSourceDisplay.showRealtime && props.metadata?.data_source_type !== 'saved_session'" class="sync-time">Synced {{ getLastSyncTime }}</span>
                            </div>
                        </div>
                        <div class="results-tools">
                            <div v-if="isStreaming" class="streaming-indicator">
                                <v-progress-circular :model-value="streamingProgressPercent" size="16" width="2" color="primary" class="me-2" />
                                <span class="streaming-text">Loading results ({{ streamingProgressPercent }}%)</span>
                            </div>
                            <v-text-field v-model="search" density="compact" hide-details
                                :aria-label="isResultsPreview ? 'Search preview' : 'Search results'"
                                :placeholder="isResultsPreview ? 'Search preview' : 'Search results'"
                                prepend-inner-icon="mdi-magnify" single-line clearable variant="outlined" class="search-field" />
                            <v-btn class="download-btn" :class="{ 'preview-export': isResultsPreview }" @click="downloadCSV" variant="flat"
                                :title="`Export all ${displayedItems.length.toLocaleString()} loaded records and all result columns, including hidden fields`">
                                <v-icon size="small" start aria-hidden="true">mdi-download</v-icon>
                                {{ isResultsPreview ? 'Export preview' : 'Export CSV' }}
                            </v-btn>
                        </div>
                        <p v-if="isResultsPreview" class="preview-description">
                            {{ showTableAction ? 'Fetch all records to search and export the complete saved result.' : 'Search and export include only the records in this preview.' }}
                        </p>
                        <div v-if="showTableAction" class="table-action">
                            <v-btn class="saved-results-btn" :loading="tableActionLoading" :disabled="tableActionLoading"
                                variant="flat" @click="emit('table-action')">
                                <v-icon size="small" start aria-hidden="true">mdi-database-arrow-down-outline</v-icon>
                                {{ tableActionLabel }}
                            </v-btn>
                        </div>
                        <div class="table-view-controls">
                            <v-select v-model="groupColumn" :items="groupOptions" label="Group by"
                                aria-label="Group results by column" density="compact" variant="outlined"
                                hide-details class="group-field" />
                            <v-menu :close-on-content-click="false">
                                <template #activator="{ props: menuProps }">
                                    <v-btn v-bind="menuProps" variant="outlined" class="columns-button" prepend-icon="mdi-view-column-outline">
                                        Columns {{ visibleHeaders.length }}/{{ formattedHeaders.length }}
                                    </v-btn>
                                </template>
                                <div class="column-menu">
                                    <div class="column-presets" aria-label="Column presets">
                                        <v-btn size="small" variant="tonal" @click="selectColumns(5)">5 columns</v-btn>
                                        <v-btn size="small" variant="tonal" @click="selectColumns(7)">7 columns</v-btn>
                                        <v-btn size="small" variant="text" @click="selectColumns(formattedHeaders.length)">All</v-btn>
                                    </div>
                                    <p>CSV includes all result columns, even hidden ones.</p>
                                    <div class="column-options" role="group" aria-label="Visible columns">
                                        <label v-for="header in formattedHeaders" :key="header.key">
                                            <input type="checkbox" :checked="visibleKeys.has(header.key)"
                                                :disabled="visibleKeys.has(header.key) && visibleHeaders.length === 1"
                                                @change="toggleColumn(header.key)">
                                            {{ header.title }}
                                        </label>
                                    </div>
                                </div>
                            </v-menu>
                            <span class="sort-hint">Click headers to sort by multiple columns. Numbers show priority.</span>
                        </div>
                    </div>
                </template>
                <template #group-header="{ item, columns, toggleGroup, isGroupOpen }">
                    <tr class="result-group-row">
                        <td :colspan="columns.length">
                            <button type="button" class="result-group-toggle" :aria-expanded="isGroupOpen(item)"
                                @click="toggleGroup(item)">
                                <v-icon size="18" aria-hidden="true">{{ isGroupOpen(item) ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
                                <span>{{ groupLabel(item.value) }}</span>
                                <span class="group-count">{{ item.items.length.toLocaleString() }} {{ item.items.length === 1 ? 'record' : 'records' }}</span>
                            </button>
                        </td>
                    </tr>
                </template>
                <template v-for="header in visibleHeaders" :key="header.key" v-slot:[`item.${header.key}`]="{ value }">
                    <ResultTableCell :value="value" :label="header.title" />
                </template>
            </v-data-table>
        </div>

        <!-- No Results Message -->
        <div v-else-if="!loading && !displayedItems.length && !isTextData && !isJsonData && !isError && !isStreaming"
            class="no-results">
            <v-icon icon="mdi-information-outline" size="large" class="mb-3" style="color: var(--primary)"></v-icon>
            <div class="no-results-message">No results found</div>
            <div class="no-results-hint">Try adjusting your query or search terms</div>
        </div>
    </div>
</template>

<script setup>
import { marked } from 'marked'
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { MessageType } from './messageTypes'
import ResultTableCell from './ResultTableCell.vue'
import { resultColumnKeys, resultRowsCsv, resultValueText } from './resultTable.js'

marked.setOptions({
    breaks: true,    // Translate line breaks to <br>
    gfm: true,       // GitHub flavored markdown
    headerIds: false, // Don't add IDs to headers
    mangle: false,    // Don't mangle email addresses
})

// Add computed property to render markdown
const renderedMarkdown = computed(() => {
  if (!props.content || typeof props.content !== 'string') {
    return '';
  }
  
  // Process the content to fix line breaks in paragraphs while preserving formatting
  const processedContent = props.content
        // Preserve heading boundaries so heading styling does not absorb the next paragraph.
        .replace(/^(#{1,6}[ \t]+.+)\n(?=\S)/gm, '$1__MD_HEADING_BREAK__')
    // Fix line breaks in the middle of sentences (before lists and sections)
    .replace(/([a-zA-Z0-9.,:;)"])\n\n([0-9]+\.\s+)/g, '$1\n\n$2')
    // Fix line breaks in the middle of paragraphs
    .replace(/([a-zA-Z0-9.,;:)])(\n)([a-zA-Z0-9(])/g, '$1 $3')
    // Fix extra line breaks between list items
        .replace(/\n{3,}/g, '\n\n')
        .replace(/__MD_HEADING_BREAK__/g, '\n');
    
  return marked.parse(processedContent);
});

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
    },
    showTableAction: {
        type: Boolean,
        default: false
    },
    tableActionLabel: {
        type: String,
        default: 'Fetch all records'
    },
    tableActionLoading: {
        type: Boolean,
        default: false
    }
})

const emit = defineEmits(['table-action'])

// Render as text: generated explanations must never become HTML.
const resultSummary = computed(() => {
    if (props.metadata?.isStreaming) return ''
    if (props.type !== MessageType.TABLE && props.metadata?.outcome !== 'empty') return ''
    return typeof props.metadata?.summary === 'string' ? props.metadata.summary.trim() : ''
})

// State management


const search = ref('')
const sortBy = ref([{ key: 'email', order: 'asc' }])
const tablePage = ref(1)
const groupColumn = ref('')
const openedGroups = ref([])
const selectedColumns = ref(null)
const rowKeys = new WeakMap()
let nextRowKey = 0
const rowKey = item => {
    if (!rowKeys.has(item)) rowKeys.set(item, ++nextRowKey)
    return rowKeys.get(item)
}

watch([groupColumn, search], () => {
    tablePage.value = 1
    openedGroups.value = []
})

// Type checks with simplified logic
const isJsonData = computed(() => {
    const result = props.type === MessageType.JSON;
    return result;
});
const isError = computed(() => {
    const result = props.type === MessageType.ERROR;
    return result;
});

const isTextData = computed(() => {
    const result = props.type === 'text' ||
        props.type === MessageType.MARKDOWN ||
        (typeof props.content === 'object' && props.content?.type === 'text');
    return result;
});

const displayedItems = computed(() => {
    if (props.type === MessageType.STREAM || props.type === MessageType.BATCH || props.type === MessageType.TABLE) {
        // Handle both direct array content and nested content structure
        let items = [];
        
        if (Array.isArray(props.content)) {
            // Direct array of items (most common case during streaming)
            items = props.content;
        } else if (props.content && Array.isArray(props.content.content)) {
            // Nested content structure
            items = props.content.content;
        }
        
        // Keep a reference to the last known items to prevent table disappearing
        if (items.length > 0) {
            lastDisplayedItems.value = items;
        }
        
        // If items are empty but we were displaying items before and not streaming,
        // show the old items briefly to avoid flicker
        if (items.length === 0 && !isStreaming.value && lastDisplayedItems.value.length > 0) {
            return lastDisplayedItems.value;
        }

        return items;
    }
    return [];
});

// Keep track of last displayed items to prevent blank table
const lastDisplayedItems = ref([]);

const isResultsPreview = computed(() => props.metadata?.isPreview === true)
const recordCountLabel = computed(() => {
    const loaded = displayedItems.value.length
    const count = loaded.toLocaleString()
    if (isResultsPreview.value) {
        const total = Number(props.metadata?.count)
        return Number.isSafeInteger(total) && total > loaded
            ? `${count} of ${total.toLocaleString()} records`
            : `${count} shown`
    }
    return `${count} ${isStreaming.value ? 'loaded' : loaded === 1 ? 'record' : 'records'}`
})


// Keep technical identifiers readable without giving short statuses equal space.
const normalizedColumn = key => String(key).replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase()
const columnKind = key => {
    const name = normalizedColumn(key)
    if (/(^|_)status$/.test(name)) return 'status'
    if (/(^|_)(id|kid)$/.test(name)) return 'identifier'
    if (/(^|_)(email|login)$/.test(name)) return 'email'
    if (/(^|_)(at|date|time)$/.test(name)) return 'timestamp'
    if (/(^|_)(name|label)$/.test(name)) return 'name'
    return 'text'
}
const columnWidth = key => ({ status: 140, identifier: 230, email: 250, timestamp: 230, name: 200, text: 180 }[columnKind(key)])
// Formatted Headers
const formattedHeaders = computed(() => {
    // Use metadata headers if available
    if (props.metadata?.headers && Array.isArray(props.metadata.headers)) {
        return props.metadata.headers.map(header => ({
            title: header.text,
            key: header.value,
            align: header.align || 'start',
            sortable: true,
            width: header.width || columnWidth(header.value)
        }))
    }

    // Generate headers from data if available
    if (displayedItems.value.length > 0) {
        return resultColumnKeys(displayedItems.value).map(key => ({
            title: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            key: key,
            align: 'start',
            sortable: true,
            width: columnWidth(key)
        }))
    }

    return []
})
const visibleKeys = computed(() => new Set(selectedColumns.value ?? formattedHeaders.value.slice(0, 7).map(header => header.key)))
const visibleHeaders = computed(() => formattedHeaders.value.filter(header => visibleKeys.value.has(header.key)))
const selectColumns = count => { selectedColumns.value = formattedHeaders.value.slice(0, count).map(header => header.key) }
const toggleColumn = key => {
    const keys = new Set(visibleKeys.value)
    if (keys.has(key)) { if (keys.size > 1) keys.delete(key) } else keys.add(key)
    selectedColumns.value = [...keys]
}
watch(() => formattedHeaders.value.map(header => header.key).join('\0'), () => {
    selectedColumns.value = null
})
watch(visibleHeaders, headers => {
    const keys = new Set(headers.map(header => header.key))
    sortBy.value = sortBy.value.filter(sort => keys.has(sort.key))
    if (!keys.has(groupColumn.value)) groupColumn.value = ''
})
const searchedItems = computed(() => {
    const term = (search.value || '').trim().toLocaleLowerCase()
    return term ? displayedItems.value.filter(row => formattedHeaders.value.some(header =>
        resultValueText(row[header.key]).toLocaleLowerCase().includes(term))) : displayedItems.value
})
const tableMinWidth = computed(() => visibleHeaders.value.reduce((total, header) => total + columnWidth(header.key),
    groupBy.value.length ? 44 : 0))

// Group scalar values only; nested objects and arrays do not make useful group labels.
const groupOptions = computed(() => [
    { title: 'None', value: '' },
    ...visibleHeaders.value
        .filter(header => displayedItems.value.every(row => row[header.key] == null || typeof row[header.key] !== 'object'))
        .map(header => ({ title: header.title, value: header.key }))
])
const groupBy = computed(() => groupColumn.value && groupOptions.value.some(option => option.value === groupColumn.value)
    ? [{ key: groupColumn.value, order: 'asc' }]
    : [])
const groupLabel = value => value == null || value === '' ? '(Empty)' : String(value)
const tableHeaders = computed(() => [
    ...(groupBy.value.length ? [{ key: 'data-table-group', title: '', width: 44, sortable: false,
        headerProps: { class: 'group-spacer' }, cellProps: { class: 'group-spacer' } }] : []),
    ...visibleHeaders.value,
])

// Formatted JSON content
const formattedJson = computed(() => {
    try {
        return JSON.stringify(props.content, null, 2)
    } catch (error) {
        console.error('JSON formatting error:', error)
        return String(props.content)
    }
})

// Streaming support computed properties
const isStreaming = computed(() => {
    // Check both locations where streaming status might be stored
    const directStreaming = props.metadata?.isStreaming === true;
    const nestedStreaming = props.metadata?.streamingProgress?.isStreaming === true;
    const contentMetadataStreaming = props.content?.metadata?.isStreaming === true;
    
    const result = directStreaming || nestedStreaming || contentMetadataStreaming;

    return result;
})

const streamingProgress = computed(() => {
    return props.metadata?.streamingProgress || null
})

const streamingProgressPercent = computed(() => {
    if (!streamingProgress.value) return 0
    const { current, total } = streamingProgress.value
    return total > 0 ? Math.round((current / total) * 100) : 0
})

const shouldShowEmptyStreamingTable = computed(() => {
    const condition = displayMode.value === 'table' && displayedItems.value.length === 0 && isStreaming.value;
    return condition;
});

// Add computed to track what should be displayed
const displayMode = computed(() => {
    const hasDisplayedItems = displayedItems.value.length > 0;
    const isText = isTextData.value;
    const isJson = isJsonData.value;
    const isErr = isError.value;
    const isLoad = props.loading;
    const isStream = isStreaming.value;
    
    let mode = 'unknown';
    if (isText) mode = 'text';
    else if (isJson) mode = 'json';
    else if (isErr) mode = 'error';
    else if (hasDisplayedItems) mode = 'table';
    else if (props.type === 'table' && isStream) mode = 'table'; // Show empty table during streaming
    else if (!isLoad && !hasDisplayedItems && !isText && !isJson && !isErr && !isStream) mode = 'no-results';
    else mode = 'loading-or-hidden';

    return mode;
})

const getDataSourceDisplay = computed(() => {
    // Get data source type from metadata
    const dataSourceType = props.metadata?.data_source_type || 'api';
    
    switch (dataSourceType) {
        case 'saved_session':
            return {
                showRealtime: false,
                prefix: 'Data Source:',
                source: 'Saved session'
            };
        case 'sql':
            return {
                showRealtime: false,
                prefix: 'Data Source:',
                source: 'Database'
            };
        case 'hybrid':
            return {
                showRealtime: false,
                prefix: 'Data Source:',
                source: 'Database',
                suffix: ' + Live API'
            };
        case 'api':
        default:
            return {
                showRealtime: true,
                prefix: 'Data Source:',
                source: 'Live API'
            };
    }
})

const getLastSyncTime = computed(() => {
    // Get timestamp from the correct nested path
    let timestampStr = 'Never';

    // Handle the nested structure we identified
    if (props.metadata?.last_sync?.last_sync) {
        timestampStr = props.metadata.last_sync.last_sync;
    } else if (props.metadata?.last_sync && typeof props.metadata.last_sync === 'string') {
        timestampStr = props.metadata.last_sync;
    }

    if (timestampStr && timestampStr !== 'Never' && timestampStr !== 'Error') {
        try {
            // Parse timestamp as UTC (same approach as in useSync.js)
            const utcTimeStr = timestampStr.endsWith("Z") ? timestampStr : timestampStr + "Z";
            const date = new Date(utcTimeStr);

            // Format exactly like in formattedLastSyncTime()
            if (!isNaN(date.getTime())) {
                const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                const month = months[date.getMonth()];
                const day = date.getDate();
                const year = date.getFullYear();

                let hours = date.getHours();
                const ampm = hours >= 12 ? "PM" : "AM";
                hours = hours % 12;
                hours = hours ? hours : 12;
                const minutes = date.getMinutes().toString().padStart(2, "0");

                return `${month} ${day}, ${year}, ${hours}:${minutes} ${ampm}`;
            }

            return timestampStr.split('.')[0];
        } catch (e) {
            console.error('Error formatting timestamp:', e);
            return timestampStr;
        }
    }

    return timestampStr;
});
// Helper function to format timestamps consistently
const formatTimestamp = (timestamp) => {
    if (!timestamp || timestamp === 'Never' || timestamp === 'Error') {
        return timestamp;
    }

    try {
        const date = new Date(timestamp);
        if (!isNaN(date.getTime())) {
            const options = {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            };
            return new Intl.DateTimeFormat('en-US', options).format(date);
        }

        // For timestamps with milliseconds, remove them for cleaner display
        if (typeof timestamp === 'string' && timestamp.includes('.')) {
            return timestamp.split('.')[0];
        }

        return timestamp;
    } catch (e) {
        console.error('Error formatting timestamp:', e);
        return timestamp;
    }
}

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

})

// Add CSV download functionality
const downloadCSV = () => {
    if (!displayedItems.value?.length) {
        console.warn('No items to download')
        return
    }

    try {
        // Export the full loaded dataset, independent of pagination and display controls.
        const csvContent = resultRowsCsv(displayedItems.value, formattedHeaders.value)

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

// Result schemas vary by question; never retain a hidden sort or obsolete grouping column.
watch(() => formattedHeaders.value.map(header => header.key), keys => {
    sortBy.value = sortBy.value.filter(sort => keys.includes(sort.key))
    if (groupColumn.value && !keys.includes(groupColumn.value)) groupColumn.value = ''
}, { immediate: true })
</script>

<style scoped>
.data-display {
    margin: 0;
    width: 100%;
    padding: 0;
    min-width: 0;
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
    text-align: center;
    /* Center the text */
    box-shadow: 0 2px 8px rgba(76, 100, 226, 0.05);
}

/* Markdown content */
.text-content {
    text-align: left !important;
    /* Override center alignment for markdown */
    white-space: normal;
}

/* Style markdown elements */
.text-content :deep(h1),
.text-content :deep(h2),
.text-content :deep(h3),
.text-content :deep(h4) {
    margin-top: 1em;
    margin-bottom: 0.5em;
    font-weight: 600;
}

.text-content :deep(p) {
    margin-bottom: 1em;
}

.text-content :deep(ul),
.text-content :deep(ol) {
    padding-left: 2em;
    margin-bottom: 1em;
}

.text-content :deep(code) {
    background: rgba(0, 0, 0, 0.05);
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-family: monospace;
    font-size: 0.9em;
}

.text-content :deep(pre) {
    background: rgba(0, 0, 0, 0.05);
    padding: 1em;
    border-radius: 5px;
    overflow-x: auto;
    margin: 1em 0;
}

.text-content :deep(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

.text-content :deep(th),
.text-content :deep(td) {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: left;
}

.text-content :deep(th) {
    background-color: #f2f2f2;
}

/* End of markdown content */

.download-btn {
    color: #ffffff !important;
    text-transform: none;
    font-size: 13px;
    letter-spacing: normal;
    font-weight: 500;
    padding: 0 14px !important;
    height: 34px;
    border: 1px solid #375bcc !important;
    background: var(--primary) !important;
    border-radius: 9px !important;
    box-shadow: 0 2px 4px rgba(62, 99, 221, 0.12);
    transition: background 0.15s ease, border-color 0.15s ease;
}

.saved-results-btn {
    color: #fff !important;
    text-transform: none;
    letter-spacing: normal;
    font-size: 13px;
    font-weight: 500;
    padding: 0 12px !important;
    min-height: 34px;
    border: 1px solid #375bcc !important;
    background: var(--primary) !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(23, 36, 58, .08) !important;
}
.saved-results-btn:hover { background: var(--primary-hover) !important; }
.download-btn.preview-export { background: #fff !important; color: #405779 !important; border-color: #aebcd0 !important; box-shadow: none; }
.download-btn.preview-export:hover { background: #f7f9fd !important; border-color: #aebfe0 !important; }

.download-btn:hover {
    background: var(--primary-hover) !important;
    border-color: #2948a8 !important;
}

.sync-info {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #5f6b7a;
    font-size: 12px;
    white-space: normal;
    padding: 0;
    background: transparent;
    border-radius: 6px;
    flex-wrap: wrap;
}

.source-badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 6px; background: #edf3ff; color: #385ea9; font-size: 12px; font-weight: 500; }
.source-sql { color: #7754aa; background: #f2ecfa; }
.source-hybrid { color: #276e78; background: #eaf5f5; }
.source-saved_session { color: #566174; background: #eef1f5; }
.sync-time { font-size: 12px; }

.sync-icon {
    color: var(--primary);
    font-size: 16px;
}

.results-count {
    color: #6B7280;
    font-size: 0.813rem;
}

.streaming-indicator {
    color: #4C64E2;
}

.streaming-text {
    font-size: 0.813rem;
    font-weight: 500;
    color: #4C64E2;
}

.streaming-footer-indicator {
    border-top: 1px solid #eef1ff;
    background: #f9faff;
}

.streaming-footer-text {
    font-size: 0.875rem;
    font-weight: 500;
    color: #4C64E2;
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
    animation: fade-in-up 0.5s ease-out;
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
    margin: 0 auto;
    /* Already centered, but reinforcing */
    max-width: 600px;
    line-height: 1.5;
    box-shadow: 0 8px 16px rgba(220, 38, 38, 0.08),
        0 2px 4px rgba(220, 38, 38, 0.08),
        0 0 1px rgba(0, 0, 0, 0.08);
    width: fit-content;
    min-width: 300px;
    display: flex;
    flex-direction: column;
    align-items: center;
    /* Center content inside */
    text-align: center;
    /* Center text */
}

.result-explanation {
    margin: 0;
    padding: 16px 20px;
    color: #334155;
    font-size: 14px;
    line-height: 1.6;
    overflow-wrap: anywhere;
    border-bottom: 1px solid var(--workspace-outline, #e2e8f0);
}

.result-explanation-label {
    color: #2563eb;
    font-weight: 600;
    margin-inline-end: 4px;
    white-space: nowrap;
}

.result-explanation-icon { margin-inline-end: 3px; vertical-align: -2px; }

.no-results {
    padding: 24px 16px;
    text-align: center;
    color: #6b7280;
    font-size: 15px;
    margin: 0 auto;
    max-width: 600px;
    background: transparent;
    /* Remove background */
    border-radius: 0;
    /* Remove border radius */
    box-shadow: none;
    /* Remove shadow */
}


.table-header-container {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(300px, 400px);
    gap: 10px 24px;
    padding: 20px 22px;
}

.results-heading, .results-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 10px; }
.results-heading { grid-column: 1; grid-row: 1; gap: 12px; flex-wrap: wrap; }
.results-title h3 { color: #253248; font-size: 14px; font-weight: 600; margin: 0; }
.record-count { border-radius: 20px; background: #f1f3f7; color: #586579; padding: 3px 8px; font-size: 12px; font-variant-numeric: tabular-nums; }

.results-tools { grid-column: 2; grid-row: 1; display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 10px; min-width: 0; }
.preview-description { grid-column: 1; grid-row: 2; align-self: center; margin: 0; color: #5d6b7d; font-size: 12px; line-height: 1.5; }
.table-action { grid-column: 2; grid-row: 2; display: flex; justify-content: flex-end; align-items: center; }
.results-tools .streaming-indicator { flex-basis: 100%; text-align: right; }
.table-view-controls { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: 10px 16px; }
.group-field { flex: 0 1 220px; min-width: 160px; }
.sort-hint { margin-inline-start: auto; text-align: right; color: #5d6b7d; font-size: 12px; line-height: 1.5; }
:deep(.group-field .v-field) { border-radius: 10px; background: #f8fafc; }
:deep(.group-field .v-field__input) { font-size: 13px; min-height: 38px; padding-top: 7px; padding-bottom: 7px; }
:deep(.group-field .v-field__outline) { color: #aebcd0; --v-field-border-opacity: 1; }
:deep(.group-field .v-label) { color: #526077; opacity: 1; }
.result-group-toggle { display: flex; align-items: center; gap: 8px; width: 100%; padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left; color: #253248; font: inherit; font-weight: 600; border-radius: 4px; }
.result-group-toggle:focus-visible { outline: 2px solid #3d61ac; outline-offset: 4px; }
.group-count { color: #586579; font-size: 12px; font-weight: 400; }
:deep(.results-table .v-table__wrapper > table > tbody > .result-group-row > td) { background: #f5f7fb; vertical-align: middle; }
:deep(.results-table .v-table__wrapper > table > thead > tr > .group-spacer),
:deep(.results-table .v-table__wrapper > table > tbody > tr > .group-spacer) { width: 44px; padding: 0; }

.search-field {
    min-width: 160px;
    max-width: 100%;
    flex-grow: 1;
}

:deep(.search-field .v-field__input) {
    font-size: 13px;
    min-height: 34px;
    padding-top: 6px;
    padding-bottom: 6px;
}

:deep(.search-field input::placeholder) { color: #626b79; opacity: 1; }

:deep(.search-field .v-field) {
    border-radius: 10px;
    background: #f8fafc;
}
:deep(.search-field .v-field__outline) { color: #aebcd0; --v-field-border-opacity: 1; }
:deep(.search-field .v-field--focused .v-field__outline) { color: var(--primary); }
:deep(.search-field .v-field__prepend-inner .v-icon) { font-size: 19px; }

/* Target Vuetify's current table markup, including its native scroll wrapper. */
.table-content { width: 100%; min-width: 0; container-type: inline-size; }
.columns-button { height: 40px; border-color: #aebcd0; color: #40516b; text-transform: none; letter-spacing: 0; }
.column-menu { background: #fff; border: 1px solid #d6dce5; border-radius: 10px; padding: 16px; max-width: min(360px, 90vw); box-shadow: 0 8px 28px #182b491f; color: #253248; }
.column-presets { display: flex; gap: 6px; }
.column-menu p { font-size: 12px; color: #64748b; margin: 12px 0; }
.column-options { display: grid; max-height: 280px; overflow-y: auto; gap: 4px; }
.column-options label { display: flex; align-items: center; gap: 10px; padding: 7px 4px; font-size: 13px; cursor: pointer; }
.column-options input { width: 16px; height: 16px; accent-color: #3e63dd; }
.results-table { font-family: var(--font-family-body, inherit); }
:deep(.results-table) { background: #fff; border: 1px solid var(--workspace-outline, #d6dce5); border-radius: 12px; overflow: hidden; box-shadow: none; font-size: 13px; }
:deep(.results-table .v-table__wrapper) {
    overflow-x: auto;
    border-top: 1px solid var(--workspace-outline, #d6dce5);
    background: #fff;
}
:deep(.results-table .v-table__wrapper > table) {
    width: 100%;
    min-width: var(--results-table-min-width);
    table-layout: fixed;
    border-spacing: 0;
}
:deep(.results-table .v-table__wrapper > table > thead > tr > th) {
    height: 40px;
    padding: 10px 22px;
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.035em;
    line-height: 1.4;
    color: #525866;
    background: #f1f4f8;
    white-space: normal;
    overflow-wrap: anywhere;
    border-bottom: 1px solid var(--workspace-outline, #d6dce5);
}
:deep(.results-table .v-table__wrapper > table > tbody > tr > td) {
    height: 44px;
    padding: 11px 22px;
    font-size: 13px;
    font-weight: 400;
    line-height: 1.6;
    color: #202b3c;
    vertical-align: top;
    white-space: normal;
    overflow-wrap: anywhere;
    border-bottom: 1px solid #e4e9f0;
}
:deep(.results-table tbody > tr:nth-child(even)) { background: #fff; }
:deep(.results-table tbody > tr:hover) { background: #f3f6fc; }
:deep(.results-table tbody > tr:hover > td:first-child) { box-shadow: inset 2px 0 #7694df; }
:deep(.results-table .v-data-table__th--sorted) { color: #3d61ac; }
:deep(.results-table tbody > tr:last-child > td) { border-bottom: 0; }
:deep(.results-table .v-data-table-footer) {
    padding: 8px 16px;
    font-size: 13px;
    background: #fff;
    border-top: 1px solid var(--workspace-outline, #d6dce5);
    gap: 4px 12px;
}
:deep(.results-table .v-data-table-footer .v-field__input) { font-size: 13px; }
:deep(.results-table .v-data-table-footer__items-per-page) { margin-inline-end: auto; gap: 10px; color: #5f6b7a; }
:deep(.results-table .v-data-table-footer .v-field) { border-radius: 8px; background: #f8fafc; }
:deep(.results-table .v-data-table-footer .v-field__outline) { color: #aebcd0; --v-field-border-opacity: 1; }
:deep(.results-table .v-data-table-footer .v-field__input) { min-height: 32px; padding-top: 4px; padding-bottom: 4px; }
:deep(.results-table .v-data-table-footer__info) { color: #657188; font-variant-numeric: tabular-nums; }
:deep(.results-table .v-data-table-footer .v-btn) { width: 30px; height: 30px; border-radius: 7px; }
:deep(.results-table .v-data-table-footer .v-btn:not(:disabled)) { border: 1px solid #b8c2cf; color: #596b89; }
:deep(.results-table .v-data-table-footer .v-btn .v-icon) { font-size: 19px; }

/* Compact markdown styling - text-first results */
.markdown-shell {
    width: 100%;
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    padding: 8px 0;
    font-family: var(--font-family-body);
}

.markdown-content {
    width: 100%;
    max-width: none;
    margin: 0;
    padding: 0;
    line-height: 1.78;
    font-size: 16px;
    color: #0f172a;
    overflow-wrap: anywhere;
    background: transparent;
    border-radius: 0;
    border: 0;
    box-shadow: none;
    animation: fade-in-up 0.4s ease-out;
    font-family: inherit;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(p),
.markdown-content :deep(ul),
.markdown-content :deep(ol),
.markdown-content :deep(li),
.markdown-content :deep(strong),
.markdown-content :deep(em),
.markdown-content :deep(blockquote),
.markdown-content :deep(a),
.markdown-content :deep(table),
.markdown-content :deep(th),
.markdown-content :deep(td) {
    font-family: inherit;
}

@keyframes fade-in-up {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Markdown answers should read like assistant prose, not boxed reports */
.markdown-content :deep(h1),
.markdown-content :deep(h2) {
    margin: 0 0 0.9rem;
    font-weight: 650;
    color: #0f172a;
    line-height: 1.15;
    letter-spacing: -0.025em;
}

.markdown-content :deep(h1) {
    font-size: 1.7rem;
}

.markdown-content :deep(h2) {
    font-size: 1.45rem;
}

.markdown-content :deep(h3),
.markdown-content :deep(h4) {
    margin: 1.35rem 0 0.45rem;
    font-size: 0.82rem;
    font-weight: 700;
    color: #475569;
    line-height: 1.35;
    letter-spacing: 0.08em;
}

.markdown-content :deep(h1:first-child),
.markdown-content :deep(h2:first-child),
.markdown-content :deep(h3:first-child),
.markdown-content :deep(h4:first-child),
.markdown-content :deep(p:first-child) {
    margin-top: 0;
}

.markdown-content :deep(h1 + p),
.markdown-content :deep(h2 + p) {
    margin-top: 0;
    margin-bottom: 1rem;
    font-size: 1.04rem;
    line-height: 1.75;
    color: #334155;
}

/* Tighter paragraph and list spacing */
.markdown-content :deep(p),
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
    margin: 0.72rem 0;
}

/* Compact lists without extra spacing */
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
    padding-left: 1.15rem;
}

.markdown-content :deep(li) {
    margin: 0.34rem 0;
    padding-left: 0.15rem;
    line-height: 1.65;
}

.markdown-content :deep(li::marker) {
    color: #64748b;
}

.markdown-content :deep(ul ul),
.markdown-content :deep(ul ol) {
    margin-top: 0.2rem;
  margin-bottom: 0;
  padding-left: 1rem;
}

.markdown-content :deep(li li) {
    margin: 0.18rem 0;
}

.markdown-content :deep(li:last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(strong) {
    font-weight: 650;
    color: #0f172a;
}

/* Keep bold labels inline so they do not render as fake report headings */
.markdown-content :deep(p strong),
.markdown-content :deep(li strong) {
    display: inline;
    padding: 0;
    margin: 0;
    border: 0;
}

/* Modern code styling - slightly darker background to stand out */
.markdown-content :deep(code) {
    background: #f8fafc;
    padding: 0.18em 0.42em;
    border-radius: 6px;
  font-family: 'SF Mono', 'Courier New', monospace;
  font-size: 0.9em;
    color: var(--primary);
    border: 1px solid rgba(var(--primary-rgb), 0.1);
}

.markdown-content :deep(pre) {
    background: #f8fafc;
    padding: 0.95em 1rem;
    border-radius: 12px;
  overflow-x: auto;
    margin: 1em 0;
    border: 1px solid rgba(148, 163, 184, 0.2);
    box-shadow: none;
}

/* Enhanced table styling */
.markdown-content :deep(table) {
    border-collapse: separate;
    border-spacing: 0;
  width: 100%;
    margin: 1em 0;
  font-size: 0.95em;
    box-shadow: none;
    border-radius: 12px;
  overflow: hidden;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: #ffffff;
}

.markdown-content :deep(th) {
    background-color: #f8fafc;
    font-weight: 600;
    color: #475569;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    padding: 10px 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.72rem;
}

.markdown-content :deep(td) {
    border-bottom: 1px solid rgba(148, 163, 184, 0.14);
    padding: 10px 12px;
  background-color: #fff;
}

.markdown-content :deep(tr:last-child td) {
    border-bottom: 0;
}

/* Remove special background for first paragraph */
.markdown-content :deep(p):first-of-type {
    font-weight: 400;
  padding: 0;
  margin-bottom: 1rem;
  border: none;
  background-color: transparent;
}

/* Fix adjacent list spacing */
.markdown-content :deep(ul + p),
.markdown-content :deep(ol + p) {
    margin-top: 0.8rem;
}

.markdown-content :deep(blockquote) {
    margin: 1rem 0;
    padding: 0.15rem 0 0.15rem 1rem;
    border-left: 2px solid rgba(var(--primary-rgb), 0.2);
    color: #334155;
    background: rgba(var(--primary-rgb), 0.04);
    border-radius: 0 10px 10px 0;
}

/* Clean links */
.markdown-content :deep(a) {
    color: var(--primary);
  text-decoration: none;
  transition: color 0.2s ease;
}

.markdown-content :deep(a:hover) {
  text-decoration: underline;
    color: var(--primary-hover);
}

/* Container when inside cards or boxes */
.final-results .markdown-shell {
    padding: 24px 28px;
}

/* Responsive adjustments */
@container (max-width: 900px) {
    .table-header-container { grid-template-columns: minmax(0, 1fr); gap: 12px; }
    .results-tools { grid-column: 1; grid-row: 2; }
    .preview-description { grid-column: 1; grid-row: 2; }
    .table-header-container.is-preview .results-tools { grid-row: 3; }
    .table-action { grid-column: 1; grid-row: 4; }
    .table-action .saved-results-btn { width: 100%; }
}

@media (max-width: 992px) {
    .table-header-container { grid-template-columns: minmax(0, 1fr); gap: 12px; }
    .results-tools { grid-column: 1; grid-row: 2; }
    .preview-description { grid-column: 1; grid-row: 2; }
    .table-header-container.is-preview .results-tools { grid-row: 3; }
    .table-action { grid-column: 1; grid-row: 4; }
    .table-action .saved-results-btn { width: 100%; }




}

@media (max-width: 768px) {
    .markdown-shell {
        padding: 20px 18px;
    }



    .markdown-content {
        max-width: 100%;
        font-size: 15px;
        line-height: 1.72;
    }

    .markdown-content :deep(h1) {
        font-size: 1.48rem;
    }

    .markdown-content :deep(h2) {
        font-size: 1.28rem;
    }

    .search-field {
        min-width: 0;
        flex: 1;
    }
}

@media (max-width: 480px) {
    .table-header-container { padding: 14px; }
    .results-title { gap: 7px; }
    .markdown-shell {
        padding: 18px 14px;
        border-radius: 12px;
    }





    .search-field {
        width: 100%;
    }
}
</style>
