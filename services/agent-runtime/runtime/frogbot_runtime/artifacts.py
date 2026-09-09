from __future__ import annotations

import base64
import hashlib
import json
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
IMAGE_MODEL_ID = os.environ.get(
    "FROGBOT_IMAGE_MODEL_ID", "stability.stable-image-core-v1:1"
)
IMAGE_MODEL_REGION = os.environ.get("FROGBOT_IMAGE_MODEL_REGION", "us-west-2")
IMAGE_ASPECT_RATIOS = {
    "square": "1:1",
    "landscape": "16:9",
    "portrait": "9:16",
}
IMAGE_STYLES = {
    "3D_ANIMATED_FAMILY_FILM": "polished 3D animated family film",
    "DESIGN_SKETCH": "clean professional design sketch",
    "FLAT_VECTOR_ILLUSTRATION": "crisp flat vector illustration",
    "GRAPHIC_NOVEL_ILLUSTRATION": "dramatic graphic novel illustration",
    "MAXIMALISM": "richly detailed maximalist artwork",
    "MIDCENTURY_RETRO": "mid-century retro illustration",
    "PHOTOREALISM": "photorealistic professional photography",
    "SOFT_DIGITAL_PAINTING": "soft digital painting",
}
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


def image_tool(prefix: str, *, client=None, s3_client=None):
    if not FILES_BUCKET_NAME or not _valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    target = s3_client or boto3.client("s3")
    bedrock = client or boto3.client(
        "bedrock-runtime",
        region_name=IMAGE_MODEL_REGION,
        config=Config(
            retries={"total_max_attempts": 3, "mode": "adaptive"},
            connect_timeout=5,
            read_timeout=300,
        ),
    )

    @tool
    def generate_image(
        filename: str,
        prompt: str,
        orientation: str = "square",
        style: str = "PHOTOREALISM",
        negative_prompt: str = "text, watermark, logo, low resolution, distortion",
    ) -> str:
        """Create a new PNG from text only. Cannot edit or preserve reference images."""
        if not isinstance(filename, str):
            raise TypeError("filename must be a string")
        raw_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if Path(raw_name).suffix.lower() != ".png":
            raise ValueError("filename must end in .png")
        stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(raw_name).stem).strip(" .-")
        safe_name = f"{(stem or 'FroggyBot image')[:80]}.png"
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1024:
            raise ValueError("prompt must be between 1 and 1024 characters")
        if not isinstance(negative_prompt, str) or len(negative_prompt.strip()) > 1024:
            raise ValueError("negative_prompt must be at most 1024 characters")
        if orientation not in IMAGE_ASPECT_RATIOS:
            raise ValueError("orientation must be square, landscape, or portrait")
        if style not in IMAGE_STYLES:
            raise ValueError("style is not supported")
        request = {
            "prompt": f"{prompt.strip()}. Visual style: {IMAGE_STYLES[style]}.",
            "aspect_ratio": IMAGE_ASPECT_RATIOS[orientation],
            "output_format": "png",
            **(
                {"negative_prompt": negative_prompt.strip()}
                if negative_prompt.strip()
                else {}
            ),
        }
        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request).encode("utf-8"),
        )
        result = json.loads(response["body"].read())
        finish_reasons = result.get("finish_reasons")
        if (
            isinstance(finish_reasons, list)
            and finish_reasons
            and finish_reasons[0] is not None
        ):
            raise RuntimeError(
                "Image generation was filtered or could not be completed"
            )
        images = result.get("images")
        if not isinstance(images, list) or not images or not isinstance(images[0], str):
            message = result.get("error")
            raise RuntimeError(
                message
                if isinstance(message, str) and message
                else "Image generation failed"
            )
        try:
            body = base64.b64decode(images[0], validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Image generation returned invalid data") from exc
        if not body.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Image generation did not return a PNG image")
        _put_artifact(target, prefix, safe_name, body, "image/png")
        return f"Saved {safe_name} for the user to download."

    return generate_image
