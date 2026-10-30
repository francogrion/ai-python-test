"""Runs the real provider/responses.py through the guardrails with the k6 prompts."""

import importlib.util
import random
from pathlib import Path

import pytest

from guardrails import Accepted, Rejected, extract_notification

RESPONSES = Path(__file__).resolve().parents[2] / "provider" / "responses.py"

K6_PROMPTS = [
    (
        "Enviar email a juan@example.com diciendo que su paquete está en camino.",
        "juan@example.com", "email", "su paquete está en camino.",
    ),
    (
        "Avisar por SMS al 600-111-222 que la reserva ha sido confirmada.",
        "600-111-222", "sms", "la reserva ha sido confirmada.",
    ),
    (
        "Manda un correo a marta@app.com: Tienes un nuevo mensaje.",
        "marta@app.com", "email", "Tienes un nuevo mensaje.",
    ),
    (
        "Recordatorio por teléfono al 699888777: cita a las 10:00",
        "699888777", "sms", "cita a las 10:00",
    ),
]


@pytest.fixture(scope="module")
def generate():
    spec = importlib.util.spec_from_file_location("provider_responses", RESPONSES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_ai_response


def mock_message(user_input):
    """Same derivation as provider/app.py."""
    prompt = user_input.lower()
    return prompt.split(":")[-1].strip() if ":" in prompt else prompt[:50]


@pytest.mark.parametrize(("user_input", "to", "channel", "body"), K6_PROMPTS)
def test_every_mock_answer_is_recovered_or_is_a_refusal(generate, user_input, to, channel, body):
    random.seed(2026)
    for _ in range(3000):
        content = generate(to, mock_message(user_input), channel)
        result = extract_notification(content, user_input)

        if isinstance(result, Rejected):
            assert result == Rejected("no_json", retryable=True), content
            assert "{" not in content
        else:
            assert isinstance(result, Accepted)
            assert result.notification.model_dump() == {"to": to, "message": body, "type": channel}, content
