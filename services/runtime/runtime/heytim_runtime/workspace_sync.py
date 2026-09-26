"""Copy explicitly selected durable files into a fresh Code Interpreter session."""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

import boto3
from botocore.config import Config
from strands import tool

from .repository_workspace import _consume_response

MAX_FILES = 5
MAX_FILE_BYTES = 4_500_000
FILES_BUCKET_NAME = os.environ.get("HEYTIM_FILES_BUCKET", "")
_ACTOR = re.compile(r"^[a-f0-9]{64}$")
_GROUP_PREFIX = re.compile(r"^groups/[a-f0-9-]{36}/uploads/$")


def workspace_files_from_payload(payload: dict, actor_id: str | None) -> list[dict]:
    raw = payload.get("workspaceFiles")
    if raw is None:
        return []
    if not FILES_BUCKET_NAME or not isinstance(raw, list) or len(raw) > MAX_FILES:
        raise ValueError("workspaceFiles is invalid")
    group_prefix = payload.get("attachmentPrefix")
    if group_prefix is not None:
        if not isinstance(payload.get("group"), dict) or not isinstance(group_prefix, str) or not _GROUP_PREFIX.fullmatch(group_prefix):
            raise ValueError("workspace scope is invalid")
        base = group_prefix.removesuffix("uploads/") + "workspace/"
    else:
        bot = payload.get("bot")
        bot_id = bot.get("id") if isinstance(bot, dict) else None
        if not isinstance(actor_id, str) or not _ACTOR.fullmatch(actor_id) or not isinstance(bot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bot_id):
            raise ValueError("workspace scope is invalid")
        base = f"users/{actor_id}/bots/{bot_id}/workspace/"
    selected = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("workspace file is invalid")
        file_id, name, key, size = (
            item.get("workspaceFileId"), item.get("name"),
            item.get("objectKey"), item.get("size"),
        )
        try:
            parsed_id = str(uuid.UUID(file_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("workspace file identity is invalid") from exc
        legacy_key = f"{base}{parsed_id}/{name}"
        revision_key = re.fullmatch(
            re.escape(f"{base}{parsed_id}/revisions/")
            + r"[1-9]\d*/(?:[a-f0-9]{16}/)?"
            + re.escape(name),
            key if isinstance(key, str) else "",
        )
        if (
            parsed_id in seen
            or not isinstance(name, str) or not name or len(name) > 200
            or name in {".", ".."} or "/" in name or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or not isinstance(key, str)
            or (key != legacy_key and revision_key is None)
            or type(size) is not int or not 0 < size <= MAX_FILE_BYTES
        ):
            raise ValueError("workspace file metadata is invalid")
        selected.append({"id": parsed_id, "name": name, "objectKey": key, "size": size})
        seen.add(parsed_id)
    return selected


def sync_workspace_files(interpreter: Any, selected: list[dict], *, s3_client: Any = None) -> dict:
    session_name, error = interpreter._ensure_session(None)
    if error:
        return error
    client = s3_client or boto3.client(
        "s3",
        config=Config(
            retries={"total_max_attempts": 4, "mode": "adaptive"},
            connect_timeout=3,
            read_timeout=20,
        ),
    )
    code_session = interpreter._sessions[session_name].client
    paths = []
    for item in selected:
        response = client.get_object(Bucket=FILES_BUCKET_NAME, Key=item["objectKey"])
        stream = response["Body"]
        try:
            body = stream.read(MAX_FILE_BYTES + 1)
        finally:
            stream.close()
        if len(body) != item["size"] or not 0 < len(body) <= MAX_FILE_BYTES:
            raise ValueError("A selected workspace file changed or is unavailable")
        path = f"workspace-{item['id'][:8]}-{item['name']}"
        _consume_response(code_session.upload_file(path, body))
        paths.append(path)
    return {"status": "success", "content": [{"text": "Loaded files: " + ", ".join(paths)}]}


def workspace_sync_tool(interpreter: Any, selected: list[dict]):
    @tool(name="load_workspace_files")
    def load_workspace_files() -> dict:
        """Load the selected durable workspace files into this code session."""
        return sync_workspace_files(interpreter, selected)

    return load_workspace_files
