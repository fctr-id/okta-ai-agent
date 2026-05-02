import { ref } from 'vue'
import { useAuth } from './useAuth'

export function useHistory() {
    const auth = useAuth()
    const history = ref([])
    const favorites = ref([])
    const sessions = ref([])
    const loading = ref(false)
    const error = ref(null)
    const sessionsLoading = ref(false)
    const sessionsError = ref(null)

    const handleAuthError = async (response) => {
        if (response.status !== 401 && response.status !== 403) {
            return false
        }

        try {
            await auth.logout()
        } finally {
            window.location.href = '/login'
        }

        return true
    }

    const ensureOk = async (response, fallbackMessage) => {
        if (await handleAuthError(response)) {
            throw new Error('Session expired')
        }

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}))
            throw new Error(payload.detail || fallbackMessage)
        }

        return response
    }

    const fetchHistory = async () => {
        loading.value = true
        error.value = null
        try {
            // Add timestamp to prevent browser caching
            const response = await fetch(`/api/history/?_t=${Date.now()}`)
            await ensureOk(response, 'Failed to fetch history')
            history.value = await response.json()
        } catch (err) {
            error.value = err.message
        } finally {
            loading.value = false
        }
    }

    const fetchSessions = async (options = {}) => {
        const {
            limit = 10,
            includeArchived = false
        } = options

        sessionsLoading.value = true
        sessionsError.value = null

        try {
            const params = new URLSearchParams({
                limit: String(limit),
                include_archived: includeArchived ? 'true' : 'false',
                _t: String(Date.now())
            })
            const response = await fetch(`/api/sessions/?${params.toString()}`)
            await ensureOk(response, 'Failed to fetch sessions')
            sessions.value = await response.json()
            return sessions.value
        } catch (err) {
            sessionsError.value = err.message
            return []
        } finally {
            sessionsLoading.value = false
        }
    }

    const createSession = async (payload = {}) => {
        sessionsError.value = null
        try {
            const response = await fetch('/api/sessions/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            await ensureOk(response, 'Failed to create session')
            const session = await response.json()
            await fetchSessions()
            return session
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const fetchSessionDetail = async (sessionId, options = {}) => {
        const {
            turnLimit = 100
        } = options

        sessionsError.value = null
        try {
            const params = new URLSearchParams({
                turn_limit: String(turnLimit),
                _t: String(Date.now())
            })
            const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}?${params.toString()}`)
            await ensureOk(response, 'Failed to fetch session detail')
            return await response.json()
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const fetchTurnDetail = async (sessionId, turnNumber) => {
        sessionsError.value = null
        try {
            const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/turns/${turnNumber}?_t=${Date.now()}`)
            await ensureOk(response, 'Failed to fetch conversation turn')
            return await response.json()
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const fetchTurnResultPreview = async (sessionId, turnNumber) => {
        sessionsError.value = null
        try {
            const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/turns/${turnNumber}/result-preview?_t=${Date.now()}`)
            await ensureOk(response, 'Failed to fetch saved result preview')
            return await response.json()
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const fetchTurnResultFull = async (sessionId, turnNumber) => {
        sessionsError.value = null
        try {
            const params = new URLSearchParams({
                _t: String(Date.now())
            })

            const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/turns/${turnNumber}/result-full?${params.toString()}`)
            await ensureOk(response, 'Failed to fetch saved full result')
            return await response.json()
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const updateSession = async (sessionId, updates) => {
        sessionsError.value = null
        try {
            const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            })
            await ensureOk(response, 'Failed to update session')
            const session = await response.json()
            await fetchSessions()
            return session
        } catch (err) {
            sessionsError.value = err.message
            throw err
        }
    }

    const fetchFavorites = async () => {
        loading.value = true
        error.value = null
        try {
            const response = await fetch('/api/history/favorites')
            await ensureOk(response, 'Failed to fetch favorites')
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
            await ensureOk(response, 'Failed to save history')
            await fetchHistory()
        } catch (err) {
            console.error('Failed to save history:', err)
        }
    }

    const toggleFavorite = async (historyId, isFavorite) => {
        try {
            const response = await fetch(`/api/history/${historyId}/favorite?is_favorite=${isFavorite}`, {
                method: 'PATCH'
            })
            await ensureOk(response, 'Failed to toggle favorite')
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
        sessions,
        loading,
        error,
        sessionsLoading,
        sessionsError,
        fetchHistory,
        fetchFavorites,
        fetchSessions,
        createSession,
        fetchSessionDetail,
        fetchTurnDetail,
        fetchTurnResultPreview,
        fetchTurnResultFull,
        updateSession,
        saveToHistory,
        toggleFavorite
    }
}
