from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import boto3
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from strands import tool

from . import artifacts
from .meme_templates import (
    MAX_MEME_SEARCH_CHARS,
    MAX_MEME_SEARCH_RESULTS,
    MAX_MEME_TEMPLATE_BYTES,
    matching_templates,
    read_s3_object,
    template_catalog,
)

MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 1_600
MAX_MEME_TEXT_CHARS = 300
MAX_MEME_CAPTIONS = 20
MEME_LAYOUTS = {"classic", "top_only", "bottom_only", "caption_bar"}


def image_attachments_from_messages(messages: list[dict]) -> list[bytes]:
    if not messages:
        return []
    images = []
    for block in messages[-1].get("content", []):
        image = block.get("image") if isinstance(block, dict) else None
        source = image.get("source") if isinstance(image, dict) else None
        body = source.get("bytes") if isinstance(source, dict) else None
        if isinstance(body, bytes):
            images.append(body)
    return images


def _safe_png_name(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("filename must be text")
    raw_name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if Path(raw_name).suffix.lower() != ".png":
        raise ValueError("filename must end in .png")
    stem = re.sub(r"[^A-Za-z0-9 _.-]", "-", Path(raw_name).stem).strip(" .-")
    return f"{(stem or 'FroggyBot meme')[:80]}.png"


def _clean_caption(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text")
    clean = " ".join(value.split()).strip()
    if len(clean) > MAX_MEME_TEXT_CHARS:
        raise ValueError(
            f"{field_name} must be at most {MAX_MEME_TEXT_CHARS} characters"
        )
    return clean


def _clean_captions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_MEME_CAPTIONS:
        raise TypeError(f"texts must be a list with at most {MAX_MEME_CAPTIONS} items")
    return [_clean_caption(item, f"texts[{index}]") for index, item in enumerate(value)]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        chunk = ""
        for character in word:
            candidate = f"{chunk}{character}"
            if chunk and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(chunk)
                chunk = character
            else:
                chunk = candidate
        current = chunk
    if current:
        lines.append(current)
    return lines


def _fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    width: int,
    max_height: int,
    *,
    maximum_size: int,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int, int]]:
    minimum_size = max(14, width // 40)
    for size in range(maximum_size, minimum_size - 1, -2):
        font = _font(size)
        wrapped = "\n".join(_wrap_lines(draw, text, font, width))
        bbox = draw.multiline_textbbox(
            (0, 0), wrapped, font=font, spacing=max(2, size // 8), align="center"
        )
        if bbox[2] - bbox[0] <= width and bbox[3] - bbox[1] <= max_height:
            return wrapped, font, bbox
    raise ValueError("Caption is too long to fit legibly on this image")


def _open_image(body: bytes) -> Image.Image:
    try:
        source = Image.open(io.BytesIO(body))
        width, height = source.size
        if width < 64 or height < 64:
            raise ValueError("The selected image is too small")
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError("The selected image has too many pixels")
        source.seek(0)
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
        return image
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The selected image is not supported") from exc


def _draw_template_caption(image: Image.Image, text: str, box: dict) -> None:
    if not text:
        return
    left = round(box["x"] * image.width)
    top = round(box["y"] * image.height)
    width = max(12, round(box["width"] * image.width))
    height = max(12, round(box["height"] * image.height))
    surface = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(surface)
    padding = max(2, min(width, height) // 30)
    maximum_size = max(
        14,
        min(
            height - (2 * padding),
            round(image.width * box.get("fontMaxSize", 0.12)),
        ),
    )
    rendered_text = text.upper() if box["uppercase"] else text
    wrapped, font, bbox = _fitted_text(
        draw,
        rendered_text,
        width - (2 * padding),
        height - (2 * padding),
        maximum_size=maximum_size,
    )
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    desired_x = {
        "left": padding,
        "center": (width - text_width) / 2,
        "right": width - padding - text_width,
    }[box["horizontalAlign"]]
    desired_y = {
        "top": padding,
        "middle": (height - text_height) / 2,
        "bottom": height - padding - text_height,
    }[box["verticalAlign"]]
    stroke_width = round(box["strokeWidth"] * image.width)
    if box["strokeWidth"] > 0:
        stroke_width = max(1, stroke_width)
    draw.multiline_text(
        (desired_x - bbox[0], desired_y - bbox[1]),
        wrapped,
        font=font,
        fill=box["fill"],
        stroke_width=stroke_width,
        stroke_fill=box["stroke"],
        spacing=max(2, font.size // 8),
        align=box["horizontalAlign"],
    )
    if box["rotation"]:
        surface = surface.rotate(
            -box["rotation"], resample=Image.Resampling.BICUBIC, expand=True
        )
        left += (width - surface.width) // 2
        top += (height - surface.height) // 2
    image.paste(surface, (left, top), surface)


def _draw_centered(
    image: Image.Image,
    text: str,
    *,
    at_bottom: bool,
    fill: str,
    stroke_fill: str,
) -> None:
    if not text:
        return
    draw = ImageDraw.Draw(image)
    margin = max(12, image.width // 32)
    maximum_size = max(28, image.width // 11)
    wrapped, font, bbox = _fitted_text(
        draw,
        text.upper(),
        image.width - (2 * margin),
        int(image.height * 0.36),
        maximum_size=maximum_size,
    )
    text_height = bbox[3] - bbox[1]
    y = image.height - margin - text_height if at_bottom else margin
    stroke_width = max(2, image.width // 240)
    draw.multiline_text(
        (image.width / 2, y),
        wrapped,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
        spacing=max(2, font.size // 8),
        align="center",
        anchor="ma",
    )


def _caption_bar(image: Image.Image, text: str) -> Image.Image:
    if not text:
        raise ValueError("caption_bar requires top_text")
    probe = Image.new("RGB", image.size, "white")
    draw = ImageDraw.Draw(probe)
    margin = max(16, image.width // 24)
    wrapped, font, bbox = _fitted_text(
        draw,
        text,
        image.width - (2 * margin),
        int(image.height * 0.45),
        maximum_size=max(24, image.width // 16),
    )
    bar_height = bbox[3] - bbox[1] + (2 * margin)
    result = Image.new("RGB", (image.width, image.height + bar_height), "white")
    result.paste(image, (0, bar_height))
    ImageDraw.Draw(result).multiline_text(
        (image.width / 2, margin),
        wrapped,
        font=font,
        fill="black",
        spacing=max(2, font.size // 8),
        align="center",
        anchor="ma",
    )
    return result


def meme_tools(prefix: str, image_attachments: list[bytes], *, client=None):
    if not artifacts.FILES_BUCKET_NAME or not artifacts._valid_prefix(prefix):
        raise ValueError("Artifact storage is not configured")
    target = client or boto3.client("s3")
    catalog_cache: list[dict] | None = None

    def catalog() -> list[dict]:
        nonlocal catalog_cache
        if catalog_cache is None:
            catalog_cache = template_catalog(target)
        return catalog_cache

    @tool
    def search_meme_templates(query: str = "", limit: int = 10) -> str:
        """Find stored meme templates by name, aliases, or intended visual format."""
        if not isinstance(query, str) or len(query.strip()) > MAX_MEME_SEARCH_CHARS:
            raise ValueError(
                f"query must be text up to {MAX_MEME_SEARCH_CHARS} characters"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_MEME_SEARCH_RESULTS
        ):
            raise ValueError(
                f"limit must be between 1 and {MAX_MEME_SEARCH_RESULTS}"
            )
        matches = matching_templates(catalog(), query.strip(), limit)
        if not matches:
            return "No stored meme templates matched that search."
        lines = ["Stored meme templates (pass texts in the listed caption order):"]
        for template in matches:
            order = ", ".join(box["label"] for box in template["textBoxes"])
            description = template["description"] or f'{template["name"]} format.'
            lines.append(
                f'- {template["id"]}: {template["name"]} — {description} '
                f"Caption order: {order}."
            )
        return "\n".join(lines)

    @tool
    def compose_meme(
        filename: str,
        top_text: str = "",
        bottom_text: str = "",
        layout: str = "classic",
        template_id: str = "",
        attachment_number: int = 1,
        texts: list[str] | None = None,
    ) -> str:
        """Caption a stored template with ordered texts, or use top/bottom text on an attached image."""
        safe_name = _safe_png_name(filename)
        top = _clean_caption(top_text, "top_text")
        bottom = _clean_caption(bottom_text, "bottom_text")
        ordered_texts = _clean_captions(texts)
        if not top and not bottom and not any(ordered_texts):
            raise ValueError("Provide texts, top_text, or bottom_text")
        if layout not in MEME_LAYOUTS:
            raise ValueError(
                "layout must be classic, top_only, bottom_only, or caption_bar"
            )
        if layout == "top_only" and not top:
            raise ValueError("top_only requires top_text")
        if layout == "bottom_only" and not bottom:
            raise ValueError("bottom_only requires bottom_text")
        if not isinstance(template_id, str):
            raise TypeError("template_id must be text")
        selected_id = template_id.strip()
        if selected_id:
            if layout != "classic":
                raise ValueError(
                    "Stored templates use their template-specific text boxes; layout is only for attached images"
                )
            if ordered_texts and (top or bottom):
                raise ValueError(
                    "For a stored template, use texts or top_text/bottom_text, not both"
                )
            if not re.fullmatch(r"[0-9]{1,20}", selected_id):
                raise ValueError("template_id is invalid")
            template = next(
                (item for item in catalog() if item["id"] == selected_id), None
            )
            if template is None:
                raise ValueError("template_id is not in the stored meme catalog")
            image = _open_image(
                read_s3_object(target, template["key"], MAX_MEME_TEMPLATE_BYTES)
            )
            captions = ordered_texts or [top, bottom]
            while captions and not captions[-1]:
                captions.pop()
            if len(captions) > len(template["textBoxes"]):
                raise ValueError(
                    f'{template["name"]} accepts at most {len(template["textBoxes"])} captions'
                )
            for index, caption in enumerate(captions):
                _draw_template_caption(image, caption, template["textBoxes"][index])
            source = f'the stored "{template["name"]}" template'
        else:
            if ordered_texts:
                raise ValueError(
                    "texts is only for stored templates; use top_text and bottom_text for attached images"
                )
            if (
                not isinstance(attachment_number, int)
                or isinstance(attachment_number, bool)
                or not 1 <= attachment_number <= len(image_attachments)
            ):
                raise ValueError(
                    "Provide a stored template_id or select an image from the latest user message"
                )
            image = _open_image(image_attachments[attachment_number - 1])
            source = "the supplied image"
            if layout == "caption_bar":
                image = _caption_bar(image, top)
                if bottom:
                    _draw_centered(
                        image,
                        bottom,
                        at_bottom=True,
                        fill="white",
                        stroke_fill="black",
                    )
            else:
                if layout in {"classic", "top_only"}:
                    _draw_centered(
                        image,
                        top,
                        at_bottom=False,
                        fill="white",
                        stroke_fill="black",
                    )
                if layout in {"classic", "bottom_only"}:
                    _draw_centered(
                        image,
                        bottom,
                        at_bottom=True,
                        fill="white",
                        stroke_fill="black",
                    )
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        artifacts._put_artifact(
            target, prefix, safe_name, output.getvalue(), "image/png"
        )
        return f"Saved {safe_name} using {source} and captions."

    return [search_meme_templates, compose_meme]


__all__ = ["image_attachments_from_messages", "meme_tools"]
