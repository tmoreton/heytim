from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from strands import tool

from . import artifacts

IMAGE_MODEL_ID = os.environ.get(
    "FROGBOT_IMAGE_MODEL_ID", "stability.stable-image-core-v1:1"
)
IMAGE_REGION = os.environ.get("FROGBOT_IMAGE_REGION", "us-west-2")
IMAGE_REQUEST_TIMEOUT_SECONDS = int(
    os.environ.get("FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS", "300")
)
IMAGE_MAX_ATTEMPTS = int(os.environ.get("FROGBOT_IMAGE_MAX_ATTEMPTS", "4"))
MAX_IMAGE_PROMPT_CHARS = 4_000
MAX_ENCODED_IMAGE_BYTES = 12_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 4_096
MAX_REFERENCE_IMAGES = 5
ASPECT_RATIOS = {"square": "1:1", "youtube": "16:9", "portrait": "9:16"}
COMPARISON_PATTERN = re.compile(
    r"\b(vs\.?|versus|compare|comparison|both|better|wins?|face[- ]?off)\b",
    re.IGNORECASE,
)
DEFAULT_NEGATIVE_PROMPT = (
    "unreadable text, misspelled words, random letters, watermark, signature, "
    "duplicate subjects, blurry, low contrast"
)
THUMBNAIL_NEGATIVE_PROMPT = (
    f"{DEFAULT_NEGATIVE_PROMPT}, generic stock photo, generic desk with monitors, "
    "rows of glowing spheres, stock dashboard, tiny interface details, muddy darkness, "
    "weak hierarchy, flat lighting, cluttered composition, frames, cards, badges, people, faces"
)

if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,127}", IMAGE_MODEL_ID):
    raise ValueError("FROGBOT_IMAGE_MODEL_ID is invalid")
if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", IMAGE_REGION):
    raise ValueError("FROGBOT_IMAGE_REGION is invalid")
if not 30 <= IMAGE_REQUEST_TIMEOUT_SECONDS <= 600:
    raise ValueError("FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS must be between 30 and 600")
if not 1 <= IMAGE_MAX_ATTEMPTS <= 5:
    raise ValueError("FROGBOT_IMAGE_MAX_ATTEMPTS must be between 1 and 5")


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


def _decoded_image(encoded: Any) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Bedrock image generation returned no image")
    if len(encoded) > MAX_ENCODED_IMAGE_BYTES:
        raise RuntimeError("Bedrock image generation returned an oversized image")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(
            "Bedrock image generation returned invalid image data"
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
                "Bedrock image generation returned unsupported dimensions"
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
            "Bedrock image generation returned an unsupported image"
        ) from exc
    if not result or len(result) > artifacts.MAX_ARTIFACT_BYTES:
        raise RuntimeError("Bedrock image generation returned an oversized PNG")
    return result


def _client():
    return boto3.client(
        "bedrock-runtime",
        region_name=IMAGE_REGION,
        config=Config(
            retries={"total_max_attempts": IMAGE_MAX_ATTEMPTS, "mode": "adaptive"},
            connect_timeout=5,
            read_timeout=IMAGE_REQUEST_TIMEOUT_SECONDS,
        ),
    )


def _invoke_image(
    target,
    prompt: str,
    aspect_ratio: str,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
) -> bytes:
    request = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "aspect_ratio": aspect_ratio,
        "output_format": "png",
        "seed": secrets.randbelow(4_294_967_295),
    }
    try:
        response = target.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(request),
            contentType="application/json",
            accept="application/json",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"AccessDeniedException", "UnauthorizedException"}:
            message = "Bedrock image generation is not authorized"
        elif code in {"ThrottlingException", "TooManyRequestsException"}:
            message = "Bedrock image generation is temporarily rate limited"
        elif code in {
            "InternalServerException",
            "ModelTimeoutException",
            "ServiceUnavailableException",
        }:
            message = "Bedrock image generation is temporarily unavailable"
        else:
            message = "Bedrock image generation failed"
        raise RuntimeError(message) from exc

    body = response.get("body")
    if body is None or not hasattr(body, "read"):
        raise RuntimeError("Bedrock image generation returned an invalid response")
    try:
        raw = body.read()
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    try:
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(
            "Bedrock image generation returned an invalid response"
        ) from exc
    images = payload.get("images") if isinstance(payload, dict) else None
    finish_reasons = (
        payload.get("finish_reasons") if isinstance(payload, dict) else None
    )
    if not isinstance(images, list) or not images:
        if isinstance(finish_reasons, list) and any(finish_reasons):
            raise RuntimeError("Bedrock image generation was blocked by content safety")
        raise RuntimeError("Bedrock image generation returned no image")
    return _normalized_png(_decoded_image(images[0]))


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def _is_comparison(*values: str) -> bool:
    return bool(COMPARISON_PATTERN.search(" ".join(values)))


def _thumbnail_background_prompt(
    prompt: str, *, comparison: bool, has_portrait: bool, logo_count: int
) -> str:
    story = (
        "Build two opposing visual worlds with one hero element on each side, warm orange "
        "on the left and electric cyan-blue on the right, separated by a strong central "
        "tension line or diagonal energy."
        if comparison
        else "Build one dominant visual metaphor with an obvious focal subject and intentional asymmetry."
    )
    reserved = ["the upper 28 percent for a large headline"]
    if has_portrait:
        reserved.append("the lower-left for a portrait")
    if logo_count:
        reserved.append("the lower-right for logo marks")
    return (
        "Create a premium editorial YouTube thumbnail background designed to stay readable "
        f"at small mobile size. The video's visual idea is: {prompt}. {story} Use large crisp "
        "shapes, strong foreground and midground depth, saturated complementary color, "
        "cinematic rim lighting, dramatic clean contrast, and polished modern tech-channel "
        f"art direction. Keep {', and '.join(reserved)} visually quiet and uncluttered. "
        "Background artwork only; render no words, letters, numbers, logos, watermarks, UI "
        "screenshots, frames, cards, badges, people, or faces."
    )


def _grade_thumbnail(canvas: Image.Image, *, comparison: bool) -> None:
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = canvas.size
    draw.rectangle((0, 0, width, 205), fill=(2, 9, 18, 78))
    draw.rectangle((0, height - 150, width, height), fill=(2, 9, 18, 54))
    if comparison:
        draw.polygon(
            ((0, 0), (width * 0.58, 0), (width * 0.43, height), (0, height)),
            fill=(244, 91, 32, 54),
        )
        draw.polygon(
            (
                (width * 0.48, 0),
                (width, 0),
                (width, height),
                (width * 0.62, height),
            ),
            fill=(31, 117, 255, 50),
        )
        draw.line(
            ((width * 0.55, 0), (width * 0.52, height)),
            fill=(255, 255, 255, 72),
            width=5,
        )
    canvas.alpha_composite(overlay)


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


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    maximum_size: int,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int, int]]:
    for size in range(maximum_size, 23, -2):
        font = _font(size)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=max(1, size // 28))
        if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
            return font, bounds
    raise ValueError("thumbnail text is too long to fit legibly")


def _compose_thumbnail(
    background: bytes,
    references: list[dict],
    headline: str,
    subheadline: str,
    portrait_number: int,
    logo_numbers: list[int],
    *,
    comparison: bool,
) -> bytes:
    canvas = _cover(
        Image.open(io.BytesIO(background)).convert("RGB"), (1280, 720)
    ).convert("RGBA")
    canvas.alpha_composite(Image.new("RGBA", canvas.size, (0, 0, 0, 30)))
    _grade_thumbnail(canvas, comparison=comparison)
    draw = ImageDraw.Draw(canvas)

    if portrait_number:
        portrait = _cover(
            _open_reference(_reference(references, portrait_number)), (360, 360)
        )
        mask = Image.new("L", portrait.size, 0)
        ImageDraw.Draw(mask).ellipse((4, 4, 356, 356), fill=255)
        shadow = Image.new("RGBA", (388, 388), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((10, 14, 378, 382), fill=(0, 0, 0, 145))
        canvas.alpha_composite(shadow, (12, 320))
        border = Image.new("RGBA", portrait.size, (255, 255, 255, 255))
        canvas.paste(border, (28, 336), mask)
        inner = portrait.resize((340, 340), Image.Resampling.LANCZOS)
        inner_mask = mask.resize((340, 340), Image.Resampling.LANCZOS)
        canvas.paste(inner, (38, 346), inner_mask)

    selected_logos = [
        _open_reference(_reference(references, item)) for item in logo_numbers
    ]
    if selected_logos:
        card_width = 190
        gap = 22
        total_width = len(selected_logos) * card_width + (len(selected_logos) - 1) * gap
        start_x = 1240 - total_width
        for index, logo in enumerate(selected_logos):
            x = start_x + index * (card_width + gap)
            draw.rounded_rectangle(
                (x - 9, 429, x + card_width + 9, 637),
                radius=34,
                fill=(35, 116, 255, 82),
            )
            draw.rounded_rectangle(
                (x, 438, x + card_width, 628),
                radius=28,
                fill=(8, 18, 32, 224),
                outline=(255, 255, 255, 255),
                width=4,
            )
            logo.thumbnail((150, 150), Image.Resampling.LANCZOS)
            canvas.alpha_composite(
                logo,
                (x + (card_width - logo.width) // 2, 438 + (190 - logo.height) // 2),
            )

    title_draw = ImageDraw.Draw(canvas)
    title_font, title_bounds = _fit_text(title_draw, headline, 1120, 170, 112)
    title_width = title_bounds[2] - title_bounds[0]
    title_draw.text(
        ((1280 - title_width) / 2 - title_bounds[0], 58 - title_bounds[1]),
        headline,
        font=title_font,
        fill="white",
        stroke_width=max(3, title_font.size // 25),
        stroke_fill="#08131F",
    )
    if subheadline:
        sub_font, sub_bounds = _fit_text(title_draw, subheadline, 760, 90, 62)
        sub_width = sub_bounds[2] - sub_bounds[0]
        box_left = (1280 - sub_width) / 2 - 42
        box_top = 594
        box_right = (1280 + sub_width) / 2 + 42
        box_bottom = 684
        title_draw.rounded_rectangle(
            (box_left, box_top, box_right, box_bottom),
            radius=18,
            fill=(7, 18, 31, 232),
            outline="#FFFFFF",
            width=3,
        )
        title_draw.text(
            ((1280 - sub_width) / 2 - sub_bounds[0], 609 - sub_bounds[1]),
            subheadline,
            font=sub_font,
            fill="white",
        )

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return _normalized_png(output.getvalue())


def image_generation_tools(
    prefix: str,
    image_references: list[dict] | None = None,
    *,
    s3_client=None,
    bedrock_client=None,
):
    if not artifacts.FILES_BUCKET_NAME or not artifacts._valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    storage = s3_client or boto3.client("s3")
    generator = bedrock_client or _client()
    references = list(image_references or [])[:MAX_REFERENCE_IMAGES]

    @tool
    async def generate_image(
        filename: str, prompt: str, aspect_ratio: str = "square"
    ) -> str:
        """Create one original image with Bedrock. aspect_ratio is square, youtube, or portrait."""
        safe_name = _safe_png_name(filename)
        clean_prompt = _prompt(prompt)
        if aspect_ratio not in ASPECT_RATIOS:
            raise ValueError("aspect_ratio must be square, youtube, or portrait")
        image = await asyncio.to_thread(
            _invoke_image, generator, clean_prompt, ASPECT_RATIOS[aspect_ratio]
        )
        artifacts._put_artifact(storage, prefix, safe_name, image, "image/png")
        return f"Saved {safe_name} as an original image created with Amazon Bedrock."

    @tool
    async def create_youtube_thumbnail(
        filename: str,
        background_prompt: str,
        headline: str,
        subheadline: str = "",
        portrait_image_number: int = 0,
        logo_image_numbers: list[int] | None = None,
    ) -> str:
        """Create a 1280x720 thumbnail with crisp text and exact recent user images selected by number."""
        safe_name = _safe_png_name(filename)
        clean_prompt = _prompt(background_prompt)
        clean_headline = _clean_text(headline, "headline", 80)
        clean_subheadline = (
            _clean_text(subheadline, "subheadline", 100) if subheadline else ""
        )
        logo_numbers = list(logo_image_numbers or [])
        if len(logo_numbers) > 3:
            raise ValueError("logo_image_numbers can contain at most 3 images")
        if portrait_image_number:
            _reference(references, portrait_image_number)
        for number in logo_numbers:
            _reference(references, number)
        comparison = _is_comparison(clean_prompt, clean_headline, clean_subheadline)
        background = await asyncio.to_thread(
            _invoke_image,
            generator,
            _thumbnail_background_prompt(
                clean_prompt,
                comparison=comparison,
                has_portrait=bool(portrait_image_number),
                logo_count=len(logo_numbers),
            ),
            "16:9",
            THUMBNAIL_NEGATIVE_PROMPT,
        )
        image = _compose_thumbnail(
            background,
            references,
            clean_headline,
            clean_subheadline,
            portrait_image_number,
            logo_numbers,
            comparison=comparison,
        )
        artifacts._put_artifact(storage, prefix, safe_name, image, "image/png")
        used = (
            " using the selected recent images"
            if portrait_image_number or logo_numbers
            else ""
        )
        return f"Saved {safe_name} as a 1280x720 YouTube thumbnail{used}."

    return [generate_image, create_youtube_thumbnail]


__all__ = ["image_generation_tools"]
