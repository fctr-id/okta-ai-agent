import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { getBrowserTimezone } from '../src/composables/userTimezone.js'
import { isClarificationTurn } from '../src/composables/turnFeedback.js'

test('browser timezone is optional when Intl is unavailable', (t) => {
    assert.equal(getBrowserTimezone(), Intl.DateTimeFormat().resolvedOptions().timeZone)
    t.mock.method(Intl, 'DateTimeFormat', () => { throw new Error('Unavailable') })
    assert.equal(getBrowserTimezone(), undefined)
})

test('request carries timezone and COMPLETE clarification finishes without error', async (t) => {
    const server = await createServer({ configFile: false, envFile: false,
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null, ws: false } })
    let stream
    const requests = []
    t.mock.method(console, 'log', () => {})
    t.mock.method(console, 'warn', () => {})
    t.mock.method(Intl, 'DateTimeFormat', () => ({ resolvedOptions: () => ({ timeZone: 'Asia/Kathmandu' }) }))
    t.mock.method(globalThis, 'fetch', async (url, options) => {
        requests.push({ url, options })
        return { ok: true, status: 200, json: async () => ({ process_id: 'fixture', session_id: 'fixture', turn_number: 1 }) }
    })
    const previous = globalThis.EventSource
    globalThis.EventSource = class {
        constructor() { stream = this }
        addEventListener() {}
        close() { this.closed = true }
    }
    try {
        const { useReactStream } = await server.ssrLoadModule('/src/composables/useReactStream.js')
        const state = useReactStream()
        await state.startProcess('Show local timestamps')
        assert.equal(JSON.parse(requests[0].options.body).user_timezone, 'Asia/Kathmandu')
        await state.connectToStream('fixture')
        stream.onmessage({ data: JSON.stringify({ type: 'COMPLETE', outcome: 'clarify', result_mode: 'needs_clarification',
            display_type: 'markdown', content: 'Which source timezone?' }) })
        stream.onmessage({ data: JSON.stringify({ type: 'DONE' }) })
        assert.equal(state.results.value.content, 'Which source timezone?')
        assert.equal(isClarificationTurn({ results: state.results.value }), true)
        assert.equal(state.error.value, null)
        assert.equal(state.isLoading.value, false)
        assert.equal(state.isProcessing.value, false)
        assert.equal(stream.closed, true)
    } finally {
        if (previous === undefined) delete globalThis.EventSource
        else globalThis.EventSource = previous
        await server.close()
    }
})
