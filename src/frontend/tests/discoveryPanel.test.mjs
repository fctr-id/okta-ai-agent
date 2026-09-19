import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

test('activity hides internal reasoning and preserves actual endpoint statuses', async () => {
    const server = await createServer({
        configFile: false, envFile: false, plugins: [vue()],
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false },
    })
    try {
        const { default: DiscoveryPanel } = await server.ssrLoadModule('/src/components/messages/DiscoveryPanel.vue')
        const html = await renderToString(createSSRApp({ render: () => h(DiscoveryPanel, {
            isComplete: true,
            steps: [{ text: 'PRIVATE_STEP_TEXT', title: 'PRIVATE_STEP_TITLE', reasoning: 'PRIVATE_REASONING', tools: [{
                testId: 'test-a', description: 'Fetch user groups and roles', requests: [
                    { id: '1', operation: 'user.list_groups', status: 'success' },
                    { id: '2', operation: 'user.list_roles', status: 'failed' },
                    { id: '3', operation: 'application.list', status: 'empty' },
                ],
            }] }],
        }) }))
        assert.match(html, /user.list_groups/)
        assert.match(html, /Returned data/)
        assert.match(html, /user.list_roles/)
        assert.match(html, /Failed/)
        assert.match(html, /No data/)
        assert.match(html, />Activity</)
        assert.match(html, /aria-expanded="false"/)
        assert.match(html, /1 failed attempt/)
        assert.doesNotMatch(html, /PRIVATE_/)
        assert.doesNotMatch(html, /Testing<\/span>/)

        const working = await renderToString(createSSRApp({ render: () => h(DiscoveryPanel, {
            steps: [{ text: 'PRIVATE_HISTORY_TEXT', tools: [] }],
        }) }))
        assert.match(working, /aria-expanded="true"/)
        assert.match(working, /Preparing your request/)
        assert.doesNotMatch(working, /PRIVATE_/)

        const descriptions = await renderToString(createSSRApp({ render: () => h(DiscoveryPanel, {
            steps: [{ tools: [
                { name: 'get_sql_context', description: 'Inspect application fields' },
                { name: 'unknown', description: 'Read saved retrieval results' },
            ] }],
        }) }))
        assert.match(descriptions, /Read database schema/)
        assert.match(descriptions, /Inspect application fields/)
        assert.match(descriptions, /Read saved retrieval results/)
        assert.doesNotMatch(descriptions, />unknown</)

        const { default: ExecutionPanel } = await server.ssrLoadModule('/src/components/messages/ExecutionPanel.vue')
        const execution = await renderToString(createSSRApp({ render: () => h(ExecutionPanel, {
            executionStarted: true, isComplete: true, executionError: 'Fixture execution failed',
        }) }))
        assert.match(execution, /aria-expanded="true"/)
        assert.match(execution, /Execution failed/)
        assert.doesNotMatch(execution, /Script executed successfully/)

        const stopped = await renderToString(createSSRApp({ render: () => h(DiscoveryPanel, {
            isComplete: true, error: 'Request failed',
        }) }))
        assert.match(stopped, /aria-expanded="true"/)
        assert.match(stopped, /Stopped/)
        assert.match(stopped, /Request failed/)
    } finally {
        await server.close()
    }
})
