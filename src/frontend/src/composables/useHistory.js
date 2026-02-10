import { ref } from 'vue'

export function useHistory() {
    const history = ref([])
    const favorites = ref([])
    const loading = ref(false)
    const error = ref(null)

    const fetchHistory = async () => {
        loading.value = true
        error.value = null
        try {
            // Add timestamp to prevent browser caching
            const response = await fetch(`/api/history/?_t=${Date.now()}`)
            if (!response.ok) throw new Error('Failed to fetch history')
            history.value = await response.json()
            console.log(`[useHistory] Fetched ${history.value.length} items`)
        } catch (err) {
            error.value = err.message
        } finally {
            loading.value = false
        }
    }

    const fetchFavorites = async () => {
        loading.value = true
        error.value = null
        try {
            const response = await fetch('/api/history/favorites')
            if (!response.ok) throw new Error('Failed to fetch favorites')
            favorites.value = await response.json()
        } catch (err) {
            error.value = err.message
        } finally {
            loading.value = false
        }
    }

    const saveToHistory = async (queryText, finalScript, resultsSummary) => {
        try {
            const response = await fetch('/api/history/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query_text: queryText,
                    final_script: finalScript,
                    results_summary: resultsSummary
                })
            })
            if (response.ok) {
                await fetchHistory()
            }
        } catch (err) {
            console.error('Failed to save history:', err)
        }
    }

    const toggleFavorite = async (historyId, isFavorite) => {
        try {
            const response = await fetch(`/api/history/${historyId}/favorite?is_favorite=${isFavorite}`, {
                method: 'PATCH'
            })
            if (!response.ok) {
                const data = await response.json()
                throw new Error(data.detail || 'Failed to toggle favorite')
            }
            await fetchHistory()
            await fetchFavorites()
            return true
        } catch (err) {
            error.value = err.message
            return false
        }
    }

    return {
        history,
        favorites,
        loading,
        error,
        fetchHistory,
        fetchFavorites,
        saveToHistory,
        toggleFavorite
    }
}
