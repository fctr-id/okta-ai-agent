"""Observe SDK throttling without adding retries or changing their timing.

Only throttled model requests produce events. Context variables isolate simultaneous
queries and carry the callback into Bedrock's worker thread.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
import time
from uuid import uuid4
import re
from pydantic_ai.models.wrapper import WrapperModel

from src.core.retry_status import retry_after_seconds

progress_callback = ContextVar('model_progress_callback', default=None)
_request = ContextVar('model_request_progress', default=None)


def public_model_progress(details):
    """Publish bounded status fields only, never provider payloads or model prose."""
    if not isinstance(details, dict) or details.get('kind') != 'model_request':
        return None
    request_id = details.get('request_id')
    status = details.get('status')
    if (not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id)
            or status not in {'retry_wait', 'retrying', 'success', 'failed', 'cancelled', 'timed_out'}):
        return None
    clean = {'kind': 'model_request', 'request_id': request_id, 'status': status,
             'reason': 'rate_limit', 'label': 'AI provider'}
    for field, maximum in [('elapsed_ms', 86400000), ('retry_after_seconds', 86400), ('attempt', 100)]:
        value = details.get(field)
        if type(value) in (int, float) and 0 <= value <= maximum:
            clean[field] = round(value)
    return {'type': 'STEP-PROGRESS', 'details': clean, 'timestamp': time.time()}


class ProviderProgressModel(WrapperModel):
    """Observe requests without changing prompts, output, or retry policy."""
    async def request(self, messages, model_settings, model_request_parameters):
        async with model_request_progress():
            return await self.wrapped.request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        async with model_request_progress():
            async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
                yield stream

    async def count_tokens(self, messages, model_settings, model_request_parameters):
        async with model_request_progress():
            return await self.wrapped.count_tokens(messages, model_settings, model_request_parameters)


class RequestProgress:
    def __init__(self, callback):
        self.callback = callback
        self.loop = asyncio.get_running_loop()
        self.id = uuid4().hex
        self.started = time.monotonic()
        self.throttled = False
        self.waiting = False
        self.closed = False
        self.attempt = 0

    async def emit(self, status, **fields):
        if self.closed or not self.callback:
            return
        try:
            await self.callback('progress', {'details': {
                'kind': 'model_request', 'request_id': self.id, 'status': status,
                'reason': 'rate_limit', 'attempt': self.attempt,
                'elapsed_ms': round((time.monotonic() - self.started) * 1000), **fields,
            }})
        except Exception:
            # Progress delivery must not change SDK retry behavior; cancellation propagates.
            logging.getLogger(__name__).warning('Could not deliver model retry status')

    async def response(self, status, headers, throttled=False):
        if status != 429 and not throttled:
            return
        self.throttled = self.waiting = True
        delay = retry_after_seconds(headers)
        await self.emit('retry_wait', **({'retry_after_seconds': delay} if delay is not None else {}))

    async def sending(self):
        if self.waiting:
            self.waiting = False
            self.attempt += 1
            await self.emit('retrying')


@asynccontextmanager
async def model_request_progress():
    state = RequestProgress(progress_callback.get())
    token = _request.set(state)
    status = 'success'
    try:
        yield
    except asyncio.CancelledError:
        status = 'cancelled'
        raise
    except TimeoutError:
        status = 'timed_out'
        raise
    except BaseException:
        status = 'failed'
        raise
    finally:
        try:
            if state.throttled:
                await state.emit(status)
        finally:
            state.closed = True
            _request.reset(token)


async def _on_request(request):
    if state := _request.get():
        await state.sending()


async def _on_response(response):
    if state := _request.get():
        await state.response(response.status_code, response.headers)


def observe_http_client(client):
    if _on_request not in client.event_hooks['request']:
        client.event_hooks['request'].append(_on_request)
    if _on_response not in client.event_hooks['response']:
        client.event_hooks['response'].append(_on_response)
    return client


def observe_http_provider(provider):
    # Keep Pydantic AI's client ownership, close/reopen lifecycle and defaults.
    # These two SDK-owned fields are covered by the provider integration checks.
    client = getattr(provider, '_own_http_client', None)
    # Caller-owned clients are instrumented explicitly, without taking ownership.
    if client is not None:
        observe_http_client(client)
        factory = getattr(provider, '_http_client_factory', None)
        if factory is not None:
            provider._http_client_factory = lambda: observe_http_client(factory())
    return provider


def observe_bedrock_client(client):
    # These handlers run in the SDK worker thread and never return a retry decision.
    def sending(**kwargs):
        if (state := _request.get()) and not state.closed:
            asyncio.run_coroutine_threadsafe(state.sending(), state.loop).result()

    def response(response=None, **kwargs):
        if response is not None and (state := _request.get()) and not state.closed:
            http, parsed = response
            throttled = parsed.get('Error', {}).get('Code') in {'Throttling', 'ThrottlingException', 'TooManyRequestsException'}
            asyncio.run_coroutine_threadsafe(
                state.response(http.status_code, http.headers, throttled), state.loop).result()

    client.meta.events.register('before-send.bedrock-runtime', sending)
    client.meta.events.register('needs-retry.bedrock-runtime', response)
