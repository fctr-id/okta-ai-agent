"""Observe discovery requests without changing the client or exposing tenant data."""

import asyncio
import json
import re
import time
from urllib.parse import urlsplit


def response_diagnostics(response):
    """Summarize shape and known client error codes without logging payloads."""
    wrapped = isinstance(response, dict) and response.get("status") in ("success", "error")
    data = response.get("data") if wrapped else response
    details = {
        "response_type": type(response).__name__,
        "response_chars": len(json.dumps(response, separators=(',', ':'), default=str)),
        "client_status": response["status"] if wrapped else "not_wrapped",
        "data_type": type(data).__name__,
        "data_count": len(data) if isinstance(data, list) else None,
        "data_item_types": sorted({type(item).__name__ for item in data[:3]}) if isinstance(data, list) else [],
    }
    if isinstance(response, dict):
        code = response.get("error_code")
        if isinstance(code, str) and re.fullmatch(r"E\d{7}|UNKNOWN", code):
            details["error_code"] = code
        status = response.get("http_status")
        if type(status) is int and 100 <= status <= 599:
            details["http_status"] = status
    return details


class DiscoveryTestClient:
    """Per-test adapter; delegates requests unchanged to the existing Okta client."""

    def __init__(self, client, endpoints, test_id, progress_callback, diagnostic_callback=None):
        self._client = client
        self._test_id = test_id
        self._progress_callback = progress_callback
        self._diagnostic_callback = diagnostic_callback
        self._request_count = 0
        self._operations = []
        for endpoint in endpoints or []:
            template = endpoint.get("url_pattern", "")
            entity, operation = endpoint.get("entity"), endpoint.get("operation")
            if not template or not entity or not operation:
                continue
            parts = re.split(r"(\{[^}]+\})", template.rstrip("/"))
            pattern = "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
            specificity = sum(len(part) for part in parts if not part.startswith("{"))
            self._operations.append((specificity, endpoint.get("method", "GET").upper(),
                                     re.compile(pattern), f"{entity}.{operation}"))
        # Prefer literal routes over placeholder routes that also match.
        self._operations.sort(key=lambda item: item[0], reverse=True)

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _operation(self, endpoint, method):
        try:
            path = urlsplit(str(endpoint)).path.rstrip("/")
            for _, expected_method, pattern, operation in self._operations:
                if expected_method == str(method).upper() and pattern.fullmatch(path):
                    return operation
        except ValueError:
            pass
        # Never send raw URLs, IDs, query strings, or error payloads to the panel.
        return "Uncatalogued endpoint"

    async def _emit(self, request_id, operation, status):
        if self._progress_callback:
            try:
                await self._progress_callback({"details": {
                    "kind": "api_test_request", "test_id": self._test_id,
                    "request_id": request_id, "operation": operation, "status": status,
                }})
            except Exception:
                # A disconnected UI must not change the request result.
                pass

    def _diagnose(self, request_id, operation, status, started, response=None):
        if self._diagnostic_callback:
            try:
                self._diagnostic_callback({
                    "test_id": self._test_id, "request_id": request_id,
                    "operation": operation, "outcome": status,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    **response_diagnostics(response),
                })
            except Exception:
                # Diagnostics must not change retrieval results or errors.
                pass

    async def make_request(self, *args, **kwargs):
        endpoint = kwargs.get("endpoint", args[0] if args else "")
        method = kwargs.get("method", args[1] if len(args) > 1 else "GET")
        operation = self._operation(endpoint, method)
        self._request_count += 1
        request_id = f"{self._test_id}-request-{self._request_count}"
        started = time.monotonic()
        try:
            await self._emit(request_id, operation, "running")
            response = await self._client.make_request(*args, **kwargs)
        except asyncio.CancelledError:
            self._diagnose(request_id, operation, "cancelled", started)
            await self._emit(request_id, operation, "cancelled")
            raise
        except Exception:
            self._diagnose(request_id, operation, "exception", started)
            await self._emit(request_id, operation, "failed")
            raise
        status = "unknown"
        if isinstance(response, dict):
            if response.get("status") == "success":
                status = "empty" if response.get("data") in (None, [], {}) else "success"
            elif response.get("status") == "error":
                status = "failed"
        self._diagnose(request_id, operation, status, started, response)
        await self._emit(request_id, operation, status)
        return response
