from __future__ import annotations

import argparse
import io
import json
import math
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
from PIL import Image, ImageOps, UnidentifiedImageError

IMGFLIP_API_URL = "https://api.imgflip.com/get_memes?type=image"
IMGFLIP_GENERATOR_URL = "https://imgflip.com/memegenerator/{template_id}"
IMGFLIP_TERMS_URL = "https://imgflip.com/terms"
DEFAULT_PREFIX = "meme-templates/v1"
MAX_SOURCE_BYTES = 8_000_000
MAX_LAYOUT_PAGE_BYTES = 500_000
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 1_600
MAX_TEMPLATES = 100
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")


def _read_url(url: str, maximum_bytes: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "api.imgflip.com",
        "i.imgflip.com",
        "imgflip.com",
    }:
        raise ValueError("Imgflip returned an unsupported source URL")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FroggyBot meme-template sync/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in {
            "api.imgflip.com",
            "i.imgflip.com",
            "imgflip.com",
        }:
            raise ValueError("Imgflip redirected to an unsupported source URL")
        body = response.read(maximum_bytes + 1)
    if not body or len(body) > maximum_bytes:
        raise ValueError("Imgflip returned an empty or oversized response")
    return body


def _feed(fetch: Callable[[str, int], bytes]) -> list[dict[str, Any]]:
    try:
        payload = json.loads(fetch(IMGFLIP_API_URL, MAX_SOURCE_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Imgflip returned an invalid template feed") from exc
    if not isinstance(payload, dict):
        raise TypeError("Imgflip returned an invalid template feed")
    data = payload.get("data")
    memes = data.get("memes") if isinstance(data, dict) else None
    if payload.get("success") is not True or not isinstance(memes, list):
        raise ValueError("Imgflip did not return a successful template feed")
    return memes


def _template(raw: dict[str, Any]) -> dict[str, Any]:
    template_id = raw.get("id")
    name = raw.get("name")
    source_url = raw.get("url")
    width = raw.get("width")
    height = raw.get("height")
    box_count = raw.get("box_count")
    if (
        not isinstance(template_id, str)
        or not re.fullmatch(r"[0-9]{1,20}", template_id)
        or not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 120
        or not isinstance(source_url, str)
        or not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width < 64
        or height < 64
        or width * height > MAX_IMAGE_PIXELS
        or not isinstance(box_count, int)
        or isinstance(box_count, bool)
        or not 1 <= box_count <= 20
    ):
        raise ValueError("Imgflip returned an invalid template entry")
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname != "i.imgflip.com":
        raise ValueError("Imgflip returned an unsupported template URL")
    return {
        "id": template_id,
        "name": name.strip(),
        "sourceUrl": source_url,
        "width": width,
        "height": height,
        "boxCount": box_count,
    }


def _layout_feed(
    fetch: Callable[[str, int], bytes], template_id: str
) -> dict[str, dict[str, Any]]:
    url = IMGFLIP_GENERATOR_URL.format(template_id=template_id)
    try:
        document = fetch(url, MAX_LAYOUT_PAGE_BYTES).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Imgflip returned invalid template layout metadata") from exc
    marker = re.search(r"usermemeID=[0-9]+;memes=", document)
    if marker is None:
        raise ValueError("Imgflip did not publish template layout metadata")
    try:
        payload, _ = json.JSONDecoder().raw_decode(document[marker.end() :])
    except json.JSONDecodeError as exc:
        raise ValueError("Imgflip returned invalid template layout metadata") from exc
    values = list(payload.values()) if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise TypeError("Imgflip returned invalid template layout metadata")
    layouts: dict[str, dict[str, Any]] = {}
    for raw in values:
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        if isinstance(raw_id, int) and not isinstance(raw_id, bool):
            layouts[str(raw_id)] = raw
    return layouts


def _optional_layout_feed(
    fetch: Callable[[str, int], bytes], template_id: str
) -> dict[str, dict[str, Any]]:
    try:
        return _layout_feed(fetch, template_id)
    except (OSError, TypeError, UnicodeError, ValueError):
        return {}


def _position_label(box: dict[str, float]) -> str:
    center_x = box["x"] + (box["width"] / 2)
    center_y = box["y"] + (box["height"] / 2)
    horizontal = (
        "left" if center_x < 0.38 else "right" if center_x > 0.62 else "center"
    )
    vertical = (
        "top" if center_y < 0.38 else "bottom" if center_y > 0.62 else "middle"
    )
    return vertical if horizontal == "center" else f"{vertical} {horizontal}"


def _generic_text_boxes(
    box_count: int, width: int, height: int
) -> list[dict[str, Any]]:
    base = {
        "horizontalAlign": "center",
        "verticalAlign": "middle",
        "fill": "#FFFFFF",
        "stroke": "#000000",
        "strokeWidth": 0.004,
        "uppercase": True,
        "rotation": 0.0,
    }
    if box_count == 1:
        coordinates = [(0.04, 0.03, 0.92, 0.28)]
    elif box_count == 2:
        coordinates = [(0.04, 0.03, 0.92, 0.28), (0.04, 0.69, 0.92, 0.28)]
    elif box_count == 4 and width >= height * 0.8:
        coordinates = [
            (0.03, 0.03, 0.45, 0.45),
            (0.52, 0.03, 0.45, 0.45),
            (0.03, 0.52, 0.45, 0.45),
            (0.52, 0.52, 0.45, 0.45),
        ]
    else:
        gap = 0.02
        box_height = (0.94 - (gap * (box_count - 1))) / box_count
        coordinates = [
            (0.04, 0.03 + index * (box_height + gap), 0.92, box_height)
            for index in range(box_count)
        ]
    boxes = []
    for x, y, box_width, box_height in coordinates:
        box = {
            **base,
            "x": round(x, 6),
            "y": round(y, 6),
            "width": round(box_width, 6),
            "height": round(box_height, 6),
        }
        boxes.append({"label": _position_label(box), **box})
    return boxes


def _color(value: Any, fallback: str) -> tuple[str, bool]:
    if not isinstance(value, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value
    ):
        return fallback, True
    transparent = len(value) == 9 and value[-2:].lower() == "00"
    return value[:7].upper(), not transparent


def _normalized_text_boxes(
    metadata: dict[str, Any] | None,
    *,
    box_count: int,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    settings = metadata.get("default_settings") if isinstance(metadata, dict) else None
    if not isinstance(settings, str) or not settings:
        return _generic_text_boxes(box_count, width, height)
    try:
        raw_boxes = json.loads(settings)
    except json.JSONDecodeError:
        return _generic_text_boxes(box_count, width, height)
    if not isinstance(raw_boxes, list) or len(raw_boxes) != box_count:
        return _generic_text_boxes(box_count, width, height)

    boxes = []
    for raw in raw_boxes:
        if not isinstance(raw, dict):
            return _generic_text_boxes(box_count, width, height)
        coordinates = [raw.get(field) for field in ("x", "y", "w", "h")]
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in coordinates
        ):
            return _generic_text_boxes(box_count, width, height)
        x, y, box_width, box_height = coordinates
        if box_width <= 0 or box_height <= 0:
            return _generic_text_boxes(box_count, width, height)
        normalized = {
            "x": round(x / width, 6),
            "y": round(y / height, 6),
            "width": round(box_width / width, 6),
            "height": round(box_height / height, 6),
        }
        if (
            normalized["x"] < -0.5
            or normalized["y"] < -0.5
            or normalized["x"] > 1.5
            or normalized["y"] > 1.5
            or normalized["width"] > 2
            or normalized["height"] > 2
        ):
            return _generic_text_boxes(box_count, width, height)
        fill, _ = _color(raw.get("font_color"), "#FFFFFF")
        stroke, stroke_visible = _color(raw.get("outline_color"), "#000000")
        raw_stroke = raw.get("outline_width")
        stroke_width = (
            float(raw_stroke) / width
            if isinstance(raw_stroke, (int, float))
            and not isinstance(raw_stroke, bool)
            and raw_stroke >= 0
            else 0.004
        )
        raw_rotation = raw.get("rotation") or 0
        if not isinstance(raw_rotation, (int, float)) or isinstance(
            raw_rotation, bool
        ):
            raw_rotation = 0
        rotation = ((float(raw_rotation) + 180) % 360) - 180
        horizontal = raw.get("text_align")
        vertical = raw.get("vertical_align")
        font_max_size = raw.get("font_max_size")
        box = {
            "label": _position_label(normalized),
            **normalized,
            "horizontalAlign": horizontal
            if horizontal in {"left", "center", "right"}
            else "center",
            "verticalAlign": vertical
            if vertical in {"top", "middle", "bottom"}
            else "middle",
            "fill": fill,
            "stroke": stroke,
            "strokeWidth": round(stroke_width if stroke_visible else 0.0, 6),
            "uppercase": raw.get("force_caps") is True,
            "rotation": round(rotation, 3),
        }
        if (
            isinstance(font_max_size, (int, float))
            and not isinstance(font_max_size, bool)
            and 4 <= font_max_size <= width
        ):
            box["fontMaxSize"] = round(float(font_max_size) / width, 6)
        boxes.append(box)

    labels: dict[str, int] = {}
    for box in boxes:
        labels[box["label"]] = labels.get(box["label"], 0) + 1
    seen: dict[str, int] = {}
    for box in boxes:
        label = box["label"]
        if labels[label] > 1:
            seen[label] = seen.get(label, 0) + 1
            box["label"] = f"{label} {seen[label]}"
    return boxes


def _aliases(metadata: dict[str, Any] | None) -> list[str]:
    raw = metadata.get("altNames") if isinstance(metadata, dict) else None
    if not isinstance(raw, str):
        return []
    aliases = []
    for value in raw.split(","):
        clean = " ".join(value.split()).strip()
        if clean and clean.casefold() not in {item.casefold() for item in aliases}:
            aliases.append(clean[:80])
        if len(aliases) == 12:
            break
    return aliases


def _description(name: str, aliases: list[str]) -> str:
    if aliases:
        concepts = ", ".join(aliases[:5])
        return f"Use this {name} format for ideas such as {concepts}."[:240]
    return f"Use this classic {name} reaction format."[:240]


def _png(body: bytes) -> bytes:
    try:
        source = Image.open(io.BytesIO(body))
        width, height = source.size
        if width < 64 or height < 64 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("The Imgflip template dimensions are unsupported")
        source.seek(0)
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        result = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Imgflip returned an unsupported template image") from exc
    if not result or len(result) > MAX_SOURCE_BYTES:
        raise ValueError("The normalized meme template is empty or too large")
    return result


def sync_templates(
    bucket: str,
    prefix: str = DEFAULT_PREFIX,
    limit: int = MAX_TEMPLATES,
    *,
    s3_client=None,
    fetch: Callable[[str, int], bytes] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    clean_prefix = prefix.strip("/")
    if not PREFIX_PATTERN.fullmatch(clean_prefix):
        raise ValueError("prefix is invalid")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    target = s3_client or boto3.client("s3")
    retrieve = fetch or _read_url
    timestamp = (now or (lambda: datetime.now(UTC)))().astimezone(UTC)
    templates = []
    seen = set()
    feed = _feed(retrieve)
    if not feed:
        raise ValueError("Imgflip returned no usable templates")
    first = feed[0]
    if not isinstance(first, dict) or not isinstance(first.get("id"), str):
        raise TypeError("Imgflip returned an invalid template entry")
    layouts = _optional_layout_feed(retrieve, first["id"])
    attempted_layout_pages = {first["id"]}
    for raw in feed:
        if len(templates) >= limit:
            break
        if not isinstance(raw, dict):
            raise TypeError("Imgflip returned an invalid template entry")
        template = _template(raw)
        if template["id"] in seen:
            continue
        seen.add(template["id"])
        metadata = layouts.get(template["id"])
        if metadata is None and template["id"] not in attempted_layout_pages:
            attempted_layout_pages.add(template["id"])
            layouts.update(_optional_layout_feed(retrieve, template["id"]))
            metadata = layouts.get(template["id"])
        aliases = _aliases(metadata)
        text_boxes = _normalized_text_boxes(
            metadata,
            box_count=template["boxCount"],
            width=template["width"],
            height=template["height"],
        )
        key = f'{clean_prefix}/images/{template["id"]}.png'
        image = _png(retrieve(template["sourceUrl"], MAX_SOURCE_BYTES))
        target.put_object(
            Bucket=bucket,
            Key=key,
            Body=image,
            ContentType="image/png",
            CacheControl="private, max-age=86400",
            Metadata={
                "source": "imgflip",
                "source-url": template["sourceUrl"],
                "template-id": template["id"],
                "template-name": urllib.parse.quote(template["name"], safe=""),
            },
            ServerSideEncryption="AES256",
        )
        templates.append(
            {
                **template,
                "aliases": aliases,
                "description": _description(template["name"], aliases),
                "textBoxes": text_boxes,
                "key": key,
            }
        )

    if not templates:
        raise ValueError("Imgflip returned no usable templates")
    catalog = {
        "schemaVersion": 2,
        "source": IMGFLIP_API_URL,
        "layoutSource": IMGFLIP_GENERATOR_URL.format(template_id="{template_id}"),
        "terms": IMGFLIP_TERMS_URL,
        "syncedAt": timestamp.isoformat().replace("+00:00", "Z"),
        "templates": templates,
    }
    target.put_object(
        Bucket=bucket,
        Key=f"{clean_prefix}/catalog.json",
        Body=json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        ),
        ContentType="application/json",
        CacheControl="private, max-age=300",
        Metadata={"source": "imgflip"},
        ServerSideEncryption="AES256",
    )
    return len(templates)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy Imgflip's official top image-template feed into S3."
    )
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--limit", type=int, default=MAX_TEMPLATES)
    args = parser.parse_args()
    count = sync_templates(args.bucket, args.prefix, args.limit)
    print(f"Stored {count} Imgflip meme templates in s3://{args.bucket}/{args.prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
