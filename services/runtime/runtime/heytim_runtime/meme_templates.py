from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from . import artifacts

MAX_MEME_CATALOG_BYTES = 512_000
MAX_MEME_TEMPLATE_BYTES = 8_000_000
MAX_MEME_SEARCH_CHARS = 100
MAX_MEME_SEARCH_RESULTS = 20
MEME_TEMPLATE_PREFIX = os.environ.get(
    "HEYTIM_MEME_TEMPLATE_PREFIX", "meme-templates/v1"
).strip("/")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", MEME_TEMPLATE_PREFIX):
    raise ValueError("HEYTIM_MEME_TEMPLATE_PREFIX is invalid")
MEME_CATALOG_KEY = f"{MEME_TEMPLATE_PREFIX}/catalog.json"


def read_s3_object(target, key: str, maximum_bytes: int) -> bytes:
    try:
        response = target.get_object(Bucket=artifacts.FILES_BUCKET_NAME, Key=key)
    except target.exceptions.NoSuchKey as exc:
        raise ValueError(
            "Stored meme templates are temporarily unavailable. "
            "Try again later or attach an image to caption."
        ) from exc
    stream = response["Body"]
    try:
        body = stream.read(maximum_bytes + 1)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    if not isinstance(body, bytes) or not body:
        raise ValueError("The meme template library contains an empty object")
    if len(body) > maximum_bytes:
        raise ValueError("The meme template library object is too large")
    return body


def template_catalog(target) -> list[dict]:
    body = read_s3_object(target, MEME_CATALOG_KEY, MAX_MEME_CATALOG_BYTES)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The meme template catalog is invalid") from exc
    schema_version = payload.get("schemaVersion") if isinstance(payload, dict) else None
    raw_templates = payload.get("templates") if isinstance(payload, dict) else None
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError("The meme template catalog is empty")
    if schema_version not in {1, 2}:
        raise ValueError("The meme template catalog version is unsupported")

    templates = []
    seen = set()
    for raw in raw_templates:
        template_id = raw.get("id") if isinstance(raw, dict) else None
        name = raw.get("name") if isinstance(raw, dict) else None
        key = raw.get("key") if isinstance(raw, dict) else None
        box_count = raw.get("boxCount") if isinstance(raw, dict) else None
        aliases = raw.get("aliases", []) if isinstance(raw, dict) else None
        description = raw.get("description", "") if isinstance(raw, dict) else None
        raw_text_boxes = raw.get("textBoxes") if isinstance(raw, dict) else None
        expected_key = f"{MEME_TEMPLATE_PREFIX}/images/{template_id}.png"
        if (
            not isinstance(template_id, str)
            or not re.fullmatch(r"[0-9]{1,20}", template_id)
            or template_id in seen
            or not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 120
            or key != expected_key
            or not isinstance(box_count, int)
            or isinstance(box_count, bool)
            or not 1 <= box_count <= 20
            or not isinstance(aliases, list)
            or len(aliases) > 12
            or any(
                not isinstance(alias, str) or not 1 <= len(alias.strip()) <= 80
                for alias in aliases
            )
            or not isinstance(description, str)
            or len(description.strip()) > 240
        ):
            raise ValueError("The meme template catalog contains an invalid entry")
        if schema_version == 2:
            if not isinstance(raw_text_boxes, list) or len(raw_text_boxes) != box_count:
                raise ValueError(
                    "The meme template catalog contains invalid text boxes"
                )
            text_boxes = [
                catalog_text_box(box, index) for index, box in enumerate(raw_text_boxes)
            ]
        else:
            text_boxes = legacy_text_boxes(box_count)
        seen.add(template_id)
        templates.append(
            {
                "id": template_id,
                "name": name.strip(),
                "key": key,
                "boxCount": box_count,
                "aliases": [alias.strip() for alias in aliases],
                "description": description.strip(),
                "textBoxes": text_boxes,
            }
        )
    return templates


def legacy_text_boxes(box_count: int) -> list[dict]:
    if box_count == 1:
        coordinates = [(0.04, 0.03, 0.92, 0.28)]
    elif box_count == 2:
        coordinates = [(0.04, 0.03, 0.92, 0.28), (0.04, 0.69, 0.92, 0.28)]
    else:
        gap = 0.02
        box_height = (0.94 - gap * (box_count - 1)) / box_count
        coordinates = [
            (0.04, 0.03 + index * (box_height + gap), 0.92, box_height)
            for index in range(box_count)
        ]
    return [
        {
            "label": f"caption {index + 1}",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "horizontalAlign": "center",
            "verticalAlign": "middle",
            "fill": "#FFFFFF",
            "stroke": "#000000",
            "strokeWidth": 0.004,
            "uppercase": True,
            "rotation": 0.0,
        }
        for index, (x, y, width, height) in enumerate(coordinates)
    ]


def catalog_text_box(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise TypeError("The meme template catalog contains invalid text boxes")
    label = raw.get("label")
    coordinates = [raw.get(field) for field in ("x", "y", "width", "height")]
    horizontal = raw.get("horizontalAlign")
    vertical = raw.get("verticalAlign")
    fill = raw.get("fill")
    stroke = raw.get("stroke")
    stroke_width = raw.get("strokeWidth")
    uppercase = raw.get("uppercase")
    rotation = raw.get("rotation")
    font_max_size = raw.get("fontMaxSize")
    if (
        not isinstance(label, str)
        or not 1 <= len(label.strip()) <= 40
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in coordinates
        )
        or not -0.5 <= coordinates[0] <= 1.5
        or not -0.5 <= coordinates[1] <= 1.5
        or not 0 < coordinates[2] <= 2
        or not 0 < coordinates[3] <= 2
        or horizontal not in {"left", "center", "right"}
        or vertical not in {"top", "middle", "bottom"}
        or not isinstance(fill, str)
        or re.fullmatch(r"#[0-9A-Fa-f]{6}", fill) is None
        or not isinstance(stroke, str)
        or re.fullmatch(r"#[0-9A-Fa-f]{6}", stroke) is None
        or not isinstance(stroke_width, (int, float))
        or isinstance(stroke_width, bool)
        or not 0 <= stroke_width <= 0.05
        or not isinstance(uppercase, bool)
        or not isinstance(rotation, (int, float))
        or isinstance(rotation, bool)
        or not math.isfinite(rotation)
        or not -180 <= rotation <= 180
        or (
            font_max_size is not None
            and (
                not isinstance(font_max_size, (int, float))
                or isinstance(font_max_size, bool)
                or not 0.003 <= font_max_size <= 1
            )
        )
    ):
        raise ValueError(
            f"The meme template catalog contains an invalid text box at {index + 1}"
        )
    result = {
        "label": label.strip(),
        "x": float(coordinates[0]),
        "y": float(coordinates[1]),
        "width": float(coordinates[2]),
        "height": float(coordinates[3]),
        "horizontalAlign": horizontal,
        "verticalAlign": vertical,
        "fill": fill.upper(),
        "stroke": stroke.upper(),
        "strokeWidth": float(stroke_width),
        "uppercase": uppercase,
        "rotation": float(rotation),
    }
    if font_max_size is not None:
        result["fontMaxSize"] = float(font_max_size)
    return result


def matching_templates(templates: list[dict], query: str, limit: int) -> list[dict]:
    if not query:
        return templates[:limit]
    folded = query.casefold()
    words = set(folded.split())

    def score(template: dict) -> tuple[int, int]:
        name = template["name"].casefold()
        aliases = [alias.casefold() for alias in template["aliases"]]
        search_text = " ".join([name, template["description"].casefold(), *aliases])
        name_words = set(search_text.split())
        if name == folded:
            return 4, 0
        if folded in aliases:
            return 4, len(name)
        if name.startswith(folded):
            return 3, len(name)
        if folded in search_text:
            return 2, len(name)
        overlap = len(words & name_words)
        return (1, -overlap) if overlap else (0, len(name))

    matches = [template for template in templates if score(template)[0] > 0]
    return sorted(
        matches, key=lambda template: (-score(template)[0], score(template)[1])
    )[:limit]


__all__ = [
    "MAX_MEME_SEARCH_CHARS",
    "MAX_MEME_SEARCH_RESULTS",
    "MAX_MEME_TEMPLATE_BYTES",
    "MEME_CATALOG_KEY",
    "MEME_TEMPLATE_PREFIX",
    "matching_templates",
    "read_s3_object",
    "template_catalog",
]
