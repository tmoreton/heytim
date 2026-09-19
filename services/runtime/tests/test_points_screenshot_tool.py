from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from heytim_runtime import agentcore_adapters, points_screenshots


def test_points_screenshot_captures_one_verified_official_price_card(
    monkeypatch,
) -> None:
    prefix = (
        f"users/{'a' * 64}/bots/jopbot/artifacts/12345678-1234-1234-1234-123456789012"
    )
    requests = []

    class Storage:
        def put_object(self, **request):
            requests.append(request)

    class Locator:
        async def count(self):
            return 1

        async def inner_text(self):
            return "New York to Paris From 42,000 SkyMiles + $86"

        async def is_visible(self):
            return True

        async def scroll_into_view_if_needed(self, **kwargs):
            assert kwargs == {"timeout": 10_000}

        async def bounding_box(self):
            return {"x": 20, "y": 30, "width": 240, "height": 180}

    class Page:
        url = "https://www.delta.com/us/en/flight-deals/skymiles-award-deals"

        def __init__(self):
            self.viewport_size = {"width": 400, "height": 300}

        def locator(self, selector):
            assert selector == "[data-testid='award-card']"
            return Locator()

        async def screenshot(self, **kwargs):
            assert kwargs == {
                "type": "png",
                "animations": "disabled",
                "scale": "css",
            }
            output = io.BytesIO()
            image = Image.new("RGB", (400, 300), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 30, 260, 210), outline="black", width=2)
            draw.text((40, 80), "42,000 SkyMiles", fill="black")
            image.save(output, format="PNG")
            return output.getvalue()

    browser = object.__new__(agentcore_adapters.PersistentAgentCoreBrowser)
    browser.artifact_prefix = prefix
    browser.storage_client = Storage()
    browser.managed_session = None
    browser._sessions = {
        "award-search": SimpleNamespace(get_active_page=lambda: Page())
    }
    monkeypatch.setattr(points_screenshots.artifacts, "FILES_BUCKET_NAME", "files")

    result = asyncio.run(
        browser._async_capture_points_screenshot(
            "award-search",
            "[data-testid='award-card']",
            "Delta JFK-CDG.png",
            "42,000 SkyMiles",
            "Delta JFK to CDG award fare",
        )
    )
    detail = result["content"][0]["json"]

    assert result["status"] == "success"
    assert detail["pointsValue"] == "42,000 SkyMiles"
    assert detail["sourceUrl"] == Page.url
    assert detail["artifactId"] in detail["instruction"]
    assert requests[0]["Key"].startswith(f"{prefix}/")
    assert requests[0]["ContentType"] == "image/png"
    assert requests[0]["Metadata"]["source-url"] == Page.url


@pytest.mark.parametrize(
    ("url", "text", "expected"),
    [
        (
            "https://thepointsguy.com/deals/example",
            "42,000 SkyMiles",
            "official airline and hotel domains",
        ),
        (
            "https://www.delta.com/deals",
            "52,000 SkyMiles",
            "not visible",
        ),
        (
            "https://www.delta.com/deals",
            "42,000 SkyMiles Member number: ABC12345",
            "private account data",
        ),
    ],
)
def test_points_screenshot_rejects_publishers_mismatches_and_private_data(
    monkeypatch, url, text, expected
) -> None:
    class Locator:
        async def count(self):
            return 1

        async def inner_text(self):
            return text

        async def screenshot(self, **_kwargs):
            raise AssertionError("unsafe capture reached screenshot")

    page = SimpleNamespace(url=url, locator=lambda _selector: Locator())
    browser = object.__new__(agentcore_adapters.PersistentAgentCoreBrowser)
    browser.artifact_prefix = (
        f"users/{'a' * 64}/bots/jopbot/artifacts/12345678-1234-1234-1234-123456789012"
    )
    browser.storage_client = SimpleNamespace(put_object=lambda **_: None)
    browser.managed_session = None
    browser._sessions = {"award-search": SimpleNamespace(get_active_page=lambda: page)}
    monkeypatch.setattr(points_screenshots.artifacts, "FILES_BUCKET_NAME", "files")

    with pytest.raises(ValueError, match=expected):
        asyncio.run(
            browser._async_capture_points_screenshot(
                "award-search",
                "#award-card",
                "Deal.png",
                "42,000 SkyMiles",
                "Delta award fare",
            )
        )
