"""HTTP contracts of /v1/ai/extract and /v1/notify.

Each method makes exactly one call and classifies the outcome. How many times to
try is up to the pipeline, which holds the budget.
"""

import httpx

from config import Settings
from models import Notification


class AIUnavailable(Exception):
    """The AI call failed or its response has no usable content."""


class DeliveryRetryable(Exception):
    """The provider did not take the notification, so trying again should not duplicate it."""

    def __init__(self, rate_limited: bool = False, retry_after: float | None = None) -> None:
        super().__init__(f"rate_limited={rate_limited} retry_after={retry_after}")
        self.rate_limited = rate_limited
        self.retry_after = retry_after


class DeliveryFailed(Exception):
    """Trying again would not help, or could send a duplicate."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def create_http_client(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    connections = settings.extraction_workers + settings.notification_workers
    return httpx.AsyncClient(
        base_url=settings.provider_url,
        headers={"X-API-Key": settings.provider_api_key},
        timeout=httpx.Timeout(settings.ai_read_timeout, connect=settings.connect_timeout, pool=None),
        limits=httpx.Limits(max_connections=connections, max_keepalive_connections=connections),
        transport=transport,
    )


class ProviderClient:
    def __init__(self, http: httpx.AsyncClient, notify_read_timeout: float = 15.0) -> None:
        self._http = http
        self._notify_timeout = httpx.Timeout(notify_read_timeout, connect=http.timeout.connect, pool=None)

    async def extract(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self._http.post("/v1/ai/extract", json={"messages": messages})
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise AIUnavailable(repr(error)) from error

    async def notify(self, notification: Notification, trace_id: str) -> str | None:
        """Return the provider id. A 200 is final even if its body is malformed."""
        try:
            response = await self._http.post(
                "/v1/notify",
                json=notification.model_dump(),
                params={"trace_id": trace_id},
                timeout=self._notify_timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise DeliveryRetryable() from error
        except httpx.HTTPError as error:
            # The request left, so it may have been delivered.
            raise DeliveryFailed("delivery_unknown") from error

        if response.status_code == 429:
            raise DeliveryRetryable(rate_limited=True, retry_after=_retry_after(response))
        if response.status_code in (502, 504):
            # A gateway error says nothing about whether the provider delivered it.
            raise DeliveryFailed("delivery_unknown")
        if response.status_code >= 500:
            raise DeliveryRetryable()
        if response.status_code >= 400:
            raise DeliveryFailed("provider_rejected")
        return _provider_id(response)


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def _provider_id(response: httpx.Response) -> str | None:
    try:
        return response.json().get("provider_id")
    except (ValueError, AttributeError):
        return None
