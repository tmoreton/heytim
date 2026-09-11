from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import boto3
from strands import tool

from .artifact_renderers import render_native_artifact

FILES_BUCKET_NAME = os.environ.get("FROGBOT_FILES_BUCKET", "")
MAX_ARTIFACT_SOURCE_BYTES = 1_000_000
MAX_ARTIFACT_BYTES = 8_000_000
ARTIFACT_FORMATS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
TEXT_ARTIFACT_FORMATS = {".txt", ".md", ".csv", ".json", ".html"}
USER_PREFIX_PATTERN = re.compile(r"^users/[a-f0-9]{64}/artifacts/[a-f0-9-]{32,64}$")
BOT_PREFIX_PATTERN = re.compile(
    r"^users/[a-f0-9]{64}/bots/[A-Za-z0-9][A-Za-z0-9_-]{0,63}/artifacts/[a-f0-9-]{32,64}$"
)
GROUP_PREFIX_PATTERN = re.compile(r"^groups/[a-f0-9-]{36}/artifacts/[a-f0-9-]{32,64}$")


def _valid_prefix(prefix: str) -> bool:
    return bool(
        USER_PREFIX_PATTERN.fullmatch(prefix)
        or BOT_PREFIX_PATTERN.fullmatch(prefix)
        or GROUP_PREFIX_PATTERN.fullmatch(prefix)
    )


def artifact_prefix_from_payload(
    payload: dict, actor_id: str | None = None
) -> str | None:
    value = payload.get("artifacts")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("artifacts must be an object")
    prefix = value.get("prefix")
    if not isinstance(prefix, str) or not _valid_prefix(prefix):
        raise ValueError("artifacts.prefix is invalid")
    if GROUP_PREFIX_PATTERN.fullmatch(prefix):
        if not isinstance(payload.get("group"), dict):
            raise ValueError("group artifact scope is invalid")
        # Group memory now supplies an actor, too. Bind that actor to the file
        # namespace instead of treating every non-null actor as a personal user.
        memory = payload.get("memory")
        if actor_id is not None or memory is not None:
            group_id = prefix.split("/")[1]
            expected_actor = hashlib.sha256(f"group:{group_id}".encode()).hexdigest()
            if (
                not isinstance(memory, dict)
                or memory.get("scope") != "group"
                or memory.get("actorId") != expected_actor
                or actor_id != expected_actor
            ):
                raise ValueError("group artifact scope is invalid")
        return prefix
    if not isinstance(actor_id, str) or not re.fullmatch(r"[a-f0-9]{64}", actor_id):
        raise ValueError("artifacts identity is invalid")
    if not prefix.startswith(f"users/{actor_id}/"):
        raise ValueError("artifacts.prefix does not match the invoking user")
    return prefix


def _artifact_name(value: Any) -> tuple[str, str, str]:
    if not isinstance(value, str):
        raise TypeError("filename must be a string")
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 100:
        raise ValueError("filename must be between 1 and 100 characters")
    extension = Path(name).suffix.lower()
    content_type = ARTIFACT_FORMATS.get(extension)
    if not content_type:
        raise ValueError(
            "filename must end in .txt, .md, .csv, .json, .html, .pdf, .docx, .xlsx, or .pptx"
        )
    stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(name).stem).strip(" .-")
    if not stem:
        stem = "FroggyBot artifact"
    safe_name = f"{stem[:80]}{extension}"
    return safe_name, extension, content_type


def _put_artifact(
    target, prefix: str, safe_name: str, body: bytes, content_type: str
) -> None:
    if not body or len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"generated artifact must be between 1 and {MAX_ARTIFACT_BYTES} bytes"
        )
    file_id = str(uuid.uuid4())
    encoded_name = urllib.parse.quote(safe_name, safe="")
    object_key = f"{prefix}/{file_id}--{encoded_name}"
    target.put_object(
        Bucket=FILES_BUCKET_NAME,
        Key=object_key,
        Body=body,
        ContentType=content_type,
        ContentDisposition=f"attachment; filename*=UTF-8''{encoded_name}",
        ServerSideEncryption="AES256",
    )


def artifact_tool(prefix: str, *, client=None):
    if not FILES_BUCKET_NAME or not _valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    target = client or boto3.client("s3")

    @tool
    def save_artifact(filename: str, content: str) -> str:
        """Save a downloadable file. Use Markdown for PDF/DOCX, CSV for XLSX, and --- between PPTX slides."""
        safe_name, extension, content_type = _artifact_name(filename)
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        source = content.encode("utf-8")
        if not source or len(source) > MAX_ARTIFACT_SOURCE_BYTES:
            raise ValueError(
                f"content must be between 1 and {MAX_ARTIFACT_SOURCE_BYTES} UTF-8 bytes"
            )
        body = (
            source
            if extension in TEXT_ARTIFACT_FORMATS
            else render_native_artifact(safe_name, extension, content)
        )
        _put_artifact(target, prefix, safe_name, body, content_type)
        return f"Saved {safe_name} for the user to download."

    return save_artifact
