from __future__ import annotations

from typing import Any

from bedrock_agentcore.evaluation.custom_code_based_evaluators import (
    EvaluatorInput,
    EvaluatorOutput,
    custom_code_based_evaluator,
)


def _walk(value: Any):
    yield value
    if hasattr(value, "model_dump"):
        yield from _walk(value.model_dump(mode="json"))
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def evaluate_spans(spans: list[Any]) -> EvaluatorOutput:
    error_markers = {
        "error",
        "failed",
        "failure",
        "timeout",
        "cancelled",
        "canceled",
        "deadline_exceeded",
    }
    values = {str(value).strip().lower() for value in _walk(spans) if isinstance(value, str)}
    failed = bool(values & error_markers)
    return EvaluatorOutput(
        label="Fail" if failed else "Pass",
        value=0.0 if failed else 1.0,
        explanation=(
            "The trace contains a terminal failure marker."
            if failed
            else "The trace completed without a terminal failure marker."
        ),
    )


@custom_code_based_evaluator()
def handler(input: EvaluatorInput, _context: Any) -> EvaluatorOutput:
    return evaluate_spans(input.session_spans)
