from types import SimpleNamespace

from prompts import FEW_SHOT, SYSTEM_PROMPT, build_messages
from run import answer_text, build_report, request_params, run_cases
from scoring import summarize

CASE = {
    "id": "ok",
    "input": "Mail a ana@test.com: Hola",
    "expected": {"to": "ana@test.com", "message": "Hola", "type": "email"},
}
GOOD = '{"to": "ana@test.com", "message": "Hola", "type": "email"}'


def text(value):
    return SimpleNamespace(type="text", text=value)


def test_system_prompt_goes_in_the_top_level_field():
    params = request_params(build_messages("hola"), "some-model")
    assert params["system"] == SYSTEM_PROMPT
    assert params["model"] == "some-model"


def test_few_shot_turns_are_sent_as_real_turns_with_the_request_last():
    params = request_params(build_messages("hola"), "some-model")
    assert params["messages"] == [*FEW_SHOT, {"role": "user", "content": "hola"}]


def test_a_retry_only_sends_user_and_assistant_turns():
    params = request_params(build_messages("hola", retry_reason="no_json"), "some-model")
    assert params["system"] != SYSTEM_PROMPT
    assert {message["role"] for message in params["messages"]} == {"user", "assistant"}


def test_answer_text_skips_thinking_blocks():
    response = SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), text("hola")])
    assert answer_text(response) == "hola"


def test_answer_text_of_a_refusal_is_empty():
    assert answer_text(SimpleNamespace(content=[])) == ""


def test_each_case_runs_once_per_repeat_with_the_production_messages():
    seen = []

    def ask(messages):
        seen.append(messages)
        return GOOD

    results = run_cases([CASE], ask, repeats=3)

    assert len(results) == 3
    assert seen == [build_messages(CASE["input"])] * 3
    assert all(result.pipeline_correct for result in results)


def test_an_unusable_answer_is_asked_again_like_the_service_does():
    seen = []
    answers = iter(["Lo siento, no puedo.", GOOD])

    def ask(messages):
        seen.append(messages)
        return next(answers)

    result = run_cases([CASE], ask, repeats=1)[0]

    assert seen == [build_messages(CASE["input"]), build_messages(CASE["input"], retry_reason="no_json")]
    assert result.retried is True
    assert result.pipeline_correct is True
    assert result.answer == GOOD


def test_a_retry_is_only_tried_once():
    calls = []

    def ask(messages):
        calls.append(messages)
        return "no"

    result = run_cases([CASE], ask, repeats=1)[0]

    assert len(calls) == 2
    assert result.pipeline_correct is False


def test_a_final_rejection_is_not_asked_again():
    calls = []
    case = {"id": "none", "input": "Avisa a Pedro: hola", "expected": None}

    def ask(messages):
        calls.append(messages)
        return "no"

    result = run_cases([case], ask, repeats=1)[0]

    assert len(calls) == 1
    assert result.retried is False


def test_the_summary_keeps_how_the_first_answer_did():
    answers = iter(["no", GOOD])
    results = run_cases([CASE], lambda messages: next(answers), repeats=1)

    assert summarize(results)["raw_correct"] == 0
    assert summarize(results)["retries"] == 1


def test_report_records_what_produced_the_numbers():
    results = run_cases([CASE], lambda messages: "no", repeats=1)
    report = build_report(results, model="some-model", repeats=1)

    assert report["model"] == "some-model"
    assert report["repeats"] == 1
    assert len(report["prompt_sha256"]) == 64
    assert report["summary"]["pipeline_correct"] == 0
    assert report["failures"][0]["case_id"] == "ok"
    assert report["failures"][0]["answer"] == "no"
    assert len(report["results"]) == 1
