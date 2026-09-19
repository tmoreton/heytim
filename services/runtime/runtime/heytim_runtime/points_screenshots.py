from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from . import artifacts

DEFAULT_POINTS_SCREENSHOT_DOMAINS = frozenset(
    {
        "aa.com",
        "aeroplan.com",
        "aircanada.com",
        "airfrance.com",
        "alaskaair.com",
        "all.accor.com",
        "britishairways.com",
        "choicehotels.com",
        "delta.com",
        "emirates.com",
        "flyingblue.com",
        "hilton.com",
        "hyatt.com",
        "ihg.com",
        "jetblue.com",
        "klm.com",
        "marriott.com",
        "qantas.com",
        "qatarairways.com",
        "singaporeair.com",
        "southwest.com",
        "united.com",
        "virginatlantic.com",
        "wyndhamhotels.com",
    }
)
POINTS_SCREENSHOT_DOMAINS = frozenset(
    domain.strip().lower().rstrip(".")
    for domain in os.environ.get(
        "HEYTIM_POINTS_SCREENSHOT_DOMAINS",
        ",".join(sorted(DEFAULT_POINTS_SCREENSHOT_DOMAINS)),
    ).split(",")
    if domain.strip()
)
PRIVATE_CAPTURE_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(
        r"\b(?:member|account|loyalty|frequent[ -]?flyer)\s*(?:number|no\.?|id)\s*[:#]?\s*[A-Z0-9-]{5,}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:confirmation|booking|reservation)\s*(?:code|number|no\.?|id)\s*[:#]?\s*[A-Z0-9-]{5,}\b",
        re.IGNORECASE,
    ),
)


async def capture_points_screenshot(
    *,
    page: Any,
    artifact_prefix: str,
    storage_client: Any,
    selector: str,
    filename: str,
    points_value: str,
    offer_description: str,
) -> dict[str, Any]:
    if (
        not isinstance(selector, str)
        or not selector.strip()
        or len(selector) > 500
        or selector.strip().lower() in {"html", "body", "*"}
    ):
        raise ValueError("selector must identify one points-price card")
    if not isinstance(points_value, str):
        raise TypeError("pointsValue must be text")
    clean_points = " ".join(points_value.split())
    if (
        not clean_points
        or len(clean_points) > 80
        or not any(character.isdigit() for character in clean_points)
    ):
        raise ValueError("pointsValue must contain the visible points price")
    if not isinstance(offer_description, str):
        raise TypeError("offerDescription must be text")
    clean_description = " ".join(offer_description.split())
    if not clean_description or len(clean_description) > 240:
        raise ValueError("offerDescription must be between 1 and 240 characters")

    source_url = page.url
    parsed = urlsplit(source_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in POINTS_SCREENSHOT_DOMAINS
        )
    ):
        raise ValueError(
            "Points screenshots are limited to approved official airline and hotel domains"
        )

    locator = page.locator(selector)
    if await locator.count() != 1:
        raise ValueError("selector must match exactly one points-price card")
    visible_text = " ".join((await locator.inner_text()).split())
    normalized_text = re.sub(r"[\s,]", "", visible_text).casefold()
    normalized_points = re.sub(r"[\s,]", "", clean_points).casefold()
    if normalized_points not in normalized_text:
        raise ValueError("The stated points value is not visible in the selected card")
    if any(pattern.search(visible_text) for pattern in PRIVATE_CAPTURE_PATTERNS):
        raise ValueError("The selected card appears to contain private account data")

    if not await locator.is_visible():
        raise ValueError("The selected points-price card is not visible")
    await locator.scroll_into_view_if_needed(timeout=10_000)
    bounding_box = await locator.bounding_box()
    if not bounding_box:
        raise ValueError("The selected points-price card is not visible")
    viewport = page.viewport_size
    if (
        not isinstance(viewport, dict)
        or not isinstance(viewport.get("width"), int)
        or not isinstance(viewport.get("height"), int)
    ):
        raise TypeError("Browser viewport dimensions are unavailable")
    x = bounding_box.get("x")
    y = bounding_box.get("y")
    width = bounding_box.get("width")
    height = bounding_box.get("height")
    if (
        any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (x, y, width, height)
        )
        or x < 0
        or y < 0
        or x + width > viewport["width"]
        or y + height > viewport["height"]
    ):
        raise ValueError("The selected points-price card is outside the viewport")
    viewport_png = await page.screenshot(
        type="png", animations="disabled", scale="css"
    )
    image = artifacts.crop_points_screenshot(viewport_png, bounding_box)
    captured_at = datetime.now(UTC).isoformat(timespec="seconds")
    stored = artifacts.put_png_artifact(
        artifact_prefix,
        filename,
        image,
        client=storage_client,
        metadata={
            "source-url": source_url,
            "captured-at": captured_at,
            "points-value": clean_points,
            "offer-description": clean_description,
        },
    )
    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "artifactId": stored["artifactId"],
                    "filename": stored["filename"],
                    "sourceUrl": source_url,
                    "capturedAt": captured_at,
                    "pointsValue": clean_points,
                    "offerDescription": clean_description,
                    "instruction": (
                        f'Embed with <img src="cid:{stored["artifactId"]}" alt="..."> '
                        "in a Gmail HTML draft and include the source URL and capture time."
                    ),
                }
            }
        ],
    }
