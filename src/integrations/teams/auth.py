"""Authorize authenticated Bot Service activities; never trust body identity alone."""
import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .config import TeamsConfig


class AccessUnavailable(Exception):
    """Graph could not establish membership; callers must fail closed."""


@dataclass(frozen=True)
class Sender:
    tenant: str
    user: str
    conversation: str
    activity: str
    service_url: str


def authenticated_sender(body: dict, issuer: str | None, config: TeamsConfig) -> Sender:
    """Called only AFTER the SDK validates the bearer signature, audience and expiry."""
    if issuer != "https://api.botframework.com":
        raise ValueError("Only Bot Service connector activities are supported")
    conversation = body.get("conversation") or {}
    channel = body.get("channelData") or {}
    sender = body.get("from") or {}
    tenant = str(UUID((channel.get("tenant") or {}).get("id", "")))
    user = str(UUID(sender.get("aadObjectId", "")))
    if body.get("channelId") != "msteams" or conversation.get("conversationType") != "personal":
        raise ValueError("Only Teams personal chats are supported")
    if tenant != config.tenant_id or sender.get("role") == "bot":
        raise ValueError("Untrusted tenant or sender")
    if conversation.get("tenantId") and str(UUID(conversation["tenantId"])) != tenant:
        raise ValueError("Conflicting tenant identity")
    service_url = body.get("serviceUrl", "")
    url = urlsplit(service_url)
    # A connector-authenticated body must still not become an arbitrary outbound target.
    if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
            or url.query or url.fragment or not url.hostname
            or not (url.hostname == "smba.trafficmanager.net"
                    or url.hostname.endswith(".smba.trafficmanager.net")
                    or url.hostname.endswith(".botframework.com"))):
        raise ValueError("Unsupported Bot Service URL")
    if not conversation.get("id") or not body.get("id"):
        raise ValueError("Missing activity identity")
    if len(conversation["id"]) > 2048 or len(body["id"]) > 2048:
        raise ValueError("Invalid activity identity")
    return Sender(tenant, user, conversation["id"], body["id"], service_url)


class GroupAuthorizer:
    def __init__(self, config: TeamsConfig, *, token_client=None, http=None):
        if token_client is None:
            import msal
            token_client = msal.ConfidentialClientApplication(
                config.client_id,
                authority=f"https://login.microsoftonline.com/{config.tenant_id}",
                client_credential=config.client_secret.get_secret_value(),
                timeout=10,
            )
        self.config = config
        self.tokens = token_client
        self.http = http or httpx.AsyncClient(timeout=10, follow_redirects=False)
        self._token_lock = asyncio.Lock()

    async def allowed(self, user: str) -> bool:
        user = str(UUID(user))
        try:
            # MSAL owns the token cache; directory membership is never cached.
            async with self._token_lock:
                token = await asyncio.to_thread(
                    self.tokens.acquire_token_for_client,
                    scopes=["https://graph.microsoft.com/.default"],
                )
            if not token.get("access_token"):
                raise AccessUnavailable("Graph token acquisition failed")
            groups = self.config.group_ids
            for start in range(0, len(groups), 20):
                batch = groups[start:start + 20]
                for attempt in range(3):
                    response = await self.http.post(
                        f"https://graph.microsoft.com/v1.0/users/{user}/checkMemberGroups",
                        headers={"Authorization": f"Bearer {token['access_token']}"},
                        json={"groupIds": batch},
                    )
                    if response.status_code not in (429, 502, 503, 504) or attempt == 2:
                        break
                    delay = response.headers.get("Retry-After", str(2 ** attempt))
                    # Do not retry earlier than a longer server-requested delay.
                    if not delay.isdigit() or int(delay) > 10:
                        raise AccessUnavailable("Graph retry window exceeded")
                    await asyncio.sleep(max(1, int(delay)))
                response.raise_for_status()
                matches = response.json().get("value")
                if not isinstance(matches, list) or any(not isinstance(v, str) for v in matches):
                    raise AccessUnavailable("Invalid Graph membership response")
                if set(v.lower() for v in matches).intersection(batch):
                    return True
            return False
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AccessUnavailable("Graph membership check failed") from exc

    async def close(self):
        await self.http.aclose()
