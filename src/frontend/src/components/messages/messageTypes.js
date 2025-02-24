export const MessageType = {
    STREAM: 'stream',  // For SQL streaming results
    JSON: 'json',      // For API JSON responses
    ERROR: 'error'     // For error handling
}

export const createMessage = (type, content, metadata = {}) => ({
    type,
    content,
    metadata
})