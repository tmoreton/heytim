"""Stage durable workspace asset revisions for promotion by the API worker."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from strands import tool

from .artifact_renderers import render_native_artifact
from .artifacts import (
    ARTIFACT_FORMATS,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_SOURCE_BYTES,
    PNG_CONTENT_TYPE,
    TEXT_ARTIFACT_FORMATS,
    _artifact_name,
    _put_artifact,
    _validated_points_png,
)

FILES_BUCKET_NAME = os.environ.get("HEYTIM_FILES_BUCKET", "")
MAX_WORKSPACE_ASSETS = 50
MAX_ASSET_KEY_CHARS = 160
_ACTOR = re.compile(r"^[a-f0-9]{64}$")
_GROUP_PREFIX = re.compile(r"^groups/[a-f0-9-]{36}/uploads/$")
_ASSET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
_TEXT_EXTENSIONS = frozenset(TEXT_ARTIFACT_FORMATS)
_NATIVE_EXTENSIONS = frozenset(ARTIFACT_FORMATS) - _TEXT_EXTENSIONS


def _valid_asset_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _ASSET_KEY.fullmatch(value)
        or "//" in value
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError(
            "asset_key must be a stable path-like identifier up to 160 characters"
        )
    return value


def _workspace_base(payload: dict, actor_id: str | None) -> str:
    group_prefix = payload.get("attachmentPrefix")
    if group_prefix is not None:
        if (
            not isinstance(payload.get("group"), dict)
            or not isinstance(group_prefix, str)
            or not _GROUP_PREFIX.fullmatch(group_prefix)
        ):
            raise ValueError("workspace asset scope is invalid")
        return group_prefix.removesuffix("uploads/") + "workspace/"
    bot = payload.get("bot")
    bot_id = bot.get("id") if isinstance(bot, dict) else None
    if (
        not isinstance(actor_id, str)
        or not _ACTOR.fullmatch(actor_id)
        or not isinstance(bot_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bot_id)
    ):
        raise ValueError("workspace asset scope is invalid")
    return f"users/{actor_id}/bots/{bot_id}/workspace/"


def workspace_assets_from_payload(
    payload: dict, actor_id: str | None
) -> list[dict[str, Any]]:
    raw = payload.get("workspaceAssets")
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_WORKSPACE_ASSETS:
        raise ValueError("workspaceAssets is invalid")
    base = _workspace_base(payload, actor_id)
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("workspace asset is invalid")
        asset_key = _valid_asset_key(item.get("assetKey"))
        file_id = item.get("id")
        name = item.get("name")
        revision = item.get("revision")
        object_key = item.get("objectKey")
        source_object_key = item.get("sourceObjectKey")
        try:
            parsed_id = str(uuid.UUID(file_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("workspace asset identity is invalid") from exc
        revision_prefix = f"{base}{parsed_id}/revisions/{revision}/"
        object_pattern = re.compile(
            re.escape(revision_prefix)
            + r"(?:[a-f0-9]{16}/)?"
            + re.escape(name if isinstance(name, str) else "")
        )
        if (
            asset_key in seen
            or not isinstance(name, str)
            or not name
            or len(name) > 100
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or type(revision) is not int
            or revision < 1
            or not isinstance(object_key, str)
            or object_pattern.fullmatch(object_key) is None
            or (
                source_object_key is not None
                and (
                    not isinstance(source_object_key, str)
                    or source_object_key
                    != object_key.rsplit("/", 1)[0] + "/source.txt"
                    or source_object_key == object_key
                )
            )
        ):
            raise ValueError("workspace asset metadata is invalid")
        assets.append(
            {
                "id": parsed_id,
                "assetKey": asset_key,
                "name": name,
                "revision": revision,
                "objectKey": object_key,
                **(
                    {"sourceObjectKey": source_object_key}
                    if source_object_key is not None
                    else {}
                ),
                **(
                    {"updatedAt": item["updatedAt"]}
                    if isinstance(item.get("updatedAt"), str)
                    else {}
                ),
            }
        )
        seen.add(asset_key)
    return assets


def _workspace_name(filename: Any) -> tuple[str, str, str]:
    if isinstance(filename, str) and Path(filename).suffix.lower() == ".png":
        raw_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(raw_name).stem).strip(
            " .-"
        )
        return f"{(stem or 'HeyTim image')[:80]}.png", ".png", PNG_CONTENT_TYPE
    return _artifact_name(filename)


def _decode_png(content: str) -> bytes:
    value = content.strip()
    if value.startswith("data:image/png;base64,"):
        value = value.split(",", 1)[1]
    try:
        body = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("PNG content must be valid base64") from exc
    _validated_points_png(body)
    return body


def workspace_asset_tools(
    artifact_prefix: str,
    assets: list[dict[str, Any]],
    *,
    client: Any = None,
) -> list[Any]:
    """Return read and staged-save tools for one authorized workspace scope."""
    if "/bots/" not in artifact_prefix and not artifact_prefix.startswith("groups/"):
        return []
    if not FILES_BUCKET_NAME:
        raise ValueError("Workspace storage is not configured")
    target = client or boto3.client(
        "s3",
        config=Config(
            retries={"total_max_attempts": 4, "mode": "adaptive"},
            connect_timeout=3,
            read_timeout=20,
        ),
    )
    by_key = {item["assetKey"]: item for item in assets}

    @tool
    def read_workspace_asset(asset_key: str) -> str:
        """Read the editable source for an existing durable workspace asset."""
        key = _valid_asset_key(asset_key)
        item = by_key.get(key)
        if item is None:
            raise ValueError("Workspace asset not found")
        object_key = item.get("sourceObjectKey") or item["objectKey"]
        response = target.get_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
        stream = response.get("Body")
        if stream is None or not hasattr(stream, "read"):
            raise ValueError("Workspace asset source is unavailable")
        try:
            body = stream.read(MAX_ARTIFACT_SOURCE_BYTES + 1)
        finally:
            stream.close()
        if not body or len(body) > MAX_ARTIFACT_SOURCE_BYTES:
            raise ValueError("Workspace asset source is empty or too large")
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "This workspace asset has no editable text source; attach it for review"
            ) from exc
        return content

    @tool
    def save_workspace_asset(asset_key: str, filename: str, content: str) -> str:
        """Create or revise one durable workspace asset without making duplicates.

        Reuse the same stable asset_key on every revision. Use Markdown source for
        PDF/DOCX, CSV source for XLSX, `---` between PPTX slides, and base64 for PNG.
        Read an existing asset first when its prior content must be preserved.
        """
        key = _valid_asset_key(asset_key)
        safe_name, extension, content_type = _workspace_name(filename)
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        source = content.encode("utf-8")
        if not source or len(source) > MAX_ARTIFACT_SOURCE_BYTES:
            raise ValueError(
                f"content must be between 1 and {MAX_ARTIFACT_SOURCE_BYTES} UTF-8 bytes"
            )
        if extension == ".png":
            body = _decode_png(content)
        elif extension in _TEXT_EXTENSIONS:
            body = source
        elif extension in _NATIVE_EXTENSIONS:
            body = render_native_artifact(safe_name, extension, content)
        else:  # pragma: no cover - _workspace_name owns the format allowlist.
            raise ValueError("Workspace asset format is unsupported")
        if not body or len(body) > MAX_ARTIFACT_BYTES:
            raise ValueError("Workspace asset is empty or too large")

        current = by_key.get(key)
        expected_revision = current["revision"] if current else 0
        metadata = {
            "heytim-purpose": "workspace-asset",
            "workspace-asset-key": key,
            "workspace-expected-revision": str(expected_revision),
            "workspace-sha256": hashlib.sha256(body).hexdigest(),
        }
        staged = _put_artifact(
            target,
            artifact_prefix,
            safe_name,
            body,
            content_type,
            metadata=metadata,
        )
        source_key = None
        if extension in _NATIVE_EXTENSIONS:
            source_key = (
                f"{artifact_prefix}/workspace-sources/"
                f"{staged['artifactId']}.source"
            )
            target.put_object(
                Bucket=FILES_BUCKET_NAME,
                Key=source_key,
                Body=source,
                ContentType="text/plain; charset=utf-8",
            )
            # Metadata is replaced in-place so the worker can validate the companion.
            target.copy_object(
                Bucket=FILES_BUCKET_NAME,
                CopySource={"Bucket": FILES_BUCKET_NAME, "Key": staged["objectKey"]},
                Key=staged["objectKey"],
                ContentType=content_type,
                ContentDisposition=(
                    "attachment; filename*=UTF-8''"
                    + urllib.parse.quote(safe_name, safe="")
                ),
                MetadataDirective="REPLACE",
                Metadata={
                    **metadata,
                    "workspace-source-key": urllib.parse.quote(source_key, safe="/-._~"),
                },
            )
        return (
            f"Staged {safe_name} as workspace asset {key}; it will become revision "
            f"{expected_revision + 1} when this response completes."
        )

    return [read_workspace_asset, save_workspace_asset]


__all__ = ["workspace_asset_tools", "workspace_assets_from_payload"]
