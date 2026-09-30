"""AWS CLI transport accepts only documented empty read response shapes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_writer_cli_transport import CliClient, CliError


@pytest.mark.parametrize(
    ("service", "operation"),
    [
        ("s3", "get_bucket_versioning"),
        ("lambda", "get_function_concurrency"),
        ("bedrock-agentcore-control", "get_resource_policy"),
    ],
)
@pytest.mark.parametrize("stdout", ["", "  \n", "null"])
def test_known_empty_reads_are_empty_objects(
    monkeypatch: pytest.MonkeyPatch, service: str, operation: str, stdout: str
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout, ""),
    )
    client = CliClient(service, "source-profile", "us-east-1")
    assert client.invoke(operation, {}) == {}


def test_other_empty_read_still_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    client = CliClient("s3", "source-profile", "us-east-1")
    with pytest.raises(CliError, match="InvalidAwsCliOutput"):
        client.invoke("get_bucket_encryption", {})


def test_cli_failure_is_not_reinterpreted_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 255, "", "An error occurred (AccessDenied)"
        ),
    )
    client = CliClient("lambda", "source-profile", "us-east-1")
    with pytest.raises(CliError, match="AccessDenied"):
        client.invoke("get_function_concurrency", {})
