from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from frogbot_runtime import repository_workspace


def test_repository_archive_is_staged_without_putting_token_in_sandbox(
    monkeypatch,
) -> None:
    uploaded = {}
    commands = []

    class FakeClient:
        identifier = "aws.codeinterpreter.v1"

        def upload_file(self, path: str, content: bytes) -> dict:
            uploaded.update(path=path, content=content)
            return {}

        def invoke(self, name: str, arguments: dict) -> dict:
            assert name == "executeCommand"
            commands.append(arguments["command"])
            return {}

    session = SimpleNamespace(session_id="session-1", client=FakeClient())

    class FakeInterpreter:
        def __init__(self):
            self._sessions = {"conversation": session}

        def _ensure_session(self, _name):
            return "conversation", None

    monkeypatch.setattr(
        repository_workspace,
        "_download_repository_archive",
        lambda repository, ref, token: (
            b"archive"
            if (repository, ref, token) == ("owner/repo", "main", "private-token")
            else b""
        ),
    )

    result = repository_workspace.prepare_repository(
        FakeInterpreter(), lambda: "private-token", "owner/repo"
    )

    assert result["status"] == "success"
    assert uploaded == {"path": "frogbot-repository.tar.gz", "content": b"archive"}
    assert "workspace/owner-repo" in commands[0]
    assert "private-token" not in commands[0]


def test_repository_and_ref_are_strictly_validated() -> None:
    for repository, ref in (("owner", "main"), ("owner/repo", "../secret")):
        try:
            repository_workspace.prepare_repository(
                object(), lambda: "token", repository, ref
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid repository input was accepted")
