import json

import pytest

from guardrails import Accepted, Rejected, extract_notification
from prompts import FEW_SHOT, SYSTEM_PROMPT, build_messages

USER_INPUT = "Manda un correo a marta@app.com: Tienes un nuevo mensaje."


def example_pairs():
    return list(zip(FEW_SHOT[::2], FEW_SHOT[1::2]))


def test_system_prompt_comes_first():
    assert build_messages(USER_INPUT)[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_user_request_is_the_last_message_and_is_literal():
    # The provider reads only the last user message, and any extra word in it
    # (such as "email") would change what it extracts.
    assert build_messages(USER_INPUT)[-1] == {"role": "user", "content": USER_INPUT}


def test_examples_go_between_the_system_prompt_and_the_request():
    assert build_messages(USER_INPUT)[1:-1] == FEW_SHOT


def test_examples_alternate_user_and_assistant():
    assert all(user["role"] == "user" and assistant["role"] == "assistant" for user, assistant in example_pairs())


def test_retry_adds_a_system_hint_before_the_request():
    messages = build_messages(USER_INPUT, retry_reason="no_json")
    assert messages[-2]["role"] == "system"
    assert "JSON" in messages[-2]["content"]
    assert messages[-1] == {"role": "user", "content": USER_INPUT}


def test_unknown_retry_reason_still_gets_a_hint():
    assert build_messages(USER_INPUT, retry_reason="other")[-2]["role"] == "system"


def test_first_attempt_has_no_hint():
    assert len(build_messages(USER_INPUT)) == len(FEW_SHOT) + 2


def test_system_prompt_states_the_rules_guardrails_rely_on():
    for rule in ('"to"', '"message"', '"type"', "email", "sms", "JSON", "data"):
        assert rule in SYSTEM_PROMPT


@pytest.mark.parametrize(("user", "assistant"), example_pairs())
def test_examples_pass_the_guardrails_untouched(user, assistant):
    # Keeps the prompt and the validation from drifting apart.
    result = extract_notification(assistant["content"], user["content"])
    answer = json.loads(assistant["content"])

    if answer["to"] is None:
        assert result == Rejected("no_recipient", retryable=False)
    else:
        assert isinstance(result, Accepted)
        assert result.repairs == ()
        assert result.notification.model_dump() == answer
