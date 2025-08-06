export const MessageType = {
    STREAM: 'stream',      // For SQL streaming results
    JSON: 'json',         // For API JSON responses
    ERROR: 'error',       // For error handling
    TEXT: 'text',        // For simple text messages
    BATCH: 'batch',      // For batch data chunks
    METADATA: 'metadata', // For stream metadata
    COMPLETE: 'complete', // For stream completion
    TABLE: 'table',       // For table display with Vuetify data table
    MARKDOWN: 'markdown'  // For markdown content display
}

export const createMessage = (type, content, metadata = {}) => ({
    type,
    content,
    metadata,
    timestamp: new Date().toISOString()
})

export const createBatchMessage = (content, batchInfo) => ({
    type: MessageType.BATCH,
    content,
    metadata: {
        batchNumber: batchInfo.batch_number,
        startIndex: batchInfo.start_index,
        endIndex: batchInfo.end_index,
        batchSize: batchInfo.batch_size
    },
    timestamp: new Date().toISOString()
})

export const createMetadataMessage = (metadata) => ({
    type: MessageType.METADATA,
    content: [],
    metadata: {
        totalRecords: metadata.total_records,
        totalBatches: metadata.total_batches,
        batchSize: metadata.batch_size,
        query: metadata.query,
        sql: metadata.sql,
        explanation: metadata.explanation,
        lastSync: metadata.last_sync,
        headers: metadata.headers
    },
    timestamp: new Date().toISOString()
})

export const createCompleteMessage = (summary) => ({
    type: MessageType.COMPLETE,
    content: null,
    metadata: {
        totalRecords: summary.total_records,
        completedAt: summary.timestamp
    },
    timestamp: new Date().toISOString()
})