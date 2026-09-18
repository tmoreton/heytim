from __future__ import annotations

import hashlib
import io
import math
import os
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import boto3
from PIL import Image, UnidentifiedImageError
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
PNG_CONTENT_TYPE = "image/png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
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
    target,
    prefix: str,
    safe_name: str,
    body: bytes,
    content_type: str,
    *,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not body or len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"generated artifact must be between 1 and {MAX_ARTIFACT_BYTES} bytes"
        )
    file_id = str(uuid.uuid4())
    encoded_name = urllib.parse.quote(safe_name, safe="")
    object_key = f"{prefix}/{file_id}--{encoded_name}"
    request = {
        "Bucket": FILES_BUCKET_NAME,
        "Key": object_key,
        "Body": body,
        "ContentType": content_type,
        "ContentDisposition": f"attachment; filename*=UTF-8''{encoded_name}",
    }
    if metadata:
        encoded_metadata: dict[str, str] = {}
        remaining_bytes = 1_400
        for key, value in metadata.items():
            clean_key = str(key).lower()
            if value is None or not re.fullmatch(r"[a-z0-9-]{1,40}", clean_key):
                continue
            encoded = urllib.parse.quote(str(value), safe=":/?&=%-._~")
            available = remaining_bytes - len(clean_key)
            if available <= 0:
                break
            encoded_metadata[clean_key] = encoded[:available]
            remaining_bytes -= len(clean_key) + len(encoded_metadata[clean_key])
        if encoded_metadata:
            request["Metadata"] = encoded_metadata
    target.put_object(
        **request,
    )
    return {
        "artifactId": file_id,
        "filename": safe_name,
        "contentType": content_type,
        "size": len(body),
        "objectKey": object_key,
    }


def put_png_artifact(
    prefix: str,
    filename: Any,
    body: bytes,
    *,
    client=None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Store a trusted, generated PNG in the caller's scoped artifact prefix."""
    if not FILES_BUCKET_NAME or not _valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    if not isinstance(filename, str):
        raise TypeError("filename must be a string")
    raw_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if Path(raw_name).suffix.lower() != ".png":
        raise ValueError("filename must end in .png")
    stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(raw_name).stem).strip(" .-")
    safe_name = f"{(stem or 'FroggyBot screenshot')[:80]}.png"
    _validated_points_png(body)
    return _put_artifact(
        client or boto3.client("s3"),
        prefix,
        safe_name,
        body,
        PNG_CONTENT_TYPE,
        metadata=metadata,
    )


def _validated_points_png(body: Any) -> Image.Image:
    if not isinstance(body, bytes) or not body.startswith(PNG_SIGNATURE):
        raise ValueError("screenshot must be a PNG image")
    try:
        with Image.open(io.BytesIO(body)) as source:
            source.load()
            if source.format != "PNG":
                raise ValueError("screenshot must be a PNG image")
            if (
                source.width < 80
                or source.height < 40
                or source.width > 2_048
                or source.height > 2_048
                or source.width * source.height > 2_500_000
            ):
                raise ValueError("screenshot dimensions are unsupported")
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("screenshot must be a PNG image") from exc
    if all(low == high for low, high in image.getextrema()):
        raise ValueError("screenshot is blank or uniform")
    return image


def crop_points_screenshot(body: Any, bounding_box: Any) -> bytes:
    """Crop a CSS-scale viewport PNG to one verified browser element."""
    image = _validated_points_png(body)
    if not isinstance(bounding_box, dict):
        raise TypeError("points-price card bounds are unavailable")
    values = [bounding_box.get(field) for field in ("x", "y", "width", "height")]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise ValueError("points-price card bounds are unavailable")
    x, y, width, height = values
    if width < 80 or height < 40:
        raise ValueError("points-price card is too small to capture")
    left = max(0, math.floor(x))
    top = max(0, math.floor(y))
    right = min(image.width, math.ceil(x + width))
    bottom = min(image.height, math.ceil(y + height))
    if right - left < 80 or bottom - top < 40:
        raise ValueError("points-price card is outside the visible browser area")
    cropped = image.crop((left, top, right, bottom))
    if all(low == high for low, high in cropped.getextrema()):
        raise ValueError("screenshot is blank or uniform")
    output = io.BytesIO()
    cropped.save(output, format="PNG", optimize=True)
    result = output.getvalue()
    if not result or len(result) > MAX_ARTIFACT_BYTES:
        raise ValueError("screenshot is too large")
    return result


def load_png_artifact(prefix: str, artifact_id: Any, *, client=None) -> dict[str, Any]:
    """Load one generated PNG by UUID without allowing cross-prefix access."""
    if not FILES_BUCKET_NAME or not _valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    if not isinstance(artifact_id, str):
        raise TypeError("inline image ID must be a string")
    try:
        parsed_id = str(uuid.UUID(artifact_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("inline image ID is invalid") from exc
    if parsed_id != artifact_id.lower():
        raise ValueError("inline image ID is invalid")
    target = client or boto3.client("s3")
    listing = target.list_objects_v2(
        Bucket=FILES_BUCKET_NAME,
        Prefix=f"{prefix}/{parsed_id}--",
        MaxKeys=2,
    )
    matches = [
        item.get("Key")
        for item in listing.get("Contents", [])
        if isinstance(item, dict) and isinstance(item.get("Key"), str)
    ]
    if len(matches) != 1:
        raise ValueError("inline image is unavailable")
    object_key = matches[0]
    encoded_name = object_key.rsplit("/", 1)[-1].split("--", 1)[-1]
    filename = urllib.parse.unquote(encoded_name)
    if Path(filename).suffix.lower() != ".png":
        raise ValueError("inline image is not a PNG")
    response = target.get_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
    if response.get("ContentType") != PNG_CONTENT_TYPE:
        raise ValueError("inline image is not a PNG")
    stream = response.get("Body")
    if stream is None or not hasattr(stream, "read"):
        raise ValueError("inline image is unavailable")
    body = stream.read(MAX_ARTIFACT_BYTES + 1)
    if (
        not isinstance(body, bytes)
        or not body.startswith(PNG_SIGNATURE)
        or len(body) > MAX_ARTIFACT_BYTES
    ):
        raise ValueError("inline image is invalid")
    return {
        "artifactId": parsed_id,
        "filename": filename,
        "contentType": PNG_CONTENT_TYPE,
        "body": body,
        "metadata": response.get("Metadata", {}),
    }


def artifact_tool(prefix: str, *, client=None):
    if not FILES_BUCKET_NAME or not _valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    target = client or boto3.client("s3")

    @tool
    def save_artifact(filename: str, content: str) -> str:
        """Create a file only for an explicit download, export, or native-document request.

        Do not use this for an ordinary report, plan, table, or Markdown response. Use
        Markdown source for PDF/DOCX, CSV for XLSX, and `---` between PPTX slides.
        """
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
