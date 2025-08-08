import { ref } from "vue";

const CONFIG = {
    CONNECTION_TIMEOUT: 60000,  // Keep initial connection timeout
    TOTAL_TIMEOUT: 300000,      // Keep total timeout as a safety measure
};

export function useFetchStream() {
    const isLoading = ref(false);
    const error = ref(null);
    // Add new reactive references for tracking stream progress
    const isStreaming = ref(false);
    const progress = ref(0);
    const totalBatches = ref(0);
    const currentBatch = ref(0);
    
    const streamFetch = async (url, options = {}) => {
        // console.log('🚀 streamFetch: Starting fetch to:', url);
        // console.log('🚀 streamFetch: Options:', options);
        
        isLoading.value = true;
        error.value = null;
        // Reset stream tracking values
        isStreaming.value = false;
        progress.value = 0;
        totalBatches.value = 0;
        currentBatch.value = 0;
        
        // console.log('🔄 streamFetch: Reset state - isLoading:', isLoading.value, 'isStreaming:', isStreaming.value);
        
        const startTime = Date.now();
        let partialChunk = "";

        const controller = new AbortController();
        const connectionTimeout = new Promise((_, reject) => {
            setTimeout(() => {
                controller.abort();
                reject(new Error(`Connection failed after ${CONFIG.CONNECTION_TIMEOUT / 1000} seconds`));
            }, CONFIG.CONNECTION_TIMEOUT);
        });

        try {
            // console.log('⏱️ streamFetch: Starting fetch race with timeout:', CONFIG.CONNECTION_TIMEOUT);
            const response = await Promise.race([
                fetch(url, {
                    ...options,
                    signal: controller.signal,
                    headers: {
                        "Content-Type": "application/json",
                        ...(options.headers || {}),
                    },
                }),
                connectionTimeout,
            ]);

            // console.log('✅ streamFetch: Fetch completed, response status:', response.status, response.statusText);
            if (!response.ok) {
                const errorMsg = `Server error: ${response.status} ${response.statusText}`;
                console.error('❌ streamFetch: Response not OK:', errorMsg);
                throw new Error(errorMsg);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            // console.log('📖 streamFetch: Stream reader created successfully');

            return {
                async *getStream() {
                    console.log('🌊 getStream: Starting stream processing');
                    let chunkCount = 0;
                    let eventCount = 0;
                    try {
                        while (true) {
                            // Only keep the total timeout check as a safety valve
                            if (Date.now() - startTime > CONFIG.TOTAL_TIMEOUT) {
                                const timeoutMsg = `Request timed out after ${CONFIG.TOTAL_TIMEOUT / 1000} seconds`;
                                console.error('⏰ getStream: Total timeout reached:', timeoutMsg);
                                throw new Error(timeoutMsg);
                            }

                            const { value, done } = await reader.read();
                            if (done) {
                                // console.log('🏁 getStream: Stream completed, total chunks processed:', chunkCount, 'events yielded:', eventCount);
                                break;
                            }

                            chunkCount++;
                            // Combine partial chunk with new data and split by newlines
                            const chunkText = decoder.decode(value, { stream: true });
                            const chunks = (partialChunk + chunkText).split("\n");
                            
                            // console.log(`📦 getStream: Chunk ${chunkCount} - ${chunks.length} lines, ${chunkText.length} chars`);
                            
                            // Process all complete chunks
                            partialChunk = chunks.pop() || "";
                            
                            for (const chunk of chunks) {
                                if (chunk.trim()) {
                                    try {
                                        const parsedChunk = JSON.parse(chunk);
                                        eventCount++;
                                        
                                        // console.log(`🎯 getStream: Event ${eventCount} - Type: ${parsedChunk.type}`, parsedChunk);
                                        
                                        // Handle metadata to start streaming state
                                        if (parsedChunk.type === 'metadata' && parsedChunk.content) {
                                            isStreaming.value = true;
                                            totalBatches.value = parsedChunk.content.total_batches || 0;
                                            // console.log('📊 getStream: Metadata received - streaming started, total batches:', totalBatches.value);
                                        }
                                        
                                        // Handle batch data to update progress
                                        if (parsedChunk.type === 'batch' && parsedChunk.metadata) {
                                            currentBatch.value = parsedChunk.metadata.batch_number || 0;
                                            if (totalBatches.value > 0) {
                                                progress.value = Math.floor((currentBatch.value / totalBatches.value) * 100);
                                            }
                                            // console.log(`📈 getStream: Batch ${currentBatch.value}/${totalBatches.value} - Progress: ${progress.value}%`);
                                        }
                                        
                                        // Handle completion
                                        if (parsedChunk.type === 'complete') {
                                            progress.value = 100;
                                            // console.log('🎉 getStream: Stream completion event received');
                                        }
                                        
                                        // Log critical events
                                        if (['error', 'complete', 'plan', 'status'].includes(parsedChunk.type)) {
                                            // console.log(`🔴 getStream: CRITICAL EVENT - ${parsedChunk.type}:`, parsedChunk.content);
                                        }
                                        
                                        yield parsedChunk;
                                    } catch (e) {
                                        console.error('❌ getStream: Failed to parse JSON chunk:', e, 'Raw chunk:', chunk);
                                        yield { type: 'error', content: 'Failed to parse response' };
                                    }
                                }
                            }
                        }
                    } catch (e) {
                        if (e.name === 'AbortError') {
                            // console.log('🛑 getStream: Stream aborted by user');
                        } else {
                            console.error('💥 getStream: Stream error:', e);
                            error.value = e;
                        }
                    } finally {
                        // console.log('🔧 getStream: Cleanup - setting isLoading=false, isStreaming=false');
                        isLoading.value = false;
                        isStreaming.value = false;
                    }
                },

                abort() {
                    // console.log('🛑 streamFetch: Abort called');
                    controller.abort();
                    if (reader) {
                        reader.cancel().catch(e => console.error('❌ streamFetch: Error cancelling reader:', e));
                    }
                    error.value = new Error("Stream aborted");
                    isLoading.value = false;
                    isStreaming.value = false;
                    progress.value = 0;
                    // console.log('🧹 streamFetch: Abort cleanup completed');
                },
            };
        } catch (e) {
            const errorMsg = e.name === "AbortError" ? "Connection timeout" : e.message;
            console.error('💥 streamFetch: Catch block - Error:', errorMsg, 'Original error:', e);
            error.value = e.name === "AbortError" ? new Error("Connection timeout") : e;
            isLoading.value = false;
            isStreaming.value = false;
            progress.value = 0;
            throw error.value;
        }
    };

    const postStream = (url, data) => {
        // console.log('📤 postStream: Posting to:', url, 'with data:', data);
        return streamFetch(url, {
            method: "POST",
            body: JSON.stringify(data),
        });
    };

    return {
        isLoading,
        isStreaming,
        progress,
        error,
        streamFetch,
        postStream,
    };
}
