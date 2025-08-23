import { ref, reactive, toRefs, watch } from "vue";
import { useAuth } from "./useAuth";

/**
 * Composable for handling realtime Server-Sent Events (SSE) streaming
 * Used to connect to the backend realtime API endpoints and process streaming updates
 * @returns {Object} Methods and reactive state for SSE connection management
 */
export function useRealtimeStream() {
    // Authentication service
    const auth = useAuth();

    // Chunked result state for large responses
    const chunkedResults = ref({
        chunks: [],
        expectedChunks: 0,
        receivedChunks: 0,
        totalRecords: 0,
        isReceivingChunks: false,
        baseData: null // Store metadata for final assembly
    });

    // Connection state
    const isLoading = ref(false);
    const isProcessing = ref(false);
    const isStreaming = ref(false);
    const error = ref(null);
    const activeEventSource = ref(null);
    const processId = ref(null);

    // Execution state tracking
    const execution = reactive({
        status: "idle", // idle, planning, executing, completed, error, cancelled
        planGenerated: false,
        currentStepIndex: -1,
        steps: [],
        results: null,
        currentPhase: "idle", // Track current execution phase for dynamic stepper updates
    });

    // NEW: Expansion Panel Data - standardized SSE events
    const expansionPanelData = reactive({
        visible: false,
        planData: null,
        stepDetails: [], // Array of step execution details with timing, progress, etc.
        currentStepExecution: null, // Current step being executed
    });

    /**
     * Start a new query process
     * @param {string} query - The natural language query to process
     * @returns {Promise<string|null>} - The process ID or null if failed
     */
    const startProcess = async (query) => {
        if (!query?.trim()) return null;

        // Reset state
        isLoading.value = true;
        isProcessing.value = true;
        isStreaming.value = false;
        error.value = null;
        execution.status = "planning";
        execution.planGenerated = false;
        execution.currentStepIndex = -1;
        execution.results = null;

        // Reset expansion panel data
        expansionPanelData.visible = false;
        expansionPanelData.planData = null;
        expansionPanelData.stepDetails = [];
        expansionPanelData.currentStepExecution = null;

        // Reset chunked results state
        chunkedResults.value = {
            chunks: [],
            expectedChunks: 0,
            receivedChunks: 0,
            totalRecords: 0,
            isReceivingChunks: false,
            baseData: null
        };

        // Initialize with three core steps:
        // 1. thinking (pre-plan entity relevance selection)
        // 2. generating_steps (plan generation)
        // 3. finalizing_results (will activate after all execution steps complete)
        execution.steps = [
            {
                id: 'thinking',
                tool_name: 'thinking',
                reason: 'Crafting optimal execution strategy',
                status: 'active', // Start with thinking step active
            },
            {
                id: 'generating_steps',
                tool_name: 'generating_steps',
                reason: 'Generating detailed execution plan',
                status: 'pending',
            },
            {
                id: 'finalizing_results',
                tool_name: 'finalizing_results', 
                reason: 'Finalizing and formatting results',
                status: 'pending',
            }
        ];

        try {
            const response = await fetch("/api/realtime/start-process", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                credentials: "include", // Include cookies for authentication
                body: JSON.stringify({ query: query.trim() }),
            });

            // Handle non-OK responses more explicitly
            if (!response.ok) {
                const errorText = await response.text();

                // Add explicit handling for 401 status
                if (response.status === 401) {
                    // console.log("Authentication expired, redirecting to login");
                    auth.logout(); // Update auth state
                    window.location = "/login"; // Force navigation to login
                    return null;
                }

                // Try to parse as JSON, fall back to text if that fails
                let errorMessage;
                try {
                    const errorData = JSON.parse(errorText);
                    errorMessage = errorData.detail || `Failed to start process: ${response.statusText}`;
                } catch (e) {
                    // If parsing fails, use the text directly
                    errorMessage = `Failed to start process: ${response.status} - ${errorText || response.statusText}`;
                }
                throw new Error(errorMessage);
            }

            // Parse successful response
            const data = await response.json();
            processId.value = data.process_id;

            if (data.plan) {
                // Don't override our bookend steps here - let step_plan_info handle the insertion
                execution.planGenerated = true;
            }

            return data.process_id;
        } catch (err) {
            console.error("Error in startProcess:", err);
            error.value = err.message || "Failed to start process";
            execution.status = "error";
            isProcessing.value = false;
            return null;
        } finally {
            isLoading.value = false;
        }
    };

    /**
     * Connect to the SSE stream for realtime updates
     * @param {string} id - The process ID to connect to
     * @returns {EventSource|null} - The EventSource instance or null if connection fails
     */
    const connectToStream = async (id) => {
        if (!id) {
            console.error("No process ID provided for stream connection");
            return null;
        }

        try {
            // Close any existing connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }

            // Create new EventSource connection
            const eventSourceUrl = `/api/realtime/stream-updates/${id}`;

            // Create EventSource - cookies will be sent automatically
            const eventSource = new EventSource(eventSourceUrl, {
                withCredentials: true, // This ensures cookies are sent with the request
            });
            activeEventSource.value = eventSource;
            isStreaming.value = true;

            // Handle connection open event
            eventSource.onopen = () => {
                execution.status = execution.planGenerated ? "executing" : "planning";
            };

            // Handle all messages with unified JSON format {type: "...", content: {...}}
            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    
                    // Route messages based on the unified 'type' field
                    switch (data.type) {
                        // NEW STANDARDIZED EVENTS - Complete SSE System
                        case 'PLAN-GENERATED':
                            handlePlanGeneratedEvent(event);
                            break;
                        case 'STEP-START':
                            handleStepStartEvent(event);
                            break;
                        case 'STEP-END':
                            handleStepEndEvent(event);
                            break;
                        case 'STEP-PROGRESS':
                            handleStepProgressEvent(event);
                            break;
                        case 'STEP-COUNT':
                            handleStepCountEvent(event);
                            break;
                        case 'STEP-TOKENS':
                            handleStepTokensEvent(event);
                            break;
                        case 'STEP-ERROR':
                            handleStepErrorEvent(event);
                            break;
                        case 'PLANNING-PHASE':
                            console.log(`🔍 DEBUG: PLANNING-PHASE case reached!`);
                            handlePlanningPhaseEvent(event);
                            break;
                        
                        // Essential UI events (kept for functionality)
                        case 'error':
                            handleErrorEvent(event);
                            break;
                        case 'metadata':
                            handleChunkedMetadata(event);
                            break;
                        case 'batch':
                            handleChunkedBatch(event);
                            break;
                        case 'complete':
                            handleFinalResultEvent(event);
                            break;
                        default:
                            break;
                    }
                } catch (err) {
                    console.error("Error parsing SSE message:", err, event.data);
                }
            };

            // Handle connection errors
            eventSource.onerror = (e) => {
                console.error("SSE connection error:", e);
                handleConnectionError(e, eventSource);
            };

            return eventSource;
        } catch (err) {
            console.error("Error connecting to event stream:", err);
            error.value = err.message || "Failed to connect to event stream. Please try again.";
            execution.status = "error";
            isStreaming.value = false;
            isProcessing.value = false;
            return null;
        }
    };

    /**
     * Handle final result events - Activate finalizing_results step and then complete
     */
    const handleFinalResultEvent = (event) => {
        // console.log("🎯 handleFinalResultEvent called with:", event.data);
        // console.log("🎯 chunkedResults.value.isReceivingChunks:", chunkedResults.value.isReceivingChunks);
        // console.log("🎯 execution.results exists:", !!execution.results);
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            // console.log("🎯 Final result content:", content);
            
            // If we're receiving chunks, this might be the final completion signal
            if (chunkedResults.value.isReceivingChunks || 
                (execution.results && execution.results.display_type === 'table' && Array.isArray(execution.results.content) && execution.results.content.length > 0)) {
                // console.log("🎯 handleFinalResultEvent: Detected table data exists - completing without overwriting results");

                // Force completion of chunked streaming WITHOUT overwriting execution.results
                // The chunked data is already properly set in execution.results
                if (execution.results && execution.results.metadata) {
                    execution.results.metadata.isStreaming = false;
                    delete execution.results.metadata.streamingProgress;
                }
                
                // Complete the finalizing step
                const finalizingStepIndex = execution.steps.length - 1;
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'completed';
                }
                
                execution.status = "completed";
                isProcessing.value = false;
                isStreaming.value = false;
                chunkedResults.value.isReceivingChunks = false;
                
                // console.log("🎯 handleFinalResultEvent: Table data preserved, streaming completed");
                
                // Close EventSource
                if (activeEventSource.value) {
                    activeEventSource.value.close();
                    activeEventSource.value = null;
                }
                return;
            }
            
            // Close EventSource for regular (non-chunked) results
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
            
            // SIMPLIFIED: Always activate and complete finalizing_results step
            // The backend controls execution steps, so when we get final results, we can safely finalize
            const finalizingStepIndex = execution.steps.length - 1;
            
            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                execution.steps[finalizingStepIndex].status = 'active';
                execution.currentStepIndex = finalizingStepIndex;
                // console.log("Activated finalizing_results step");
            }
            
            // Small delay to show the finalizing step as active, then complete it
            setTimeout(() => {
                // console.log("Completing finalizing step and setting results");
                // Complete the finalizing_results step
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'completed';
                }
                
                // The Results Formatter output is in content.formatted_response
                const formattedResponse = content.formatted_response || {};
                const agentDisplayMetadata = formattedResponse.metadata || content.metadata || content.display_hints || {};

                // Handle nested content structure from Modern Execution Manager
                let actualContent, actualMetadata;
                if (formattedResponse.content && typeof formattedResponse.content === 'object' && formattedResponse.content.content) {
                    // Nested structure: formatted_response.content.content contains the actual data
                    actualContent = formattedResponse.content.content;
                    actualMetadata = {
                        ...agentDisplayMetadata,
                        ...formattedResponse.content.metadata // Merge metadata from nested content
                    };
                    // console.log("Using nested content structure");
                } else {
                    // Flat structure
                    actualContent = formattedResponse.content || content.content || content.result_content || "";
                    actualMetadata = agentDisplayMetadata;
                    // console.log("Using flat content structure");
                }

                // Clean up malformed array data from backend
                if (Array.isArray(actualContent)) {
                    actualContent = actualContent.map(row => {
                        const cleanedRow = { ...row };
                        Object.keys(cleanedRow).forEach(key => {
                            const value = cleanedRow[key];
                            // Fix stringified empty arrays like ["[]"] -> []
                            if (Array.isArray(value) && value.length === 1 && value[0] === "[]") {
                                cleanedRow[key] = [];
                                console.log(`Fixed malformed array in ${key}: ["[]"] -> []`);
                            }
                            // Fix other stringified arrays like ["[\"item1\",\"item2\"]"] -> ["item1", "item2"]
                            else if (Array.isArray(value) && value.length === 1 && typeof value[0] === 'string' && value[0].startsWith('[')) {
                                try {
                                    cleanedRow[key] = JSON.parse(value[0]);
                                    console.log(`Fixed stringified array in ${key}:`, value[0], '->', cleanedRow[key]);
                                } catch (e) {
                                    console.warn(`Could not parse stringified array in ${key}:`, value[0]);
                                }
                            }
                        });
                        return cleanedRow;
                    });
                    // console.log("Cleaned content:", actualContent);
                }

                // Format the result to the expected shape for the frontend
                execution.results = {
                    content: actualContent,
                    display_type: formattedResponse.display_type || content.display_type || "markdown",
                    headers: actualMetadata.headers || formattedResponse.headers || [], // Include headers for Vuetify table display
                    metadata: actualMetadata, // This will now correctly pass headers, totalItems, etc.
                };

                // console.log("Final execution.results set:", execution.results);
                // console.log("execution.results.content:", execution.results.content);
                // console.log("execution.results.content as JSON:", JSON.stringify(execution.results.content, null, 2));
                // console.log("execution.results.display_type:", execution.results.display_type);
                // console.log("execution.results.metadata:", execution.results.metadata);
                // console.log("execution.results.metadata as JSON:", JSON.stringify(execution.results.metadata, null, 2));
                
                execution.status = content.status || "completed"; // Use status from content if available
                isProcessing.value = false;
                isStreaming.value = false; // Ensure streaming is also marked as false
                
            }, 500); // Show finalizing step as active for 500ms
            
        } catch (err) {
            console.error("Error processing final result event:", err);
            // Optionally, set an error state in the execution object
            execution.error = "Failed to process final result.";
            execution.status = "error";
            isProcessing.value = false;
            isStreaming.value = false;
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        }
    };

    /**
     * Handle chunked streaming metadata events (unified format)
     */
    const handleChunkedMetadata = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // console.log("📦 handleChunkedMetadata received:", content);

            chunkedResults.value.isReceivingChunks = true;
            chunkedResults.value.expectedChunks = content.total_batches || content.total_chunks || 0;
            chunkedResults.value.totalRecords = content.total_records || 0;
            chunkedResults.value.baseData = content.base_data; // Store base for final assembly

            // --- KEY CHANGE: Initialize results object immediately ---
            // This makes the table appear right away
            if (!execution.results) {
                // Handle case where base_data might be undefined
                const baseData = content.base_data || {};
                
                execution.results = {
                    display_type: content.display_type || 'table',
                    content: [], // Start with empty content
                    // Add streaming metadata for the UI - CRITICAL: Make this reactive
                    metadata: {
                        ...(baseData.metadata || {}),
                        isStreaming: true, // This should trigger table to show
                        streamingProgress: {
                            current: 0,
                            total: content.total_records || 0,
                            chunksReceived: 0,
                            totalChunks: content.total_batches || content.total_chunks || 0,
                        }
                    },
                    // Include any other properties from base_data if available
                    ...(baseData || {})
                };
                // console.log("📦 Initialized execution.results for streaming with isStreaming=true:", execution.results);
            }
            // ---------------------------------------------------------

        } catch (err) {
            console.error("Error handling chunked metadata:", err);
        }
    };

    /**
     * Handle chunked streaming batch events (unified format)
     */
    const handleChunkedBatch = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            const metadata = data.metadata || {};
            
            // Handle batch number from metadata
            const batchNumber = metadata.batch_number || (chunkedResults.value.receivedChunks + 1);
            
            // console.log(`📦 handleChunkedBatch received: batch ${batchNumber}/${chunkedResults.value.expectedChunks}`);

            // Ensure results object is initialized
            if (!execution.results) {
                console.warn("📦 Received batch before metadata. Initializing fallback structure.");
                execution.results = {
                    display_type: 'table',
                    content: [],
                    metadata: { 
                        isStreaming: true, 
                        streamingProgress: {
                            current: 0,
                            total: 0,
                            chunksReceived: 0,
                            totalChunks: 0
                        }
                    }
                };
            }

            // --- KEY CHANGE: Extract data from formatted_response structure ---
            let dataToAdd = [];
            
            // The backend sends the entire chunk object with formatted_response
            if (content && content.formatted_response && Array.isArray(content.formatted_response.content)) {
                dataToAdd = content.formatted_response.content;
                
                // If this is the first chunk and we haven't set up the base structure, do it now
                // BUT preserve the streaming metadata we set up in handleChunkedMetadata
                if (execution.results.content.length === 0 && content.formatted_response) {
                    const { content: chunkContent, metadata: baseMetadata, ...baseStructure } = content.formatted_response;
                    
                    // Preserve our streaming metadata while merging base structure
                    const currentStreamingMetadata = execution.results.metadata;
                    Object.assign(execution.results, baseStructure);
                    execution.results.content = []; // Ensure content starts as empty array
                    
                    // Merge base metadata but preserve streaming status
                    execution.results.metadata = {
                        ...(baseMetadata || {}),
                        ...currentStreamingMetadata, // Keep our streaming metadata
                        isStreaming: true, // Ensure streaming stays true
                    };
                    
                    // console.log("📦 Merged base structure while preserving streaming metadata:", execution.results.metadata);
                }
            } else if (Array.isArray(content)) {
                // Fallback for direct array content
                dataToAdd = content;
            }
            
            if (dataToAdd.length > 0) {
                // CRITICAL: Force Vue reactivity by creating a new array reference
                // This ensures Vue detects the change and re-renders the table
                const newContent = [...execution.results.content, ...dataToAdd];
                execution.results.content = newContent;
                // console.log(`📦 Added ${dataToAdd.length} records to results. Total: ${execution.results.content.length}`);
            } else {
                console.warn("📦 No data found in batch:", content);
            }
            // ---------------------------------------------------------------------

            // Update progress - Create new object for Vue reactivity
            if (execution.results.metadata?.streamingProgress) {
                execution.results.metadata.streamingProgress = {
                    ...execution.results.metadata.streamingProgress,
                    current: execution.results.content.length,
                    chunksReceived: batchNumber,
                };
                // console.log(`📦 Progress updated: ${execution.results.content.length}/${execution.results.metadata.streamingProgress.total} (${Math.round((execution.results.content.length / execution.results.metadata.streamingProgress.total) * 100)}%)`);
            }

            // CRITICAL: Ensure streaming status is maintained during batching
            if (execution.results.metadata) {
                execution.results.metadata.isStreaming = true; // Keep streaming true until all chunks received
            }

            // Update chunk tracking
            chunkedResults.value.receivedChunks = batchNumber;

            // If all chunks are received, mark streaming as complete in the metadata
            if (chunkedResults.value.receivedChunks >= chunkedResults.value.expectedChunks) {
                // console.log("📦 All chunks received, updating streaming status.");
                if (execution.results.metadata) {
                    execution.results.metadata.isStreaming = false;
                }
                chunkedResults.value.isReceivingChunks = false;
            }
        } catch (err) {
            console.error("Error handling chunked batch:", err);
        }
    };

    /**
     * Handle error events
     */
    const handleErrorEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            error.value = content.error || content.message || "An error occurred during execution";
            execution.status = "error";
            isProcessing.value = false;
            isStreaming.value = false;

            // Close the connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        } catch (err) {
            console.error("Error processing error event:", err);
        }
    };

    /**
     * Handle connection errors
     */
    const handleConnectionError = (e, eventSource) => {
        console.error("Connection error in EventSource:", e);

        // If we're already completed, cancelled, or have an error, this is expected connection closure
        // Also check if we have results (final processing phase) or finalizing_results step is active
        const finalizingStepIndex = execution.steps.length - 1;
        const isFinalizingActive = execution.steps[finalizingStepIndex]?.status === 'active' && 
                                   execution.steps[finalizingStepIndex]?.id === 'finalizing_results';
        
        // Special handling for chunked streaming completion
        if (chunkedResults.value.isReceivingChunks && chunkedResults.value.chunks.length > 0) {
            // console.log("[handleConnectionError] Connection closed during chunked streaming - attempting graceful completion");
            
            // Force completion of chunked streaming
            execution.results.metadata.isStreaming = false;
            delete execution.results.metadata.streamingProgress;
            
            // Complete the finalizing step
            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                execution.steps[finalizingStepIndex].status = 'completed';
            }
            
            execution.status = "completed";
            isProcessing.value = false;
            isStreaming.value = false;
            chunkedResults.value.isReceivingChunks = false;
            
            if (eventSource && activeEventSource.value) {
                eventSource.close();
                activeEventSource.value = null;
            }
            return;
        }
        
        if (execution.status === "completed" || 
            execution.status === "cancelled" || 
            execution.status === "error" ||
            execution.results !== null ||
            isFinalizingActive ||
            activeEventSource.value === null) { // Already closed by us
            if (eventSource && activeEventSource.value) {
                eventSource.close();
                activeEventSource.value = null;
            }
            return;
        }

        // Only treat as error if we're still processing
        error.value = "Connection to server lost. Please try your query again.";
        execution.status = "error";
        isProcessing.value = false;
        isStreaming.value = false;

        // Close the connection
        if (eventSource) {
            eventSource.close();
        }
        activeEventSource.value = null;
    };

    /**
     * Cancel an in-progress query
     * @returns {Promise<void>}
     */
    const cancelProcess = async () => {
        if (!processId.value) {
            console.warn("No process ID available to cancel");
            return;
        }

        try {

            const response = await fetch(`/api/realtime/cancel/${processId.value}`, {
                method: "POST",
                credentials: "include", // Include cookies for authentication
            });

            if (!response.ok) {
                // Silent fail for cancel requests
            }

            execution.status = "cancelled";
            isProcessing.value = false;
            isStreaming.value = false;

            // Close the connection
            if (activeEventSource.value) {
                activeEventSource.value.close();
                activeEventSource.value = null;
            }
        } catch (err) {
            // Silent fail for cancel errors
        }
    };

    /**
     * Clean up resources when component unmounts
     */
    const cleanup = () => {
        if (activeEventSource.value) {
            activeEventSource.value.close();
            activeEventSource.value = null;
        }
        isStreaming.value = false;
    };

    // Automatically clean up EventSource when process ID changes to null
    watch(
        () => processId.value,
        (newVal) => {
            if (!newVal && activeEventSource.value) {
                cleanup();
            }
        }
    );

    // Add watcher to track execution.results changes
    watch(() => execution.results, (newResults, oldResults) => {
        // console.log("🎯 execution.results changed:", {
        //     newExists: !!newResults,
        //     oldExists: !!oldResults,
        //     newType: newResults?.display_type,
        //     oldType: oldResults?.display_type,
        //     newContentLength: Array.isArray(newResults?.content) ? newResults.content.length : 'N/A',
        //     oldContentLength: Array.isArray(oldResults?.content) ? oldResults.content.length : 'N/A',
        //     newResults: newResults,
        //     oldResults: oldResults
        // });
    }, { deep: true });

    // ====== NEW STANDARDIZED EVENT HANDLERS FOR EXPANSION PANEL ======
    
    /**
     * Handle PLAN-GENERATED events - store plan data for expansion panel AND setup stepper
     */
    const handlePlanGeneratedEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Store plan data for expansion panel
            expansionPanelData.planData = {
                plan: content.plan,
                stepCount: content.step_count,
                formattedTime: content.formatted_time,
                estimatedDuration: content.estimated_duration
            };
            
            // Make expansion panel visible when we have plan data
            expansionPanelData.visible = true;
            
            // STEPPER MANAGEMENT: Setup stepper steps from plan data
            if (content.plan && content.plan.steps && Array.isArray(content.plan.steps)) {
                execution.planGenerated = true;
                
                // Complete the thinking and generating_steps sentinel steps
                if (execution.steps[0] && execution.steps[0].id === 'thinking') {
                    execution.steps[0].status = 'completed';
                }
                if (execution.steps[1] && execution.steps[1].id === 'generating_steps') {
                    execution.steps[1].status = 'completed';
                }

                // Create the new execution steps from the plan for the stepper
                const newExecutionSteps = content.plan.steps.map((step, index) => ({
                    id: step.step_index || index,
                    tool_name: step.tool_name || step.step_name,
                    reason: step.reason || step.step_name,
                    status: "pending",
                    operation: step.operation,
                    entity: step.entity
                }));

                // Insert new steps between thinking/generating_steps and finalizing_results
                execution.steps = [
                    execution.steps[0], // thinking
                    execution.steps[1], // generating_steps
                    ...newExecutionSteps,
                    execution.steps[execution.steps.length - 1] // finalizing_results
                ];

                execution.status = "executing";
            }
            
            console.log("📋 PLAN-GENERATED: Plan stored for expansion panel and stepper updated");
        } catch (err) {
            console.error("Error handling PLAN-GENERATED event:", err);
        }
    };

    /**
     * Handle STEP-START events - track step start timing AND update stepper status
     */
    const handleStepStartEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Update or create step detail record for expansion panel
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            const stepDetail = {
                stepNumber: content.step_number,
                stepType: content.step_type,
                stepName: content.step_name,
                queryContext: content.query_context,
                critical: content.critical,
                startTime: content.formatted_time,
                endTime: null,
                duration: null,
                success: null,
                recordCount: 0,
                progressPercentage: 0,
                progressDetails: '',
                inputTokens: 0,
                outputTokens: 0,
                errorMessage: null
            };
            
            if (stepDetailIndex >= 0) {
                // Update existing step
                expansionPanelData.stepDetails[stepDetailIndex] = {
                    ...expansionPanelData.stepDetails[stepDetailIndex],
                    ...stepDetail
                };
            } else {
                // Add new step
                expansionPanelData.stepDetails.push(stepDetail);
            }
            
            // Track current step being executed
            expansionPanelData.currentStepExecution = {
                stepNumber: content.step_number,
                stepType: content.step_type,
                stepName: content.step_name,
                startTime: content.formatted_time
            };
            
            // STEPPER MANAGEMENT: Update stepper step status to active
            const stepIndex = content.step_number + 1; // Offset for thinking + generating_steps
            if (stepIndex >= 2 && stepIndex < execution.steps.length - 1) {
                execution.steps[stepIndex].status = 'active';
                execution.currentStepIndex = stepIndex;
            }
            
            console.log(`🚀 STEP-START: Step ${content.step_number} (${content.step_type}) - ${content.step_name}`);
        } catch (err) {
            console.error("Error handling STEP-START event:", err);
        }
    };

    /**
     * Handle STEP-END events - track completion timing AND update stepper status
     */
    const handleStepEndEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Find and update the step detail for expansion panel
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            if (stepDetailIndex >= 0) {
                const stepDetail = expansionPanelData.stepDetails[stepDetailIndex];
                stepDetail.endTime = content.formatted_time;
                stepDetail.duration = content.duration_seconds;
                stepDetail.success = content.success;
                stepDetail.recordCount = content.record_count || stepDetail.recordCount;
                stepDetail.errorMessage = content.error_message;
                
                // Update the step detail in place for Vue reactivity
                expansionPanelData.stepDetails[stepDetailIndex] = { ...stepDetail };
            }
            
            // Clear current step execution if this matches
            if (expansionPanelData.currentStepExecution?.stepNumber === content.step_number) {
                expansionPanelData.currentStepExecution = null;
            }
            
            // STEPPER MANAGEMENT: Update stepper step status to completed/error
            const stepIndex = content.step_number + 1; // Offset for thinking + generating_steps
            if (stepIndex >= 2 && stepIndex < execution.steps.length - 1) {
                execution.steps[stepIndex].status = content.success ? 'completed' : 'error';
            }
            
            const status = content.success ? "SUCCESS" : "FAILED";
            console.log(`✅ STEP-END: Step ${content.step_number} - ${status} - ${content.duration_seconds?.toFixed(1)}s - ${content.record_count || 0} records`);
        } catch (err) {
            console.error("Error handling STEP-END event:", err);
        }
    };

    /**
     * Handle STEP-PROGRESS events - track API progress percentage
     */
    const handleStepProgressEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Find and update the step detail
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            if (stepDetailIndex >= 0) {
                const stepDetail = expansionPanelData.stepDetails[stepDetailIndex];
                stepDetail.progressPercentage = content.progress_percentage;
                stepDetail.progressDetails = content.message;  // Backend sends 'message', not 'details'
                
                // Update the step detail in place for Vue reactivity
                expansionPanelData.stepDetails[stepDetailIndex] = { ...stepDetail };
            }
            
            console.log(`📈 STEP-PROGRESS: Step ${content.step_number} - ${content.progress_percentage?.toFixed(1)}% - ${content.message}`);
        } catch (err) {
            console.error("Error handling STEP-PROGRESS event:", err);
        }
    };

    /**
     * Handle STEP-COUNT events - track record counts from operations
     */
    const handleStepCountEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Find and update the step detail
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            if (stepDetailIndex >= 0) {
                const stepDetail = expansionPanelData.stepDetails[stepDetailIndex];
                stepDetail.recordCount = content.record_count;
                
                // Update the step detail in place for Vue reactivity
                expansionPanelData.stepDetails[stepDetailIndex] = { ...stepDetail };
            }
            
            console.log(`📊 STEP-COUNT: Step ${content.step_number} - ${content.record_count} ${content.operation_type} records`);
        } catch (err) {
            console.error("Error handling STEP-COUNT event:", err);
        }
    };

    /**
     * Handle STEP-TOKENS events - track LLM token usage and costs
     */
    const handleStepTokensEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Find and update the step detail
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            if (stepDetailIndex >= 0) {
                const stepDetail = expansionPanelData.stepDetails[stepDetailIndex];
                stepDetail.inputTokens = content.input_tokens;
                stepDetail.outputTokens = content.output_tokens;
                // Note: total_cost removed to match execution_events_spec.md
                
                // Update the step detail in place for Vue reactivity
                expansionPanelData.stepDetails[stepDetailIndex] = { ...stepDetail };
            }
            
            const totalTokens = content.input_tokens + content.output_tokens;
            console.log(`🪙 STEP-TOKENS: Step ${content.step_number} - ${totalTokens} tokens (${content.agent_name})`);
        } catch (err) {
            console.error("Error handling STEP-TOKENS event:", err);
        }
    };

    /**
     * Handle STEP-ERROR events - track step-specific errors with retry options
     */
    const handleStepErrorEvent = (event) => {
        try {
            const content = event.content;
            
            // Find the step detail for this specific step
            const stepDetailIndex = expansionPanelData.stepDetails.findIndex(
                step => step.stepNumber === content.step_number
            );
            
            if (stepDetailIndex !== -1) {
                const stepDetail = expansionPanelData.stepDetails[stepDetailIndex];
                
                // Mark step as failed and add error information
                stepDetail.status = 'error';
                stepDetail.errorMessage = content.error_message;
                stepDetail.errorType = content.error_type;
                stepDetail.retryPossible = content.retry_possible;
                stepDetail.technicalDetails = content.technical_details;
                stepDetail.formattedTime = content.formatted_time;
                
                // Update the step detail in place for Vue reactivity
                expansionPanelData.stepDetails[stepDetailIndex] = { ...stepDetail };
            }
            
            const retryText = content.retry_possible ? " (Retry Possible)" : " (Retry Not Possible)";
            console.log(`❌ STEP-ERROR: Step ${content.step_number} - ${content.error_type}: ${content.error_message}${retryText}`);
        } catch (err) {
            console.error("Error handling STEP-ERROR event:", err);
        }
    };

    /**
     * Handle PLANNING-PHASE events - track planning phase transitions
     */
    const handlePlanningPhaseEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            
            // Update step statuses based on planning phase transitions
            if (content.phase === 'planning_start') {
                // Thinking phase completed, planning phase started
                const thinkingStep = execution.steps.find(step => step.id === 'thinking');
                const generatingStep = execution.steps.find(step => step.id === 'generating_steps');
                
                if (thinkingStep) thinkingStep.status = 'completed';
                if (generatingStep) generatingStep.status = 'active';
                
                execution.currentPhase = 'thinking';
                console.log("🧠 PLANNING-PHASE: Starting strategy analysis");
            } else if (content.phase === 'planning_complete') {
                // Planning phase completed
                const generatingStep = execution.steps.find(step => step.id === 'generating_steps');
                
                if (generatingStep) generatingStep.status = 'completed';
                
                execution.currentPhase = 'generating_steps';
                console.log("📋 PLANNING-PHASE: Generating execution plan");
            }
            
            console.log(`📋 PLANNING-PHASE: ${content.phase} at ${content.formatted_time}`);
        } catch (err) {
            console.error("Error handling PLANNING-PHASE event:", err);
        }
    };

    // ====== END OF NEW STANDARDIZED EVENT HANDLERS ======

    return {
        // State
        isLoading,
        isProcessing,
        isStreaming,
        error,
        processId,
        chunkedResults, // Expose chunked results state for progress tracking
        expansionPanelData, // NEW: Expansion panel data for detailed step tracking
        ...toRefs(execution), // Expose reactive execution state

        // Methods
        startProcess,
        connectToStream,
        cancelProcess,
        cleanup,
    };
}