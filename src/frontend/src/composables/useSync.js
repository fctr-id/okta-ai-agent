import { ref, onMounted, onBeforeUnmount } from "vue";
import { useFetchStream } from "./useFetchStream";
import { useAuth } from "./useAuth";


/**
 * Composable for managing Okta data synchronization
 */
export function useSync() {
    const { streamFetch } = useFetchStream();
    const auth = useAuth();

    // State
    const isSyncing = ref(false);
    const syncStatus = ref("none");
    const syncProgress = ref(0);
    const lastSyncTime = ref(null);
    const entityCounts = ref({
        users: 0,
        groups: 0,
        applications: 0,
        policies: 0,
    });
    const syncError = ref(null);

    // Polling and stall detection
    let pollingInterval = null;
    let stallCheckInterval = null;
    const POLL_INTERVAL = 15000;
    const STALL_TIMEOUT = 10 * 60 * 1000; // 10 minutes without changes
    let lastEntityCountChange = null;
    let previousCounts = { users: 0, groups: 0, applications: 0, policies: 0 };

    /**
     * Parse a UTC timestamp string from the server
     * We need to add 'Z' to indicate it's UTC time
     */
    const parseUtcTimestamp = (timestamp) => {
        if (!timestamp) return null;

        // If timestamp doesn't end with Z, add it to make JavaScript interpret it as UTC
        const utcTimeStr = timestamp.endsWith("Z") ? timestamp : timestamp + "Z";
        return new Date(utcTimeStr);
    };

    /**
     * Check if the sync is stalled (no entity count changes for 10 minutes)
     */
    const checkForStall = () => {
        if (isSyncing.value && lastEntityCountChange) {
            const idleTime = Date.now() - lastEntityCountChange;

            // If stalled for too long, cancel the sync
            if (idleTime > STALL_TIMEOUT) {
                console.warn(`Sync appears stalled (no changes for ${Math.round(idleTime / 60000)} minutes)`);
                syncError.value = "Sync timed out - no data changes for 10 minutes";
                cancelSync();
            }
        }
    };

    const startPolling = () => {
        if (!pollingInterval) {
            console.log("Starting sync status polling");
            lastEntityCountChange = Date.now(); // Initialize timestamp when polling starts
            checkSyncStatus();
            pollingInterval = setInterval(checkSyncStatus, POLL_INTERVAL);

            // Check for stalls every minute
            stallCheckInterval = setInterval(checkForStall, 60000);
        }
    };

    const stopPolling = () => {
        if (pollingInterval) {
            console.log("Stopping sync status polling");
            clearInterval(pollingInterval);
            pollingInterval = null;
        }

        if (stallCheckInterval) {
            clearInterval(stallCheckInterval);
            stallCheckInterval = null;
        }
    };

    const handleAuthError = async (status) => {
        if (status === 401 || status === 403) {
            console.warn(`Authentication error (${status}), redirecting to login`);
            stopPolling();
            
            try {
                // Use the proper logout method from auth composable
                await auth.logout();
                
                // After logout completes, force navigation
                setTimeout(() => {
                    window.location.href = '/login';
                }, 100);
            } catch (error) {
                console.error("Error during logout:", error);
                // Force navigation even if logout fails
                window.location.href = '/login';
            }
            return true;
        }
        return false;
    };

    const checkSyncStatus = async () => {
        try {
            const response = await fetch("/api/sync/status");
            const data = await response.json();

            syncStatus.value = data.status;
            syncProgress.value = data.progress || 0;

            // Check if entity counts have changed
            if (data.entity_counts) {
                const hasChanged =
                    data.entity_counts.users !== previousCounts.users ||
                    data.entity_counts.groups !== previousCounts.groups ||
                    data.entity_counts.applications !== previousCounts.applications ||
                    data.entity_counts.policies !== previousCounts.policies;

                // If counts changed, update the timestamp
                if (hasChanged) {
                    //console.log("Entity counts changed, updating timestamp");
                    lastEntityCountChange = Date.now();
                    previousCounts = { ...data.entity_counts };
                }

                entityCounts.value = data.entity_counts;
            }

            // Parse timestamps as UTC
            if (data.end_time) {
                lastSyncTime.value = parseUtcTimestamp(data.end_time);
            } else if (data.start_time && data.status === "completed") {
                lastSyncTime.value = parseUtcTimestamp(data.start_time);
            }

            isSyncing.value = data.status === "running" || data.status === "idle";

            if (["completed", "failed", "canceled"].includes(data.status)) {
                stopPolling();
            }

            return data;
        } catch (error) {
            syncError.value = "Failed to check sync status";
            console.error("Error checking sync status:", error);
            return null;
        }
    };

    const startSync = async () => {
        try {
            syncError.value = null;
            const response = await fetch("/api/sync/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            if (response.status === 401 || response.status === 403) {
                await handleAuthError(response.status);
                return null;
            }
            const data = await response.json();

            if (data.status === "started" || data.status === "already_running") {
                isSyncing.value = true;
                syncStatus.value = "running";
                startPolling();
            } else {
                syncError.value = data.message || "Failed to start sync";
            }

            return data;
        } catch (error) {
            syncError.value = "Failed to start sync";
            console.error("Error starting sync:", error);
            return null;
        }
    };

    const cancelSync = async () => {
        try {
            syncError.value = null;
            const response = await fetch("/api/sync/cancel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });

            const data = await response.json();

            if (data.status === "canceled") {
                isSyncing.value = false;
                syncStatus.value = "canceled";
                stopPolling();
            } else {
                syncError.value = data.message || "Failed to cancel sync";
            }

            return data;
        } catch (error) {
            syncError.value = "Failed to cancel sync";
            console.error("Error canceling sync:", error);
            return null;
        }
    };

    /**
     * Format last sync time for display
     */
    const formattedLastSyncTime = () => {
        if (!lastSyncTime.value) return "Never";

        const date = lastSyncTime.value;

        // Format month as 3-letter abbreviation
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const month = months[date.getMonth()];

        // Format day
        const day = date.getDate();

        // Get year
        const year = date.getFullYear();

        // Format time as HH:MM AM/PM
        let hours = date.getHours();
        const ampm = hours >= 12 ? "PM" : "AM";
        hours = hours % 12;
        hours = hours ? hours : 12; // Convert 0 to 12
        const minutes = date.getMinutes().toString().padStart(2, "0");

        // Put it all together
        const formattedTime = `${month} ${day}, ${year} at ${hours}:${minutes} ${ampm}`;

        return formattedTime;
    };

    // Set up initial status check when component is mounted
    onMounted(() => {
        checkSyncStatus().then((data) => {
            // Only start polling if we're currently syncing
            if (data && (data.status === "running" || data.status === "idle")) {
                startPolling();
            }
        });
    });

    // Clean up on unmount
    onBeforeUnmount(() => {
        stopPolling();
    });

    return {
        isSyncing,
        syncStatus,
        syncProgress,
        lastSyncTime,
        entityCounts,
        syncError,
        startSync,
        cancelSync,
        checkSyncStatus,
        startPolling,
        stopPolling,
        formattedLastSyncTime,
    };
}
