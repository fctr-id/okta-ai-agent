import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('follow-up phase events reach Activity without tools or internal reasoning', async (t) => {
    const server = await createServer({ configFile: false, envDir: false, plugins: [vue()],
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false } })
    t.mock.method(console, 'log', () => {})
    const previous = globalThis.EventSource
    let stream
    globalThis.EventSource = class {
        constructor() { stream = this }
        addEventListener() {}
        close() {}
    }
    try {
        const { useReactStream } = await server.ssrLoadModule('/src/composables/useReactStream.js')
        const { default: Activity } = await server.ssrLoadModule('/src/components/messages/DiscoveryPanel.vue')
        const state = useReactStream()
        await state.connectToStream('fixture')
        const render = () => renderToString(createSSRApp({ render: () => h(Activity, {
            steps: state.discoverySteps.value, isComplete: Boolean(state.results.value),
        }) }))
        for (const [phase, label] of [
            ['planning', 'Understanding your question'], ['processor', 'Processing saved results'],
            ['review', 'Planning next step'], ['analysis', 'Analyzing saved results'],
        ]) {
            stream.onmessage({ data: JSON.stringify({ type: 'STEP-START', phase, step: 1,
                title: 'PRIVATE_TITLE', text: 'PRIVATE_RESULT_SET_AND_REASONING', timestamp: 1 }) })
            const html = await render()
            assert.match(html, new RegExp(label))
            assert.match(html, /In progress/)
            assert.doesNotMatch(html, /Preparing your request|No tool calls recorded|PRIVATE_|tool call/)
        }
        // Tool calls stay beneath their phase instead of collecting at the bottom.
        const grouped = await renderToString(createSSRApp({ render: () => h(Activity, {
            steps: [
                { phase: 'planning', tools: [] },
                { phase: 'sql', tools: [{ name: 'get_sql_context' }] },
                { phase: 'sql', tools: [{ name: 'execute_test_query_sql' }] },
                { phase: 'review', tools: [] },
                { phase: 'api', tools: [{ name: 'load_comprehensive_api_endpoints' }] },
                { phase: 'review', tools: [] },
                { phase: 'synthesis', tools: [{ name: 'load_artifacts' }] },
            ],
        }) }))
        const orderedLabels = ['Understanding your question', 'Checking the database',
            'Read database schema', 'Test database query', 'Planning next step · Database',
            'Checking live data', 'Find available API endpoints', 'Planning next step · API',
            'Preparing the answer', 'Read saved results']
        for (let i = 1; i < orderedLabels.length; i++) {
            assert.ok(grouped.indexOf(orderedLabels[i - 1]) < grouped.indexOf(orderedLabels[i]))
        }
        assert.equal(grouped.split('Checking the database').length - 1, 1)
        assert.match(grouped, /4 tool calls/)
        // Unknown phase values and old prose are never rendered as public progress.
        stream.onmessage({ data: JSON.stringify({ type: 'STEP-START', phase: 'PRIVATE_UNKNOWN',
            step: 1, title: 'PRIVATE_TITLE', text: 'PRIVATE_TEXT', timestamp: 1 }) })
        stream.onmessage({ data: JSON.stringify({ type: 'COMPLETE', display_type: 'table',
            results: [{ count: 3 }], count: 1, metadata: {} }) })
        const complete = await render()
        assert.match(complete, /Analyzing saved results/)
        assert.doesNotMatch(complete, /In progress|PRIVATE_|No tool calls recorded/)
        stream.onmessage({ data: JSON.stringify({ type: 'DONE' }) })
    } finally {
        globalThis.EventSource = previous
        await server.close()
    }
})
