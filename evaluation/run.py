"""Evaluates the production prompt against a real Claude model.

Sends each case as the service would, retry included, and scores the answer on
its own and through the production guardrails. Nothing is ever notified.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT.parent / "app")]

from prompts import FEW_SHOT, SYSTEM_PROMPT, build_messages  # noqa: E402
from scoring import CaseResult, load_cases, score_case, summarize  # noqa: E402

DEFAULT_MODEL = "claude-opus-5-5"
OLLAMA_URL = "http://localhost:11434"


def request_params(messages: list[dict[str, str]], model: str) -> dict:
    system, *turns = messages
    return {
        "model": model,
        "max_tokens": 4096,
        "system": system["content"],
        "messages": turns,
        "output_config": {"effort": "low"},
    }


def ollama_payload(messages: list[dict[str, str]], model: str) -> dict:
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 4096},
    }


def ollama_answer(response: dict) -> str:
    return response["message"]["content"]


def answer_text(response) -> str:
    """A refusal has no text, and scores like any other unusable answer."""
    return "".join(block.text for block in response.content if block.type == "text")


def run_cases(cases: list[dict], ask: Callable[[list[dict[str, str]]], str], repeats: int) -> list[CaseResult]:
    return [_run_case(case, ask) for case in cases for _ in range(repeats)]


def _run_case(case: dict, ask: Callable[[list[dict[str, str]]], str]) -> CaseResult:
    """Same budget as the service: one retry, and only for an unusable answer."""
    first = score_case(case, ask(build_messages(case["input"])))
    if first.retry_reason is None:
        return first
    second = score_case(case, ask(build_messages(case["input"], first.retry_reason)))
    return replace(second, raw_correct=first.raw_correct, retried=True)


def build_report(results: list[CaseResult], model: str, repeats: int) -> dict:
    prompt = json.dumps([SYSTEM_PROMPT, FEW_SHOT], ensure_ascii=False)
    return {
        "model": model,
        "repeats": repeats,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(results),
        "failures": [asdict(result) for result in results if not result.pipeline_correct],
        "results": [asdict(result) for result in results],
    }


def report_file_name(model: str, prompt_sha256: str, dataset: str = "cases") -> str:
    safe_model = model.replace("/", "-").replace(":", "-")
    suffix = "" if dataset == "cases" else f"-{dataset}"
    return f"{safe_model}-{prompt_sha256[:8]}{suffix}.json"


def anthropic_asker(model: str) -> Callable[[list[dict[str, str]]], str]:
    import anthropic

    client = anthropic.Anthropic()
    return lambda messages: answer_text(client.messages.create(**request_params(messages, model)))


def ollama_asker(model: str) -> Callable[[list[dict[str, str]]], str]:
    import httpx

    client = httpx.Client(base_url=OLLAMA_URL, timeout=300)

    def ask(messages: list[dict[str, str]]) -> str:
        response = client.post("/api/chat", json=ollama_payload(messages, model))
        response.raise_for_status()
        return ollama_answer(response.json())

    return ask


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["anthropic", "ollama"], default="anthropic")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.json")
    arguments = parser.parse_args()

    asker = ollama_asker if arguments.backend == "ollama" else anthropic_asker
    results = run_cases(load_cases(arguments.cases), asker(arguments.model), arguments.repeats)
    report = build_report(results, arguments.model, arguments.repeats)

    output = ROOT / "results" / report_file_name(arguments.model, report["prompt_sha256"], arguments.cases.stem)
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["summary"]))
    for failure in report["failures"]:
        print(f"{failure['case_id']}: {failure['outcome']} {failure['answer']!r}")
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
