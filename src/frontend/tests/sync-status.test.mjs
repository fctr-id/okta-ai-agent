import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

test('sync failures remain visible without advancing the last successful timestamp', async (t) => {
    const server = await createServer({
        configFile: false, envFile: false,
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false },
    })
    let state
    let response
    t.mock.method(globalThis, 'fetch', async () => ({ json: async () => response }))
    try {
        const { useSync } = await server.ssrLoadModule('/src/composables/useSync.js')
        await renderToString(createSSRApp({
            setup() { state = useSync(); return () => h('div') },
        }))
        response = {
            status: 'failed', error_details: 'Page fetch failed',
            end_time: '2026-09-19T15:00:00+00:00',
            last_successful_sync_time: '2026-09-19T14:00:00+00:00',
            entity_counts: { users: 320, groups: 283, applications: 33, policies: 12, devices: 4 },
        }
        await state.checkSyncStatus()
        assert.equal(state.syncStatus.value, 'failed')
        assert.equal(state.syncError.value, 'Page fetch failed')
        assert.equal(state.isSyncing.value, false)
        assert.equal(state.entityCounts.value.users, 320)
        assert.equal(state.lastSyncTime.value.toISOString(), '2026-09-19T14:00:00.000Z')

        response = { ...response, last_successful_sync_time: null }
        await state.checkSyncStatus()
        assert.equal(state.lastSyncTime.value, null)

        response = { ...response, status: 'completed', error_details: null,
            last_successful_sync_time: '2026-09-19T15:30:00' }
        await state.checkSyncStatus()
        assert.equal(state.syncError.value, null)
        assert.equal(state.lastSyncTime.value.toISOString(), '2026-09-19T15:30:00.000Z')
    } finally {
        state?.stopPolling()
        await server.close()
    }
})
