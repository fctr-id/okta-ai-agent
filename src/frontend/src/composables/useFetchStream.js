import { ref } from "vue";

const CONFIG = {
    CONNECTION_TIMEOUT: 10000,  // Keep initial connection timeout
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
        isLoading.value = true;
        error.value = null;
        // Reset stream tracking values
        isStreaming.value = false;
        progress.value = 0;
        totalBatches.value = 0;
        currentBatch.value = 0;
        
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

            if (!response.ok) {
                throw new Error(`Server error: ${response.status} ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            return {
                async *getStream() {
                    try {
                        while (true) {
                            // Only keep the total timeout check as a safety valve
                            if (Date.now() - startTime > CONFIG.TOTAL_TIMEOUT) {
                                throw new Error(`Request timed out after ${CONFIG.TOTAL_TIMEOUT / 1000} seconds`);
                            }

                            const { value, done } = await reader.read();
                            if (done) {
                                break;
                            }

                            // Combine partial chunk with new data and split by newlines
                            const chunkText = decoder.decode(value, { stream: true });
                            const chunks = (partialChunk + chunkText).split("\n");
                            
                            // Process all complete chunks
                            partialChunk = chunks.pop() || "";
                            
                            for (const chunk of chunks) {
                                if (chunk.trim()) {
                                    try {
                                        const parsedChunk = JSON.parse(chunk);
                                        
                                        // Handle metadata to start streaming state
                                        if (parsedChunk.type === 'metadata' && parsedChunk.content) {
                                            isStreaming.value = true;
                                            totalBatches.value = parsedChunk.content.total_batches || 0;
                                        }
                                        
                                        // Handle batch data to update progress
                                        if (parsedChunk.type === 'batch' && parsedChunk.metadata) {
                                            currentBatch.value = parsedChunk.metadata.batch_number || 0;
                                            if (totalBatches.value > 0) {
                                                progress.value = Math.floor((currentBatch.value / totalBatches.value) * 100);
                                            }
                                        }
                                        
                                        // Handle completion
                                        if (parsedChunk.type === 'complete') {
                                            progress.value = 100;
                                        }
                                        
                                        yield parsedChunk;
                                    } catch (e) {
                                        console.error('Failed to parse JSON chunk:', e);
                                        yield { type: 'error', content: 'Failed to parse response' };
                                    }
                                }
                            }
                        }
                    } catch (e) {
                        if (e.name === 'AbortError') {
                            console.log('Stream aborted by user');
                        } else {
                            console.error('Stream error:', e);
                            error.value = e;
                        }
                    } finally {
                        isLoading.value = false;
                        isStreaming.value = false;
                    }
                },

                abort() {
                    controller.abort();
                    if (reader) {
                        reader.cancel().catch(e => console.error('Error cancelling reader:', e));
                    }
                    error.value = new Error("Stream aborted");
                    isLoading.value = false;
                    isStreaming.value = false;
                    progress.value = 0;
                },
            };
        } catch (e) {
            error.value = e.name === "AbortError" ? new Error("Connection timeout") : e;
            isLoading.value = false;
            isStreaming.value = false;
            progress.value = 0;
            throw error.value;
        }
    };

    const postStream = (url, data) => {
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
