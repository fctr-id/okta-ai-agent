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
    planningStarted: false,
    planningCompleted: false,
    });

    /**
     * Start a new query process
     * @param {string} query - The natural language query to process
     * @returns {Promise<string|null>} - The process ID or null if failed
     */
    const startProcess = async (query) => {
        if (!query?.trim()) return null;

        // console.log("🔄 startProcess: Starting new query - RESETTING ALL STATE");
        // console.log("🔄 startProcess: Previous state before reset:", {
        //     hasResults: !!execution.results,
        //     previousStatus: execution.status,
        //     isProcessing: isProcessing.value,
        //     isStreaming: isStreaming.value
        // });

        // Reset state
        isLoading.value = true;
        isProcessing.value = true;
        isStreaming.value = false;
        error.value = null;
        execution.status = "planning";
        execution.planGenerated = false;
        execution.currentStepIndex = -1;
        execution.results = null;

        // Reset chunked results state
        chunkedResults.value = {
            chunks: [],
            expectedChunks: 0,
            receivedChunks: 0,
            totalRecords: 0,
            isReceivingChunks: false
        };

        // console.log("🔄 startProcess: State after reset:", {
        //     hasResults: !!execution.results,
        //     newStatus: execution.status,
        //     isProcessing: isProcessing.value,
        //     isStreaming: isStreaming.value
        // });

        // Initialize with four sentinel steps:
        // 1. thinking (pre-plan entity relevance selection)
        // 2. generating_steps (plan generation)
        // 3. enriching_data (hidden step that appears before results formatting when triggered)
        // 4. finalizing_results (will activate after all execution steps complete)
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
                id: 'enriching_data',
                tool_name: 'enriching_data',
                reason: 'Enriching data with contextual insights',
                status: 'hidden', // Hidden by default, shown only when triggered
                hidden: true
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
                // console.log("SSE connection opened");
                execution.status = execution.planGenerated ? "executing" : "planning";
            };

            // Handle all messages with unified JSON format {type: "...", content: {...}}
            eventSource.onmessage = (event) => {
                // console.log("SSE Event received:", event.data);
                try {
                    const data = JSON.parse(event.data);
                    // console.log("Parsed SSE data:", data);
                    
                    // Route messages based on the unified 'type' field
                    switch (data.type) {
                        case 'status':
                            // console.log("Handling status event");
                            handlePlanStatusEvent(event);
                            break;
                        case 'plan':
                            // console.log("Handling plan event");
                            handleStepPlanInfoEvent(event);
                            break;
                        case 'step_status':
                            // console.log("Handling step_status event");
                            handleStepStatusEvent(event);
                            break;
                        case 'trigger_enriching_data':
                            // console.log("Handling trigger_enriching_data event");
                            triggerEnrichingData();
                            break;
                        case 'complete_enriching_data':
                            // console.log("Handling complete_enriching_data event");
                            completeEnrichingData();
                            break;
                        case 'error':
                            // console.log("Handling error event");
                            handleErrorEvent(event);
                            break;
                        case 'metadata':
                            handleChunkedMetadata(event);
                            break;
                        case 'batch':
                            // console.log("Handling batch event - chunked data batch");
                            handleChunkedBatch(event);
                            break;
                        case 'complete':
                            // console.log("Handling complete event");
                            handleFinalResultEvent(event);
                            break;
                        default:
                            // console.log("Unhandled message type:", data.type, data);
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
     * Handle plan status events
     */

    const handlePlanStatusEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            // Only activate generating_steps when actual planning starts
            if (content.status === 'planning_start' && execution.steps[0] && execution.steps[0].id === 'thinking') {
                execution.planningStarted = true;
                execution.status = 'planning';
                // Complete thinking step and activate generating_steps
                execution.steps[0].status = 'completed';
                if (execution.steps[1] && execution.steps[1].id === 'generating_steps') {
                    execution.steps[1].status = 'active';
                }
                execution._thinkingRenamed = true; // Keep flag for compatibility
            }

            // If we receive explicit planning_complete before plan event, mark generating_steps completed
            if (content.status === 'planning_complete' && execution.steps[1] && execution.steps[1].id === 'generating_steps') {
                // If thinking is still active (edge case), complete it first
                if (execution.steps[0] && execution.steps[0].id === 'thinking' && execution.steps[0].status === 'active') {
                    execution.steps[0].status = 'completed';
                    execution.steps[1].status = 'active';
                }
                // Complete the generating_steps step
                if (execution.steps[1].status !== 'completed') {
                    execution.steps[1].status = 'completed';
                }
                execution.planningCompleted = true;
            }

            // Handle rich plan details when available
            if (content.plan_details) {
                execution.planGenerated = true;
                const steps = content.plan_details.steps_summary || [];
                execution.steps = steps.map((step) => ({
                    id: step.step_index,
                    tool_name: step.tool_name,
                    reason: step.reason,
                    status: "pending",
                }));
                execution.status = "executing";
                return;
            }

            // Handle simpler plan status updates
            if (
                (content.status === "generated" ||
                 content.status === "starting_execution" ||
                 content.status === "running_execution") &&
                 // Avoid premature transition: require planning started + (plan data arrived or planning complete)
                 ((execution.planningStarted && execution.planningCompleted) || execution.planGenerated)
            ) {
                // Only switch to executing if we actually have a plan (plan event) OR got planning_complete
                execution.planGenerated = execution.planGenerated || execution.planningCompleted;
                execution.status = "executing";
            } else if (content.status === 'running_execution' && !execution.planningStarted) {
                // Backend may emit a generic running_execution early; treat as still planning
                execution.status = 'planning';
            }
        } catch (err) {
            console.error("Error processing plan status event:", err);
        }
    };

    /**
     * Handle step status update events
     */
    const handleStepStatusEvent = (event) => {
        // console.log("handleStepStatusEvent called with:", event.data);
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            // console.log("Step status content:", content);

            // Handle Modern Execution Manager format - Backend-driven step activation
            if (content.step_number !== undefined && content.step_name && content.status) {
                // console.log(`Processing step ${content.step_number}: ${content.step_name} - ${content.status}`);
                // Map step numbers to our inserted steps (accounting for thinking at index 0 and generating_steps at index 1)
                // Backend step 1 -> frontend index 2 (after thinking and generating_steps)
                const stepIndex = content.step_number + 1; // Offset by 2 (thinking + generating_steps), but step_number is 1-based
                
                if (stepIndex >= 2 && stepIndex < execution.steps.length - 1) { // Exclude finalizing_results (last step)
                    // Map backend status to frontend status
                    const statusMap = {
                        'running': 'active',
                        'completed': 'completed', 
                        'error': 'error'
                    };
                    
                    const frontendStatus = statusMap[content.status] || content.status;
                    execution.steps[stepIndex].status = frontendStatus;
                    
                    // Handle ERROR status - immediately stop execution and show error
                    if (content.status === 'error') {
                        console.error('Step failed:', content);
                        execution.status = "error";
                        execution.currentStepIndex = stepIndex;
                        
                        // Set error message for user display
                        const stepName = execution.steps[stepIndex].tool_name || `Step ${stepIndex}`;
                        error.value = `Execution failed at ${stepName}. The system encountered an error and cannot continue.`;
                        
                        // Mark remaining steps as disabled
                        for (let i = stepIndex + 1; i < execution.steps.length; i++) {
                            if (execution.steps[i].status === "pending" || execution.steps[i].status === "active") {
                                execution.steps[i].status = "pending";
                                execution.steps[i].disabled = true;
                            }
                        }
                        
                        // Stop processing
                        isProcessing.value = false;
                        isStreaming.value = false;
                        
                        return;
                    }
                    
                    // Update current step index if step is running
                    if (content.status === 'running') {
                        execution.currentStepIndex = stepIndex;
                        execution.status = "executing";
                    }
                    
                    // SIMPLIFIED: Let the backend completely control step activation
                    // Don't automatically activate finalizing_results here - let final result event handle it
                    // This prevents race condition where both enriching_data and finalizing_results become active
                    if (content.status === 'completed') {
                        // Just update the current step index, don't activate finalizing_results yet
                        // The backend will either:
                        // 1. Trigger enriching_data step, then send final results
                        // 2. Send final results directly (which activates finalizing_results)
                    }
                }
            }
        } catch (err) {
            console.error("Error processing step status event:", err);
        }
    };

    /**
     * Handle step plan info events - INSERT steps between generate_plan and finalizing_results
     */
    const handleStepPlanInfoEvent = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content;

            if (content.steps && Array.isArray(content.steps)) {
                execution.planGenerated = true;
                
                // Complete the thinking and generating_steps sentinel steps
                if (execution.steps[0] && execution.steps[0].id === 'thinking') {
                    execution.steps[0].status = 'completed';
                }
                if (execution.steps[1] && execution.steps[1].id === 'generating_steps') {
                    execution.steps[1].status = 'completed';
                }

                // Create the new execution steps from the plan
                const newExecutionSteps = content.steps.map((step, index) => {
                    const newStep = {
                        id: `step_${index + 1}`,
                        tool_name: step.tool_name,
                        operation: step.operation,
                        entity: step.entity,
                        reason: step.query_context || 'Processing data',
                        status: "pending",
                        critical: step.critical
                    };
                    return newStep;
                });

                // Insert the new steps between generating_steps (index 1) and the hidden steps (enriching_data, finalizing_results)
                const thinkingStep = execution.steps[0];
                const generatingStepsStep = execution.steps[1];
                const enrichingDataStep = execution.steps[2]; // Keep the hidden enriching_data step
                const finalizingResultsStep = execution.steps[3]; // finalizing_results is now at index 3
                
                execution.steps = [
                    thinkingStep,
                    generatingStepsStep,
                    ...newExecutionSteps,
                    enrichingDataStep, // Keep hidden until triggered
                    finalizingResultsStep
                ];

                execution.status = "executing";
            } else {
                // console.warn("[handleStepPlanInfoEvent] No valid steps array found in data:", data);
            }
        } catch (err) {
            console.error("[handleStepPlanInfoEvent] Error processing step plan info event:", err);
            console.error("[handleStepPlanInfoEvent] Event data:", event.data);
        }
    };

    // This function was redundant - chunked streaming is now handled by handleChunkedMetadata and handleChunkedBatch

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

    // This function was redundant - phase updates are handled by step_status events

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

    // This function was redundant - cancellation is handled by the main error handling

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

    /**
     * Trigger the enriching data step with animation
     * This makes the hidden step visible and activates it before results formatting
     */
    const triggerEnrichingData = () => {
        const enrichingStepIndex = execution.steps.findIndex(step => step.id === 'enriching_data');
        if (enrichingStepIndex !== -1 && execution.steps[enrichingStepIndex].hidden) {
            // Make the step visible and active
            execution.steps[enrichingStepIndex].hidden = false;
            execution.steps[enrichingStepIndex].status = 'active';
            execution.currentStepIndex = enrichingStepIndex;
        }
    };

    /**
     * Complete the enriching data step and move to finalizing results
     */
    const completeEnrichingData = () => {
        const enrichingStepIndex = execution.steps.findIndex(step => step.id === 'enriching_data');
        const finalizingStepIndex = execution.steps.findIndex(step => step.id === 'finalizing_results');
        
        if (enrichingStepIndex !== -1) {
            execution.steps[enrichingStepIndex].status = 'completed';
        }
        
        if (finalizingStepIndex !== -1) {
            execution.steps[finalizingStepIndex].status = 'active';
            execution.currentStepIndex = finalizingStepIndex;
        }
    };

    return {
        // State
        isLoading,
        isProcessing,
        isStreaming,
        error,
        processId,
        chunkedResults, // Expose chunked results state for progress tracking
        ...toRefs(execution), // Expose reactive execution state

        // Methods
        startProcess,
        connectToStream,
        cancelProcess,
        cleanup,
        triggerEnrichingData,
        completeEnrichingData,
    };
}