import time

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import app as module_app
from main import create_app

USER_INPUT = "Manda un mail a feda@test.com diciendo hola"
FAST = Settings(notify_rate_per_second=1000)


def fake_provider(request):
    if request.url.path == "/v1/ai/extract":
        content = '{"to": "feda@test.com", "message": "hola", "type": "email"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.Response(200, json={"status": "delivered", "provider_id": "p-1"})


def client_for(settings=FAST):
    return TestClient(create_app(settings, httpx.MockTransport(fake_provider)))


@pytest.fixture
def client():
    with client_for() as test_client:
        yield test_client


def create(client):
    return client.post("/v1/requests", json={"user_input": USER_INPUT}).json()["id"]


def wait_for_status(client, request_id, status):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if client.get(f"/v1/requests/{request_id}").json()["status"] == status:
            return
        time.sleep(0.01)
    pytest.fail(f"request never reached {status}")


def test_the_module_exposes_a_fastapi_instance():
    assert module_app.title


def test_create_returns_201_with_an_id(client):
    response = client.post("/v1/requests", json={"user_input": USER_INPUT})
    assert response.status_code == 201
    assert list(response.json()) == ["id"]


@pytest.mark.parametrize("body", [{}, {"user_input": ""}, {"user_input": 5}])
def test_create_validates_the_body(client, body):
    assert client.post("/v1/requests", json=body).status_code == 422


def test_create_rejects_an_oversized_input(client):
    assert client.post("/v1/requests", json={"user_input": "a" * 5_000}).status_code == 422


def test_a_new_request_is_queued(client):
    request_id = create(client)
    assert client.get(f"/v1/requests/{request_id}").json() == {"id": request_id, "status": "queued"}


def test_get_unknown_id_is_404(client):
    assert client.get("/v1/requests/nope").status_code == 404


def test_process_unknown_id_is_404(client):
    assert client.post("/v1/requests/nope/process").status_code == 404


def test_process_returns_202_and_the_request_ends_sent(client):
    request_id = create(client)
    response = client.post(f"/v1/requests/{request_id}/process")

    assert response.status_code == 202
    assert response.json()["id"] == request_id
    wait_for_status(client, request_id, "sent")


def test_processing_twice_is_harmless(client):
    request_id = create(client)
    client.post(f"/v1/requests/{request_id}/process")
    wait_for_status(client, request_id, "sent")

    assert client.post(f"/v1/requests/{request_id}/process").status_code == 202
    assert client.get("/health").json()["metrics"]["ai_calls"] == 1


def test_a_request_that_cannot_be_processed_stays_a_200_with_failed_status(client):
    request_id = client.post("/v1/requests", json={"user_input": "Avisa a Pedro: hola"}).json()["id"]

    assert client.post(f"/v1/requests/{request_id}/process").status_code == 202
    wait_for_status(client, request_id, "failed")
    assert client.get(f"/v1/requests/{request_id}").status_code == 200


def test_overload_answers_202_and_marks_the_request_failed():
    settings = Settings(extraction_workers=0, queue_max_size=1)
    with client_for(settings) as client:
        client.post(f"/v1/requests/{create(client)}/process")
        request_id = create(client)
        response = client.post(f"/v1/requests/{request_id}/process")

        assert response.status_code == 202
        assert response.json()["status"] == "failed"


def test_health_reports_status_counts_and_metrics(client):
    request_id = create(client)
    client.post(f"/v1/requests/{request_id}/process")
    wait_for_status(client, request_id, "sent")

    body = client.get("/health").json()
    assert body["requests"]["sent"] == 1
    assert body["metrics"]["ai_calls"] == 1
