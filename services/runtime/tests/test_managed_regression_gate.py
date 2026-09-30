"""Exercise the release workflow's actual jq gate with aggregate-only fixtures."""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/aws-production.yml"


@pytest.fixture
def completed_result() -> dict:
    return {
        "status": "COMPLETED",
        "agent_invocation_failures": [],
        "evaluation_results": {
            "totalNumberOfSessions": 5,
            "numberOfSessionsCompleted": 5,
            "numberOfSessionsInProgress": 0,
            "numberOfSessionsFailed": 0,
            "numberOfSessionsIgnored": 0,
            "evaluatorSummaries": [
                {
                    "evaluatorId": "Builtin.GoalSuccessRate",
                    "totalEvaluated": 5,
                    "totalFailed": 0,
                    "statistics": {"averageScore": 0.8},
                },
                {
                    "evaluatorId": "Builtin.ResponseRelevance",
                    "totalEvaluated": 5,
                    "totalFailed": 0,
                    "statistics": {"averageScore": 0.8},
                },
            ],
        },
    }


def passes_release_gate(result: dict) -> bool:
    workflow = WORKFLOW.read_text()
    match = re.search(
        r"if ! jq -e '\n(.*?)\n\s*' \"\$result\" >/dev/null; then",
        workflow,
        re.DOTALL,
    )
    assert match is not None, "managed release gate was not found"
    check = subprocess.run(
        ["jq", "-e", match.group(1)],
        input=json.dumps(result),
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode in {0, 1}, check.stderr
    return check.returncode == 0


def test_managed_release_gate_accepts_all_five_at_threshold(completed_result: dict) -> None:
    assert passes_release_gate(completed_result)


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("status",), "FAILED"),
        (("agent_invocation_failures",), ["failed"]),
        (("evaluation_results", "totalNumberOfSessions"), 4),
        (("evaluation_results", "numberOfSessionsCompleted"), 4),
        (("evaluation_results", "numberOfSessionsInProgress"), 1),
        (("evaluation_results", "numberOfSessionsFailed"), 1),
        (("evaluation_results", "numberOfSessionsIgnored"), 1),
        (("evaluation_results", "evaluatorSummaries", 0, "evaluatorId"), "Other"),
        (("evaluation_results", "evaluatorSummaries", 0, "totalEvaluated"), 4),
        (("evaluation_results", "evaluatorSummaries", 0, "totalFailed"), 1),
        (("evaluation_results", "evaluatorSummaries", 0, "statistics", "averageScore"), 0.79),
        (("evaluation_results", "evaluatorSummaries", 1, "statistics", "averageScore"), "0.9"),
    ],
)
def test_managed_release_gate_rejects_bad_metrics(
    completed_result: dict, path: tuple, invalid: object
) -> None:
    result = copy.deepcopy(completed_result)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid
    assert not passes_release_gate(result)


def test_managed_release_gate_requires_snake_case_envelope(completed_result: dict) -> None:
    completed_result["evaluationResults"] = completed_result.pop("evaluation_results")
    assert not passes_release_gate(completed_result)
