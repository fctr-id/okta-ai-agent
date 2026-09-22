"""Accept execution results only after checking client-owned retrieval outcomes.

These records are execution diagnostics, not a sandbox against malicious code.
Only bounded failure paths and sanitized service errors accompany failures;
query parameters, tokens, and response records are excluded.
"""
import json


SENTINEL = "__TAKO_RETRIEVAL__"


class RetrievalFailure(RuntimeError):
    """Observed incomplete retrieval with a deterministic recovery policy."""

    def __init__(self, categories, details=None):
        self.categories = frozenset(categories)
        self.details = list(details or [])[:5]
        self.rediscover = not self.categories.intersection({'access', 'transient'})
        if 'access' in self.categories:
            message = "Could not retrieve all required data because Okta denied access. Check the API credentials and permissions."
        elif 'transient' in self.categories:
            message = "Could not retrieve all required data because Okta requests failed after retrying. Please try again later."
        elif 'pagination_limit' in self.categories:
            message = "Could not retrieve all required data because the pagination safety limit was reached."
        else:
            message = "Could not retrieve all required data because an API request failed."
        super().__init__(message)


def check_retrieval_outcomes(stderr: str) -> None:
    """Reject unresolved failures, even when generated code emitted a valid table.

An identical successful request later in the same execution resolves a failure.
Successful requests with different filters or parameters do not resolve it.
"""
    pending = {}
    failures = {}
    details = {}
    categories = {'access', 'transient', 'request', 'missing', 'pagination_limit', 'unknown'}
    for line in stderr.splitlines():
        if not line.startswith(SENTINEL):
            continue
        try:
            event = json.loads(line[len(SENTINEL):])
            key = event['request']
            if not isinstance(key, str) or len(key) != 64:
                raise ValueError('Invalid request fingerprint')
            if event['state'] == 'started':
                pending[key] = pending.get(key, 0) + 1
                continue
            if event['state'] not in {'success', 'error'} or pending.get(key, 0) < 1:
                raise ValueError('Unexpected retrieval outcome')
            pending[key] -= 1
            if event['state'] == 'success':
                failures.pop(key, None)
                details.pop(key, None)
            else:
                category = event.get('category', 'unknown')
                failures[key] = category if category in categories else 'unknown'
                diagnostic = {}
                for name, limit in (('endpoint', 512), ('method', 12), ('error_code', 80), ('message', 1000)):
                    value = event.get(name)
                    if isinstance(value, str):
                        diagnostic[name] = value[:limit]
                if isinstance(event.get('http_status'), int):
                    diagnostic['http_status'] = event['http_status']
                details[key] = diagnostic
        except (ValueError, TypeError, KeyError):
            raise RetrievalFailure({'unknown'}) from None
    unresolved = set(failures.values())
    if any(pending.values()):
        unresolved.add('unknown')
    if unresolved:
        raise RetrievalFailure(unresolved, [details[key] for key in failures if details.get(key)])
