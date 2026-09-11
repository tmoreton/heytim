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

IMAGE_MODEL_ID = os.environ.get(
    "FROGBOT_IMAGE_MODEL_ID", "openai/gpt-image-2.5-sunburst"
)
IMAGE_QUALITY = os.environ.get("FROGBOT_IMAGE_QUALITY", "high")
IMAGE_REQUEST_TIMEOUT_SECONDS = int(
    os.environ.get("FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS", "300")
)
IMAGE_MAX_ATTEMPTS = int(os.environ.get("FROGBOT_IMAGE_MAX_ATTEMPTS", "2"))
MAX_IMAGE_PROMPT_CHARS = 4_000
MAX_ENCODED_IMAGE_BYTES = 16_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 4_096
MAX_REFERENCE_IMAGES = 5
MAX_REFERENCE_SIDE = 1_536
ASPECT_RATIOS = {"square": "1:1", "youtube": "16:9", "portrait": "9:16"}
IMAGE_QUALITIES = {"auto", "low", "medium", "high", "xhigh", "max"}
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
COMPARISON_PATTERN = re.compile(
    r"\b(vs\.?|versus|compare|comparison|both|better|wins?|face[- ]?off)\b",
    re.IGNORECASE,
)

if not re.fullmatch(
    r"[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._-]{0,127}",
    IMAGE_MODEL_ID,
):
    raise ValueError("FROGBOT_IMAGE_MODEL_ID is invalid")
if IMAGE_QUALITY not in IMAGE_QUALITIES:
    raise ValueError("FROGBOT_IMAGE_QUALITY is invalid")
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


def _clean_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    clean = " ".join(value.split()).strip()
    if not clean or len(clean) > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum} characters")
    return clean


def _prompt(value: Any) -> str:
    return _clean_text(value, "prompt", MAX_IMAGE_PROMPT_CHARS)


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


def _normalized_png(body: bytes, *, size: tuple[int, int] | None = None) -> bytes:
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
        if size:
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
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


def _open_reference(reference: dict) -> Image.Image:
    try:
        source = Image.open(io.BytesIO(reference["body"]))
        if source.width < 64 or source.height < 64:
            raise ValueError("The selected reference image is too small")
        if source.width * source.height > MAX_IMAGE_PIXELS:
            raise ValueError("The selected reference image has too many pixels")
        source.seek(0)
        return ImageOps.exif_transpose(source).convert("RGBA")
    except (KeyError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("The selected reference image is not supported") from exc


def _reference(references: list[dict], number: Any) -> dict:
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or not 1 <= number <= len(references)
    ):
        raise ValueError("reference image number is unavailable")
    return references[number - 1]


def _reference_data_url(reference: dict) -> str:
    image = _open_reference(reference)
    image.thumbnail((MAX_REFERENCE_SIDE, MAX_REFERENCE_SIDE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 255:
        image.save(output, format="PNG", optimize=True)
        media_type = "image/png"
    else:
        image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
        media_type = "image/jpeg"
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _is_comparison(*values: str) -> bool:
    return bool(COMPARISON_PATTERN.search(" ".join(values)))


def _thumbnail_prompt(
    visual_brief: str,
    headline: str,
    subheadline: str,
    *,
    comparison: bool,
    has_portrait: bool,
    logo_count: int,
) -> str:
    copy = f'headline: "{headline}"'
    if subheadline:
        copy += f'; secondary line: "{subheadline}"'
    else:
        copy += "; no secondary line"
    story_direction = (
        "Create visual tension between the compared subjects with a cohesive warm-amber "
        "versus cool-cyan palette, without adding a literal split-screen seam unless the "
        "visual story truly needs one."
        if comparison
        else "Use intentional asymmetry and one unmistakable focal story."
    )
    reference_directions: list[str] = []
    next_reference = 1
    if has_portrait:
        reference_directions.append(
            f"Reference image {next_reference} is the presenter. Preserve the person's "
            "recognizable face, hair, and identity. Integrate them as a natural editorial "
            "cutout or photographed subject with believable edge light; do not put them "
            "inside a circle, avatar frame, or sticker."
        )
        next_reference += 1
    for index in range(logo_count):
        reference_directions.append(
            f"Reference image {next_reference + index} is an exact logo asset. Preserve its "
            "geometry, colors, and transparent silhouette. Integrate it cleanly into the "
            "scene; do not redraw it or place it inside a white tile, app card, or thick border."
        )
    if not reference_directions:
        reference_directions.append(
            "No reference images are supplied. Do not invent brand marks or recognizable people."
        )
    return (
        "Generate the complete, finished premium YouTube thumbnail—not a background plate. "
        "Compose for a 16:9 canvas that will be center-cropped to exactly 1280x720, keeping "
        "all essential faces, logos, and typography within the central 88 percent safe area. "
        f"The video's visual story is: {visual_brief}. {story_direction} Build one decisive "
        "focal hierarchy with large simple shapes, strong foreground/midground depth, crisp "
        "cinematic contrast, saturated but controlled color, and polished editorial tech-channel "
        "art direction that remains clear at phone size. Avoid generic desks full of monitors, "
        "rows of glowing spheres, fake dashboards, decorative UI, random letters, clutter, "
        "muddy darkness, watermarks, or unrelated futuristic filler. "
        f"Render exactly this copy with correct spelling and no other visible words: {copy}. "
        "Use bold, condensed, high-contrast display typography. The headline must dominate; "
        "the secondary line must be clearly subordinate and must not repeat the headline. "
        + " ".join(reference_directions)
    )


async def _invoke_image(
    client: httpx.AsyncClient,
    api_key: str,
    prompt: str,
    aspect_ratio: str,
    *,
    input_references: list[str] | None = None,
) -> bytes:
    request: dict[str, Any] = {
        "model": IMAGE_MODEL_ID,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": IMAGE_QUALITY,
        "output_format": "png",
    }
    if input_references:
        request["input_references"] = [
            {"type": "image_url", "image_url": {"url": item}}
            for item in input_references
        ]
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
                json=request,
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
    if response is None:
        raise RuntimeError("OpenRouter image generation did not respond")
    if response.status_code >= 400:
        raise _generation_error(response)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "OpenRouter image generation returned an invalid response"
        ) from exc
    return _response_image(payload)


def image_generation_tools(
    prefix: str,
    image_references: list[dict] | None = None,
    *,
    s3_client=None,
    http_client: httpx.AsyncClient | None = None,
    api_key_loader: Callable[[], Awaitable[str]] | None = None,
):
    if not artifacts.FILES_BUCKET_NAME or not artifacts._valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    storage = s3_client or boto3.client("s3")
    load_api_key = api_key_loader or _openrouter_api_key
    references = list(image_references or [])[:MAX_REFERENCE_IMAGES]

    async def generate(
        prompt: str, aspect_ratio: str, input_references: list[str] | None = None
    ) -> bytes:
        try:
            api_key = await load_api_key()
        except Exception as exc:
            raise RuntimeError(
                "OpenRouter image-generation credential lookup failed"
            ) from exc
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError("OpenRouter image-generation credential is empty")
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(IMAGE_REQUEST_TIMEOUT_SECONDS, connect=5)
        )
        try:
            return await _invoke_image(
                client,
                api_key,
                prompt,
                aspect_ratio,
                input_references=input_references,
            )
        finally:
            if owns_client:
                await client.aclose()

    @tool
    async def generate_image(
        filename: str, prompt: str, aspect_ratio: str = "square"
    ) -> str:
        """Create one original image with the configured OpenRouter image model."""
        safe_name = _safe_png_name(filename)
        clean_prompt = _prompt(prompt)
        if aspect_ratio not in ASPECT_RATIOS:
            raise ValueError("aspect_ratio must be square, youtube, or portrait")
        image = _normalized_png(
            await generate(clean_prompt, ASPECT_RATIOS[aspect_ratio])
        )
        artifacts._put_artifact(storage, prefix, safe_name, image, "image/png")
        return f"Saved {safe_name} as an original image created with OpenRouter."

    @tool
    async def create_youtube_thumbnail(
        filename: str,
        background_prompt: str,
        headline: str,
        subheadline: str = "",
        portrait_image_number: int = 0,
        logo_image_numbers: list[int] | None = None,
    ) -> str:
        """Create a complete 1280x720 thumbnail with OpenRouter, exact copy, and selected recent images."""
        safe_name = _safe_png_name(filename)
        clean_prompt = _clean_text(background_prompt, "background_prompt", 2_000)
        clean_headline = _clean_text(headline, "headline", 80)
        clean_subheadline = (
            _clean_text(subheadline, "subheadline", 100) if subheadline else ""
        )
        logo_numbers = list(logo_image_numbers or [])
        if len(logo_numbers) > 3:
            raise ValueError("logo_image_numbers can contain at most 3 images")

        selected: list[dict] = []
        if portrait_image_number:
            selected.append(_reference(references, portrait_image_number))
        for number in logo_numbers:
            selected.append(_reference(references, number))
        reference_urls = [_reference_data_url(item) for item in selected]
        comparison = _is_comparison(clean_prompt, clean_headline, clean_subheadline)
        complete_prompt = _thumbnail_prompt(
            clean_prompt,
            clean_headline,
            clean_subheadline,
            comparison=comparison,
            has_portrait=bool(portrait_image_number),
            logo_count=len(logo_numbers),
        )
        image = _normalized_png(
            await generate(complete_prompt, "16:9", reference_urls),
            size=(1280, 720),
        )
        artifacts._put_artifact(storage, prefix, safe_name, image, "image/png")
        used = " using the selected recent images" if selected else ""
        return (
            f"Saved {safe_name} as an OpenRouter-generated 1280x720 YouTube "
            f"thumbnail{used}."
        )

    return [generate_image, create_youtube_thumbnail]


__all__ = ["image_generation_tools"]
