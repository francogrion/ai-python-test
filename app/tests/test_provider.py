import json

import httpx
import pytest

from config import Settings
from models import Notification
from provider import AIUnavailable, DeliveryFailed, DeliveryRetryable, ProviderClient, create_http_client

NOTIFICATION = Notification(to="ana@test.com", message="hola", type="email")
MESSAGES = [{"role": "user", "content": "hola"}]


def client_with(handler):
    transport = httpx.MockTransport(handler)
    return ProviderClient(create_http_client(Settings(provider_url="http://provider"), transport))


def respond(status, **kwargs):
    return lambda request: httpx.Response(status, **kwargs)


def raising(error):
    def handler(request):
        raise error

    return handler


async def test_extract_posts_the_messages_with_the_api_key():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["key"] = request.headers["X-API-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "respuesta"}}]})

    assert await client_with(handler).extract(MESSAGES) == "respuesta"
    assert seen == {"path": "/v1/ai/extract", "key": "test-dev-2026", "body": {"messages": MESSAGES}}


@pytest.mark.parametrize(
    "handler",
    [
        respond(500),
        respond(429),
        respond(200, json={"choices": []}),
        respond(200, text="no json"),
        raising(httpx.ConnectError("down")),
        raising(httpx.ReadTimeout("slow")),
    ],
)
async def test_extract_failures_are_reported_as_unavailable(handler):
    with pytest.raises(AIUnavailable):
        await client_with(handler).extract(MESSAGES)


async def test_notify_sends_the_payload_and_trace_id():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["trace_id"] = request.url.params["trace_id"]
        seen["key"] = request.headers["X-API-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "delivered", "provider_id": "p-1"})

    assert await client_with(handler).notify(NOTIFICATION, trace_id="abc") == "p-1"
    assert seen == {
        "path": "/v1/notify",
        "trace_id": "abc",
        "key": "test-dev-2026",
        "body": NOTIFICATION.model_dump(),
    }


async def test_a_200_is_final_even_with_a_malformed_body():
    assert await client_with(respond(200, text="ok")).notify(NOTIFICATION, trace_id="abc") is None


async def test_429_is_retryable_and_honours_retry_after():
    with pytest.raises(DeliveryRetryable) as error:
        await client_with(respond(429, headers={"Retry-After": "7"})).notify(NOTIFICATION, trace_id="abc")
    assert error.value.retry_after == 7


async def test_429_without_a_usable_header_is_still_flagged():
    with pytest.raises(DeliveryRetryable) as error:
        await client_with(respond(429, headers={"Retry-After": "soon"})).notify(NOTIFICATION, trace_id="abc")
    assert error.value.rate_limited
    assert error.value.retry_after is None


@pytest.mark.parametrize("handler", [respond(500), respond(503), raising(httpx.ConnectError("down"))])
async def test_failures_before_delivery_are_retryable(handler):
    with pytest.raises(DeliveryRetryable) as error:
        await client_with(handler).notify(NOTIFICATION, trace_id="abc")
    assert not error.value.rate_limited


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (respond(401), "provider_rejected"),
        (respond(422), "provider_rejected"),
        (raising(httpx.ReadTimeout("slow")), "delivery_unknown"),
        (respond(502), "delivery_unknown"),
        (respond(504), "delivery_unknown"),
    ],
)
async def test_final_notify_failures(handler, reason):
    with pytest.raises(DeliveryFailed) as error:
        await client_with(handler).notify(NOTIFICATION, trace_id="abc")
    assert error.value.reason == reason


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("EXTRACTION_WORKERS", "7")
    monkeypatch.setenv("NOTIFY_RATE_PER_SECOND", "1.5")
    monkeypatch.setenv("PROVIDER_URL", "http://other")
    settings = Settings.from_env()
    assert (settings.extraction_workers, settings.notify_rate_per_second, settings.provider_url) == (
        7,
        1.5,
        "http://other",
    )


def test_settings_defaults_match_the_provider():
    settings = Settings.from_env()
    assert settings.provider_url == "http://localhost:3001"
    assert settings.notify_rate_per_second < 5
    assert settings.ai_max_calls == 2
