from __future__ import annotations

import asyncio
import base64
import binascii
import io
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import boto3
import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from strands import tool

from model.load import OPENROUTER_BASE_URL, _openrouter_api_key

from . import artifacts

IMAGE_MODEL_ID = os.environ.get("FROGBOT_IMAGE_MODEL_ID", "meta/muse-image")
IMAGE_REQUEST_TIMEOUT_SECONDS = int(
    os.environ.get("FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS", "300")
)
IMAGE_MAX_ATTEMPTS = int(os.environ.get("FROGBOT_IMAGE_MAX_ATTEMPTS", "2"))
MAX_IMAGE_PROMPT_CHARS = 4_000
MAX_ENCODED_IMAGE_BYTES = 12_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 4_096
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}

if not re.fullmatch(
    r"[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._-]{0,127}",
    IMAGE_MODEL_ID,
):
    raise ValueError("FROGBOT_IMAGE_MODEL_ID is invalid")
if not 30 <= IMAGE_REQUEST_TIMEOUT_SECONDS <= 600:
    raise ValueError("FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS must be between 30 and 600")
if not 1 <= IMAGE_MAX_ATTEMPTS <= 3:
    raise ValueError("FROGBOT_IMAGE_MAX_ATTEMPTS must be between 1 and 3")


def _safe_png_name(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("filename must be text")
    raw_name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if Path(raw_name).suffix.lower() != ".png":
        raise ValueError("filename must end in .png")
    stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(raw_name).stem).strip(" .-")
    return f"{(stem or 'FroggyBot image')[:80]}.png"


def _prompt(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("prompt must be text")
    clean = " ".join(value.split()).strip()
    if not clean or len(clean) > MAX_IMAGE_PROMPT_CHARS:
        raise ValueError(
            f"prompt must be between 1 and {MAX_IMAGE_PROMPT_CHARS} characters"
        )
    return clean


def _response_image(payload: Any) -> bytes:
    data = payload.get("data") if isinstance(payload, dict) else None
    item = data[0] if isinstance(data, list) and data else None
    encoded = item.get("b64_json") if isinstance(item, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("OpenRouter image generation returned no image")
    if len(encoded) > MAX_ENCODED_IMAGE_BYTES:
        raise RuntimeError("OpenRouter image generation returned an oversized image")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(
            "OpenRouter image generation returned invalid image data"
        ) from exc


def _normalized_png(body: bytes) -> bytes:
    try:
        source = Image.open(io.BytesIO(body))
        width, height = source.size
        if (
            width < 64
            or height < 64
            or width > MAX_IMAGE_SIDE
            or height > MAX_IMAGE_SIDE
            or width * height > MAX_IMAGE_PIXELS
        ):
            raise RuntimeError(
                "OpenRouter image generation returned unsupported dimensions"
            )
        source.seek(0)
        image = ImageOps.exif_transpose(source)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        result = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(
            "OpenRouter image generation returned an unsupported image"
        ) from exc
    if not result or len(result) > artifacts.MAX_ARTIFACT_BYTES:
        raise RuntimeError("OpenRouter image generation returned an oversized PNG")
    return result


def _retry_delay(response: httpx.Response, attempt: int) -> float | None:
    if (
        attempt >= IMAGE_MAX_ATTEMPTS
        or response.status_code not in RETRYABLE_STATUS_CODES
    ):
        return None
    retry_after = response.headers.get("retry-after")
    try:
        delay = float(retry_after) if retry_after is not None else 2 ** (attempt - 1)
    except ValueError:
        delay = 2 ** (attempt - 1)
    return min(30.0, max(0.0, delay))


def _generation_error(response: httpx.Response) -> RuntimeError:
    if response.status_code in {401, 403}:
        message = "OpenRouter rejected the image-generation credential"
    elif response.status_code == 402:
        message = "OpenRouter image-generation credits are unavailable"
    elif response.status_code == 429:
        message = "OpenRouter image generation is temporarily rate limited"
    else:
        message = f"OpenRouter image generation failed (HTTP {response.status_code})"
    return RuntimeError(message)


def image_generation_tool(
    prefix: str,
    *,
    s3_client=None,
    http_client: httpx.AsyncClient | None = None,
    api_key_loader: Callable[[], Awaitable[str]] | None = None,
):
    if not artifacts.FILES_BUCKET_NAME or not artifacts._valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    target = s3_client or boto3.client("s3")
    load_api_key = api_key_loader or _openrouter_api_key

    @tool
    async def generate_image(filename: str, prompt: str) -> str:
        """Create one original image from a text prompt with Muse Image and save it as a PNG."""
        safe_name = _safe_png_name(filename)
        clean_prompt = _prompt(prompt)
        try:
            api_key = await load_api_key()
        except Exception as exc:
            raise RuntimeError("OpenRouter image-generation credential lookup failed") from exc
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError("OpenRouter image-generation credential is empty")

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(IMAGE_REQUEST_TIMEOUT_SECONDS, connect=5)
        )
        try:
            response = None
            for attempt in range(1, IMAGE_MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(
                        f"{OPENROUTER_BASE_URL.rstrip('/')}/images",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "HTTP-Referer": "https://froggybot.com",
                            "X-OpenRouter-Title": "FroggyBot",
                        },
                        json={"model": IMAGE_MODEL_ID, "prompt": clean_prompt},
                    )
                except httpx.RequestError as exc:
                    if attempt >= IMAGE_MAX_ATTEMPTS:
                        raise RuntimeError(
                            "OpenRouter image generation could not be reached"
                        ) from exc
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                delay = _retry_delay(response, attempt)
                if delay is None:
                    break
                await asyncio.sleep(delay)
            if response is None or response.status_code >= 400:
                if response is None:
                    raise RuntimeError("OpenRouter image generation did not respond")
                raise _generation_error(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    "OpenRouter image generation returned an invalid response"
                ) from exc
            image = _normalized_png(_response_image(payload))
        finally:
            if owns_client:
                await client.aclose()

        artifacts._put_artifact(target, prefix, safe_name, image, "image/png")
        return f"Saved {safe_name} as an original image created with Muse Image."

    return generate_image


__all__ = ["image_generation_tool"]
