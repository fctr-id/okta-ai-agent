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
        isReceivingChunks: false
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

        // Initialize with only the two sentinel steps:
        // 1. thinking (pre-plan entity relevance selection)
        // 2. finalizing_results (will activate after all execution steps complete)
        execution.steps = [
            {
                id: 'thinking',
                tool_name: 'thinking',
                reason: 'Pre-plan analysis (entity relevance selection)',
                status: 'active', // Start with thinking step active
            },
            {
                id: 'finalizing_results',
                tool_name: 'finalizing_results', 
                reason: 'Processing and formatting final results',
                status: 'pending',
            }
        ];

        // Internal timing flags no longer needed (thinking persists until planning_start)
        execution._thinkingStartedAt = undefined;
        execution._thinkingRenamed = false;
        if (execution._pendingRenameTimeout) {
            clearTimeout(execution._pendingRenameTimeout);
            execution._pendingRenameTimeout = null;
        }

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
                        case 'error':
                            // console.log("Handling error event");
                            handleErrorEvent(event);
                            break;
                        case 'metadata':
                            // console.log("Handling metadata event - start of chunked streaming");
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
            // Only rename sentinel when actual planning starts
            if (content.status === 'planning_start' && execution.steps[0] && execution.steps[0].id === 'thinking') {
                execution.planningStarted = true;
                execution.status = 'planning';
                // Immediately rename on true planning start
                execution.steps[0].id = 'generating_steps';
                execution.steps[0].tool_name = 'generating_steps';
                execution.steps[0].reason = 'Generating execution steps';
                execution._thinkingRenamed = true;
            }

            // If we receive explicit planning_complete before plan event, mark sentinel completed
            if (content.status === 'planning_complete' && execution.steps[0] && ['generating_steps','thinking','generate_plan'].includes(execution.steps[0].id)) {
                // If rename was deferred and not yet applied, apply now before completing
                // If still thinking (edge case), rename before marking completed
                if (execution.steps[0].id === 'thinking') {
                    execution.steps[0].id = 'generating_steps';
                    execution.steps[0].tool_name = 'generating_steps';
                    execution.steps[0].reason = 'Generating execution steps';
                    execution._thinkingRenamed = true;
                }
                // Ensure it shows final planning state label
                if (execution.steps[0].id !== 'generating_steps') {
                    execution.steps[0].id = 'generating_steps';
                    execution.steps[0].tool_name = 'generating_steps';
                    execution.steps[0].reason = 'Generating execution steps';
                }
                if (execution.steps[0].status !== 'completed') {
                    execution.steps[0].status = 'completed';
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

            // Handle Modern Execution Manager format
            if (content.step_number !== undefined && content.step_name && content.status) {
                // console.log(`Processing step ${content.step_number}: ${content.step_name} - ${content.status}`);
                // Map step numbers to our inserted steps (accounting for generate_plan at index 0)
                // Backend step 1 -> frontend index 1 (after generate_plan)
                const stepIndex = content.step_number; // Keep 1-based since generate_plan is at index 0
                
                if (stepIndex >= 1 && stepIndex < execution.steps.length - 1) { // Exclude finalizing_results (last step)
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
                    
                    // Check if all execution steps are completed (excluding bookends)
                    if (content.status === 'completed') {
                        const executionSteps = execution.steps.slice(1, -1); // Exclude generate_plan and finalizing_results
                        const allExecutionStepsCompleted = executionSteps.every(step => step.status === 'completed');
                        
                        if (allExecutionStepsCompleted) {
                            // All execution steps are done, activate finalizing_results
                            const finalizingStepIndex = execution.steps.length - 1;
                            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                                execution.steps[finalizingStepIndex].status = 'active';
                                execution.currentStepIndex = finalizingStepIndex;
                            }
                        }
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
                
                // Complete the planning sentinel step (could be 'generate_plan' or 'generating_steps' after rename)
                if (execution.steps[0] && ['generate_plan','generating_steps','thinking'].includes(execution.steps[0].id)) {
                    // Ensure it shows as the final planning state name
                    if (execution.steps[0].id !== 'generating_steps') {
                        execution.steps[0].id = 'generating_steps';
                        execution.steps[0].tool_name = 'generating_steps';
                        execution.steps[0].reason = 'Generating execution steps';
                    }
                    execution.steps[0].status = 'completed';
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

                // Insert the new steps between generate_plan (index 0) and finalizing_results (last)
                const generatePlanStep = execution.steps[0];
                const finalizingResultsStep = execution.steps[execution.steps.length - 1];
                
                execution.steps = [
                    generatePlanStep,
                    ...newExecutionSteps,
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
        // console.log("handleFinalResultEvent called with:", event.data);
        try {
            const data = JSON.parse(event.data);
            const content = data.content;
            // console.log("Final result content:", content);
            
            // If we're receiving chunks, this might be the final completion signal
            if (chunkedResults.value.isReceivingChunks) {
                // console.log("Received final_result during chunked streaming - completing");

                // Force completion of chunked streaming
                execution.results.metadata.isStreaming = false;
                delete execution.results.metadata.streamingProgress;
                
                // Complete the finalizing step
                const finalizingStepIndex = execution.steps.length - 1;
                if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                    execution.steps[finalizingStepIndex].status = 'completed';
                }
                
                execution.status = "completed";
                isProcessing.value = false;
                isStreaming.value = false;
                chunkedResults.value.isReceivingChunks = false;
                
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
            
            // Activate the finalizing_results step (last step)
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
            const content = data.content || {};
            
            // console.log(`[handleChunkedMetadata] Starting chunked streaming with ${content.total_batches} batches`);
            
            // Initialize chunked result state
            chunkedResults.value = {
                chunks: [],
                expectedChunks: content.total_batches || 0,
                receivedChunks: 0,
                totalRecords: 0, // Will be updated when we get first batch
                isReceivingChunks: true,
                baseData: data // Store metadata for final assembly
            };
            
            // Activate the finalizing_results step
            const finalizingStepIndex = execution.steps.length - 1;
            if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                execution.steps[finalizingStepIndex].status = 'active';
                execution.currentStepIndex = finalizingStepIndex;
            }
            
            // Show initial empty table with streaming indicator
            execution.results = {
                content: [], // Start with empty array
                display_type: content.display_type || "table",
                headers: [], // Will be updated when we get first batch
                metadata: {
                    isStreaming: true,
                    streamingProgress: {
                        current: 0,
                        total: 0, // Will be updated
                        chunksReceived: 0,
                        totalChunks: content.total_batches || 0
                    }
                }
            };
        } catch (err) {
            // console.error("[handleChunkedMetadata] Error processing metadata:", err);
        }
    };

    /**
     * Handle chunked streaming batch events (unified format)
     */
    const handleChunkedBatch = (event) => {
        try {
            const data = JSON.parse(event.data);
            const content = data.content || {};
            const metadata = data.metadata || {};
            
            // console.log(`[handleChunkedBatch] Received batch ${metadata.batch_number}/${metadata.total_batches}`);
            
            // Add chunk data to existing results
            if (content.formatted_response?.content) {
                // First batch - set up headers and total records
                if (metadata.batch_number === 1) {
                    const formattedResponse = content.formatted_response;
                    execution.results.headers = formattedResponse.headers || [];
                    chunkedResults.value.totalRecords = content.chunk_info?.total_size || 0;
                    
                    // Update total in streaming progress
                    execution.results.metadata.streamingProgress.total = chunkedResults.value.totalRecords;
                }
                
                chunkedResults.value.chunks.push(...content.formatted_response.content);
                chunkedResults.value.receivedChunks++;
                
                // Update the table content in real-time
                execution.results.content = [...chunkedResults.value.chunks]; // Spread to trigger reactivity
                
                // Update streaming progress
                execution.results.metadata.streamingProgress = {
                    current: chunkedResults.value.chunks.length,
                    total: chunkedResults.value.totalRecords,
                    chunksReceived: chunkedResults.value.receivedChunks,
                    totalChunks: chunkedResults.value.expectedChunks
                };
                
                console.log(`[handleChunkedBatch] Updated table: ${chunkedResults.value.chunks.length}/${chunkedResults.value.totalRecords} records`);
            }
            
            // Check if this is the final batch
            if (metadata.is_final || chunkedResults.value.receivedChunks >= chunkedResults.value.expectedChunks) {
                // console.log(`[handleChunkedBatch] All batches received, completing streaming`);
                
                // Mark streaming as complete
                execution.results.metadata.isStreaming = false;
                delete execution.results.metadata.streamingProgress;
                
                // Complete the finalizing_results step
                setTimeout(() => {
                    const finalizingStepIndex = execution.steps.length - 1;
                    if (execution.steps[finalizingStepIndex] && execution.steps[finalizingStepIndex].id === 'finalizing_results') {
                        execution.steps[finalizingStepIndex].status = 'completed';
                    }
                    
                    execution.status = "completed";
                    isProcessing.value = false;
                    isStreaming.value = false;
                    
                    // Close EventSource after completion
                    if (activeEventSource.value) {
                        activeEventSource.value.close();
                        activeEventSource.value = null;
                    }
                }, 300);
                
                // Reset chunk state
                chunkedResults.value.isReceivingChunks = false;
            }
        } catch (err) {
            // console.error("[handleChunkedBatch] Error processing batch:", err);
            
            // Reset chunk state on error
            chunkedResults.value.isReceivingChunks = false;
            execution.status = "error";
            error.value = "Failed to process chunked response";
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
    };
}