import json
from pathlib import Path

import pytest

from guardrails import extract_notification
from recipients import find_recipients
from scoring import load_cases, score_case, summarize

VALID = {
    "id": "valid",
    "input": "Mail a ana@test.com: Hola",
    "expected": {"to": "ana@test.com", "message": "Hola", "type": "email"},
}
INVALID = {"id": "invalid", "input": "Mail a ana@test.com", "expected": None}
CLEAN = '{"to": "ana@test.com", "message": "Hola", "type": "email"}'


def test_exact_answer_is_correct_raw_and_through_the_pipeline():
    result = score_case(VALID, CLEAN)
    assert (result.raw_correct, result.pipeline_correct, result.incorrect_acceptance) == (True, True, False)


def test_noisy_answer_is_not_raw_correct_but_the_pipeline_recovers_it():
    result = score_case(VALID, f"```json\n{CLEAN}\n```")
    assert (result.raw_correct, result.pipeline_correct) == (False, True)


def test_extra_keys_are_not_raw_correct():
    result = score_case(VALID, '{"to": "ana@test.com", "message": "Hola", "type": "email", "confidence": 1}')
    assert result.raw_correct is False


def test_refusing_a_valid_request_is_a_miss_but_not_an_incorrect_acceptance():
    result = score_case(VALID, "Lo siento, no puedo.")
    assert (result.pipeline_correct, result.incorrect_acceptance) == (False, False)


def test_wrong_payload_let_through_is_an_incorrect_acceptance():
    case = {
        "id": "free",
        "input": "Mail a ana@test.com: nos vemos",
        "expected": {"to": "ana@test.com", "message": "otro mensaje", "type": "email"},
    }
    result = score_case(case, '{"to": "ana@test.com", "message": "nos vemos", "type": "email"}')
    assert (result.pipeline_correct, result.incorrect_acceptance) == (False, True)


def test_invalid_request_answered_with_nulls_is_correct():
    result = score_case(INVALID, '{"to": "ana@test.com", "message": null, "type": "email"}')
    assert (result.raw_correct, result.pipeline_correct, result.incorrect_acceptance) == (True, True, False)


def test_accepting_a_request_that_should_fail_is_an_incorrect_acceptance():
    case = {"id": "x", "input": "Mail a ana@test.com: hola", "expected": None}
    result = score_case(case, '{"to": "ana@test.com", "message": "hola", "type": "email"}')
    assert (result.pipeline_correct, result.incorrect_acceptance) == (False, True)


def test_summary_counts_each_metric():
    results = [score_case(VALID, CLEAN), score_case(VALID, "no"), score_case(INVALID, "nada")]
    assert summarize(results) == {
        "total": 3,
        "raw_correct": 1,
        "pipeline_correct": 2,
        "incorrect_acceptances": 0,
        "retries": 0,
    }


def test_results_keep_what_is_needed_to_review_a_failure():
    result = score_case(VALID, "no")
    assert result.case_id == "valid"
    assert result.answer == "no"
    assert result.outcome == "rejected:no_json"


CASES = load_cases(Path(__file__).resolve().parents[2] / "evaluation" / "cases.json")


def test_the_dataset_covers_both_kinds_of_case():
    valid = [case for case in CASES if case["expected"] is not None]
    assert len(valid) >= 20
    assert len(CASES) - len(valid) >= 5


def test_case_ids_are_unique():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", [case for case in CASES if case["expected"]], ids=lambda case: case["id"])
def test_every_valid_case_can_pass_with_the_ideal_answer(case):
    # A dataset the guardrails could never accept would measure nothing.
    result = extract_notification(json.dumps(case["expected"], ensure_ascii=False), case["input"])
    assert result.notification.model_dump() == case["expected"]


def test_expected_recipients_come_from_the_input():
    for case in CASES:
        if case["expected"]:
            assert case["expected"]["to"] in find_recipients(case["input"])
