from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from heytim_runtime import workspace_sync

FILE_ID = "12345678-1234-4234-8234-123456789abc"
ACTOR = "a" * 64


def test_workspace_selection_is_confined_to_its_bot_or_room(monkeypatch) -> None:
    monkeypatch.setattr(workspace_sync, "FILES_BUCKET_NAME", "private-files")
    valid = {
        "workspaceFileId": FILE_ID, "name": "notes.txt", "size": 5,
        "objectKey": f"users/{ACTOR}/bots/bot1/workspace/{FILE_ID}/notes.txt",
    }
    payload = {"bot": {"id": "bot1"}, "workspaceFiles": [valid]}
    assert workspace_sync.workspace_files_from_payload(payload, ACTOR)[0]["name"] == "notes.txt"
    with pytest.raises(ValueError):
        workspace_sync.workspace_files_from_payload(
            {"bot": {"id": "bot2"}, "workspaceFiles": [valid]}, ACTOR
        )
    group = {
        "bot": {"id": "bot1"}, "group": {},
        "attachmentPrefix": "groups/12345678-1234-4234-8234-123456789abc/uploads/",
        "workspaceFiles": [valid],
    }
    with pytest.raises(ValueError):
        workspace_sync.workspace_files_from_payload(group, ACTOR)


def test_saved_file_loads_into_a_new_code_session(monkeypatch) -> None:
    monkeypatch.setattr(workspace_sync, "FILES_BUCKET_NAME", "private-files")
    uploaded = []

    class CodeClient:
        def upload_file(self, path, content):
            uploaded.append((path, content))
            return {}

    class S3Client:
        def get_object(self, **kwargs):
            assert kwargs["Bucket"] == "private-files"
            return {"Body": io.BytesIO(b"hello")}

    interpreter = SimpleNamespace(
        _ensure_session=lambda _name: ("new", None),
        _sessions={"new": SimpleNamespace(client=CodeClient())},
    )
    result = workspace_sync.sync_workspace_files(
        interpreter,
        [{"id": FILE_ID, "name": "notes.txt", "size": 5, "objectKey": "safe-key"}],
        s3_client=S3Client(),
    )
    assert uploaded == [("workspace-12345678-notes.txt", b"hello")]
    assert result["status"] == "success"
