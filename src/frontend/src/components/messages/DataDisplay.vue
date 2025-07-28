<template>
    <div class="data-display">
        <!-- Text Message Display -->
        <div v-if="isTextData" class="markdown-content" v-html="renderedMarkdown"></div>

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
                                        <span v-if="hasLastSyncTimestamp">Last Updated: {{ getLastSyncTime }}</span>
                                        <span v-else-if="isRealtimeMode">Realtime Mode</span>
                                        <span v-else>Last Updated: {{ getLastSyncTime }}</span>
                                    </div>
                                </div>

                                <div class="right-section">
                                    <!--<div class="results-count" v-if="displayedItems.length">
                                        {{ displayedItems.length }} {{ displayedItems.length === 1 ? 'result' :
                                        'results' }}
                                    </div>-->

                                    <v-text-field v-model="search" density="comfortable" hide-details
                                        placeholder="Search results" prepend-inner-icon="mdi-magnify" single-line
                                        clearable variant="outlined" class="search-field"></v-text-field>
                                </div>
                            </div>
                        </div>
                        <!-- Remove the info-row div completely -->
                    </div>
                </template>
            </v-data-table>
        </div>

        <!-- No Results Message -->
        <div v-else-if="!loading && !displayedItems.length && !isTextData && !isJsonData && !isError"
            class="no-results">
            <v-icon icon="mdi-information-outline" color="#4C64E2" size="large" class="mb-3"></v-icon>
            <div class="no-results-message">No results found</div>
            <div class="no-results-hint">Try adjusting your query or search terms</div>
        </div>
    </div>
</template>

<script setup>
import { marked } from 'marked'
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { MessageType } from './messageTypes'
import { isRealtimeMode } from '@/state/chatMode.js'

const clearSearch = () => {
    search.value = ''
}

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
    // Fix line breaks in the middle of sentences (before lists and sections)
    .replace(/([a-zA-Z0-9.,:;)"])\n\n([0-9]+\.\s+)/g, '$1\n\n$2')
    // Fix line breaks in the middle of paragraphs
    .replace(/([a-zA-Z0-9.,;:)])(\n)([a-zA-Z0-9(])/g, '$1 $3')
    // Fix extra line breaks between list items
    .replace(/\n{3,}/g, '\n\n');
    
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
    props.type === MessageType.MARKDOWN ||
    (typeof props.content === 'object' && props.content?.type === 'text')
)

const displayedItems = computed(() => {
    if (props.type === MessageType.STREAM || props.type === MessageType.BATCH || props.type === MessageType.TABLE) {
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

// Check if we have a valid last sync timestamp in metadata
const hasLastSyncTimestamp = computed(() => {
    try {
        // Ensure props and metadata exist
        if (!props || !props.metadata) {
            return false;
        }
        
        // Check for last_sync data in metadata
        if (props.metadata.last_sync) {
            const lastSync = props.metadata.last_sync;
            
            // Check if it's a valid timestamp (not error states)
            if (typeof lastSync === 'object' && lastSync && lastSync.last_sync) {
                const timestampValue = lastSync.last_sync;
                const result = timestampValue && 
                       timestampValue !== 'Never' && 
                       timestampValue !== 'Error' && 
                       timestampValue !== 'No data';
                return result;
            } else if (typeof lastSync === 'string') {
                const result = lastSync && 
                       lastSync !== 'Never' && 
                       lastSync !== 'Error' && 
                       lastSync !== 'No data';
                return result;
            }
        }
        
        return false;
    } catch (error) {
        console.warn('Error in hasLastSyncTimestamp computed:', error);
        return false;
    }
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
    transition: all 0.2s ease;
    margin-right: 10px;
}

.download-btn:hover {
    background: #f0f4ff !important;
    transform: translateY(-1px);
    box-shadow: 0 2px 5px rgba(76, 100, 226, 0.1);
}

.sync-info {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #444;
    font-size: 0.813rem;
    white-space: nowrap;
    padding: 4px 8px;
    background: rgba(76, 100, 226, 0.04);
    border-radius: 4px;
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
    border-radius: 12px;
    /* Increased from 8px for more modern look */
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
    border-bottom: 1px solid rgba(245, 247, 255, 0.5);
    /* More subtle */
}

/* Simplified Pagination */
:deep(.v-data-table-footer) {
    padding: 6px 8px;
    border-top: 1px solid #eef1ff;
}

/* Compact markdown styling with consistent background */
.markdown-content {
  padding: 16px;
  line-height: 1.5;
  font-size: 14px;
  color: #374151;
  width: 100%;
  overflow-wrap: break-word;
  background-color: #f8fafc; /* Consistent light background for entire content */
  border-radius: 8px;
  border: 1px solid #edf2f7;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}

/* Headings with modern styling */
.markdown-content :deep(h1), 
.markdown-content :deep(h2), 
.markdown-content :deep(h3), 
.markdown-content :deep(h4) {
  margin: 1rem 0 0.5rem;
  font-weight: 500;
  color: #1f2937;
  line-height: 1.3;
}

.markdown-content :deep(h3) {
  font-size: 1.15rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid #e5e7eb;
}

/* Tighter paragraph and list spacing */
.markdown-content :deep(p), 
.markdown-content :deep(ul), 
.markdown-content :deep(ol) {
  margin-bottom: 0.6rem;
  margin-top: 0.4rem;
}

/* Compact lists without extra spacing */
.markdown-content :deep(ul), 
.markdown-content :deep(ol) {
  padding-left: 1.25rem;
  margin-top: 0.3rem;
  margin-bottom: 0.5rem;
}

/* Fix spacing between main list items (users) */
.markdown-content :deep(ul > li) {
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
}

/* First user shouldn't have top margin */
.markdown-content :deep(ul > li:first-child) {
  margin-top: 0;
}

/* Fix nested list spacing */
.markdown-content :deep(ul ul),
.markdown-content :deep(ul ol) {
  margin-top: 0.1rem;
  margin-bottom: 0;
  padding-left: 1rem;
}

/* Reduce spacing in nested list items */
.markdown-content :deep(li li) {
  margin: 0.1rem 0;
}

/* Default list item spacing */
.markdown-content :deep(li) {
  margin-bottom: 0.2rem;
  line-height: 1.4;
}

.markdown-content :deep(li:last-child) {
  margin-bottom: 0;
}

/* User listing specific styling */
.markdown-content :deep(li strong) {
  display: inline-block;
  padding-bottom: 0.1rem;
}

/* Modern code styling - slightly darker background to stand out */
.markdown-content :deep(code) {
  background: #f1f5f9;
  padding: 0.2em 0.4em;
  border-radius: 4px;
  font-family: 'SF Mono', 'Courier New', monospace;
  font-size: 0.9em;
  color: #4C64E2;
  border: 1px solid rgba(76, 100, 226, 0.1);
}

.markdown-content :deep(pre) {
  background: #f1f5f9;
  padding: 0.8em;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.8em 0;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Enhanced table styling */
.markdown-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.8em 0;
  font-size: 0.95em;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  border-radius: 8px;
  overflow: hidden;
}

.markdown-content :deep(th) {
  background-color: #f1f5f9;
  font-weight: 500;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
}

.markdown-content :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  background-color: #fff;
}

/* Remove special background for first paragraph */
.markdown-content :deep(p):first-of-type {
  font-weight: 500;
  padding: 0;
  margin-bottom: 1rem;
  border: none;
  background-color: transparent;
}

.markdown-content :deep(p) strong {
  font-weight: 600;
  color: #1f2937;
  display: block;
  margin-top: 0.8rem;
  margin-bottom: 0.3rem;
  padding-bottom: 0.2rem;
  border-bottom: 1px solid #e5e7eb;
}

/* Fix adjacent list spacing */
.markdown-content :deep(ul) + :deep(p),
.markdown-content :deep(ol) + :deep(p) {
  margin-top: 0.6rem;
}

/* Clean links */
.markdown-content :deep(a) {
  color: #4C64E2;
  text-decoration: none;
  transition: color 0.2s ease;
}

.markdown-content :deep(a:hover) {
  text-decoration: underline;
  color: #3b4fc1;
}

/* Container when inside cards or boxes */
.final-results .markdown-content {
    padding: 8px 16px;
    /* Adjusted padding when inside result cards */
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