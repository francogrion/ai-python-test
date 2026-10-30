"""Scores real model answers, on their own and through the production guardrails."""

import json
from dataclasses import dataclass
from pathlib import Path

from guardrails import Accepted, extract_notification

_KEYS = {"to", "message", "type"}


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    answer: str
    outcome: str
    raw_correct: bool
    pipeline_correct: bool
    incorrect_acceptance: bool
    retry_reason: str | None = None
    retried: bool = False


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_case(case: dict, answer: str) -> CaseResult:
    expected = case["expected"]
    result = extract_notification(answer, case["input"])
    accepted = isinstance(result, Accepted)
    matches = accepted and result.notification.model_dump() == expected
    pipeline_correct = matches if expected is not None else not accepted

    return CaseResult(
        case_id=case["id"],
        answer=answer,
        outcome="accepted" if accepted else f"rejected:{result.reason}",
        raw_correct=_raw_correct(answer, expected),
        pipeline_correct=pipeline_correct,
        incorrect_acceptance=accepted and not pipeline_correct,
        retry_reason=result.reason if not accepted and result.retryable else None,
    )


def summarize(results: list[CaseResult]) -> dict[str, int]:
    return {
        "total": len(results),
        "raw_correct": sum(result.raw_correct for result in results),
        "pipeline_correct": sum(result.pipeline_correct for result in results),
        "incorrect_acceptances": sum(result.incorrect_acceptance for result in results),
        "retries": sum(result.retried for result in results),
    }


def _raw_correct(answer: str, expected: dict | None) -> bool:
    """Did the model follow the contract with no help from the guardrails?"""
    try:
        data = json.loads(answer)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if expected is not None:
        return data == expected
    return set(data) == _KEYS and (data["to"] is None or data["message"] is None)
