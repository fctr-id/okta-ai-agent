import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('table explanation is plain text and survives COMPLETE for populated and empty results', async (t) => {
    const server = await createServer({ configFile: false, envDir: false, plugins: [vue()],
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false } })
    t.mock.method(console, 'log', () => {})
    t.mock.method(console, 'warn', () => {})
    const previous = globalThis.EventSource
    let stream
    globalThis.EventSource = class {
        constructor() { stream = this }
        addEventListener() {}
        close() {}
    }
    try {
        const { useReactStream } = await server.ssrLoadModule('/src/composables/useReactStream.js')
        const { default: DataDisplay } = await server.ssrLoadModule('/src/components/messages/DataDisplay.vue')
        const summary = 'Saved subset only. <img src=x onerror=alert(1)>'
        for (const rows of [[{ email: 'a@example.test' }], []]) {
            const state = useReactStream()
            await state.connectToStream('fixture')
            stream.onmessage({ data: JSON.stringify({ type: 'COMPLETE', display_type: 'table',
                results: rows, count: rows.length, metadata: { summary, data_source_type: 'analysis' } }) })
            assert.deepEqual(state.results.value.content, rows)
            assert.equal(state.results.value.metadata.summary, summary)
            const app = createSSRApp({ render: () => h(DataDisplay, { type: 'table',
                content: state.results.value.content, metadata: state.results.value.metadata }) })
            app.config.warnHandler = () => {}
            const html = await renderToString(app)
            assert.match(html, /class="result-explanation"/)
            assert.match(html, /Saved subset only\. &lt;img/)
            assert.ok(!html.includes('<img src=x'))
            stream.onmessage({ data: JSON.stringify({ type: 'DONE' }) })
        }
        const app = createSSRApp({ render: () => h(DataDisplay, { type: 'table', content: [], metadata: {} }) })
        app.config.warnHandler = () => {}
        assert.ok(!(await renderToString(app)).includes('class="result-explanation"'))
    } finally {
        globalThis.EventSource = previous
        await server.close()
    }
})
