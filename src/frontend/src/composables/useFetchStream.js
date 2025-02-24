import { ref } from "vue";

const CONFIG = {
    CONNECTION_TIMEOUT: 5000, // 5 seconds for initial connection
    CHUNK_TIMEOUT: 10000, // 10 seconds between chunks
    TOTAL_TIMEOUT: 300000, // 5 minutes total stream time
};

export function useFetchStream() {
    const isLoading = ref(false);
    const error = ref(null);

    const streamFetch = async (url, options = {}) => {
        isLoading.value = true;
        error.value = null;
        const startTime = Date.now();

        // Setup connection timeout
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
                    let lastChunkTime = Date.now();

                    try {
                        while (true) {
                            // Check total stream duration
                            if (Date.now() - startTime > CONFIG.TOTAL_TIMEOUT) {
                                throw new Error(
                                    `Stream exceeded maximum duration of ${CONFIG.TOTAL_TIMEOUT / 1000} seconds`
                                );
                            }

                            const { value, done } = await reader.read();
                            if (done) break;

                            // Check chunk timeout
                            const now = Date.now();
                            if (now - lastChunkTime > CONFIG.CHUNK_TIMEOUT) {
                                throw new Error(`No data received for ${CONFIG.CHUNK_TIMEOUT / 1000} seconds`);
                            }

                            lastChunkTime = now;
                            const chunk = decoder.decode(value);
                            yield JSON.parse(chunk);
                        }
                    } catch (e) {
                        error.value = e;
                        throw e;
                    } finally {
                        reader.releaseLock();
                    }
                },

                abort() {
                    controller.abort();
                    reader.cancel();
                },
            };
        } catch (e) {
            error.value = e.name === "AbortError" ? new Error("Connection timeout") : e;
            throw error.value;
        } finally {
            isLoading.value = false;
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
        error,
        streamFetch,
        postStream,
    };
}
