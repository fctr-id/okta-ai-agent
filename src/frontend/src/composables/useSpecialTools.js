/**
 * Special Tools Composable
 * 
 * Handles fetching and caching of special tools metadata from the backend.
 * Tools are discovered dynamically - no hardcoded tool names.
 * 
 * Usage:
 * const { tools, loading, error, fetchTools } = useSpecialTools()
 * await fetchTools() // Call on component mount
 */

import { ref } from 'vue'

// Shared state across all components (cached)
const tools = ref([])
const loading = ref(false)
const error = ref(null)
let fetched = false // Track if we've fetched already

export function useSpecialTools() {
    /**
     * Fetch special tools from backend API
     * Only fetches once, subsequent calls return cached data
     */
    const fetchTools = async () => {
        // Return cached data if already fetched
        if (fetched && tools.value.length > 0) {
            return
        }

        loading.value = true
        error.value = null

        try {
            const response = await fetch('/api/react/special-tools', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include' // Include auth cookie
            })

            if (!response.ok) {
                throw new Error(`Failed to fetch special tools: ${response.status}`)
            }

            const data = await response.json()

            if (data.success && data.tools) {
                tools.value = data.tools
                fetched = true
            } else {
                throw new Error('Invalid response format from server')
            }
        } catch (err) {
            error.value = err.message
            console.error('Error fetching special tools:', err)
        } finally {
            loading.value = false
        }
    }

    /**
     * Clear cached tools (useful for logout/refresh)
     */
    const clearCache = () => {
        tools.value = []
        fetched = false
        error.value = null
    }

    return {
        tools,
        loading,
        error,
        fetchTools,
        clearCache
    }
}
