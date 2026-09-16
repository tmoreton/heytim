from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest
from PIL import Image

from scripts import sync_meme_templates


class FakeS3:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def put_object(self, **request) -> None:
        self.requests.append(request)


def _image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (640, 480), "green").save(output, format="JPEG")
    return output.getvalue()


def _layout_document() -> bytes:
    settings = json.dumps(
        [
            {
                "x": 600,
                "y": 0,
                "w": 600,
                "h": 600,
                "font_color": "#000000",
                "outline_color": "#ffffff",
                "text_align": "center",
                "vertical_align": "middle",
                "force_caps": False,
            },
            {
                "x": 600,
                "y": 600,
                "w": 600,
                "h": 600,
                "font_color": "#000000",
                "outline_color": "#ffffff",
                "text_align": "center",
                "vertical_align": "middle",
                "force_caps": False,
            },
        ]
    )
    metadata = [
        {
            "id": 181913649,
            "altNames": "drakeposting, drake no yes",
            "default_settings": settings,
        }
    ]
    return (
        f"<script>usermemeID=181913649;memes={json.dumps(metadata)};</script>".encode()
    )


def test_sync_stores_normalized_templates_then_publishes_catalog() -> None:
    storage = FakeS3()
    feed = {
        "success": True,
        "data": {
            "memes": [
                {
                    "id": "181913649",
                    "name": "Drake Hotline Bling",
                    "url": "https://i.imgflip.com/30b1gx.jpg",
                    "width": 1200,
                    "height": 1200,
                    "box_count": 2,
                }
            ]
        },
    }

    def fetch(url: str, maximum_bytes: int) -> bytes:
        if url == sync_meme_templates.IMGFLIP_API_URL:
            assert maximum_bytes == sync_meme_templates.MAX_SOURCE_BYTES
            return json.dumps(feed).encode()
        if url == "https://imgflip.com/memegenerator/181913649":
            assert maximum_bytes == sync_meme_templates.MAX_LAYOUT_PAGE_BYTES
            return _layout_document()
        assert url == "https://i.imgflip.com/30b1gx.jpg"
        assert maximum_bytes == sync_meme_templates.MAX_SOURCE_BYTES
        return _image_bytes()

    count = sync_meme_templates.sync_templates(
        "files",
        s3_client=storage,
        fetch=fetch,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )

    assert count == 1
    assert len(storage.requests) == 2
    image_request, catalog_request = storage.requests
    assert image_request["Key"] == "meme-templates/v1/images/181913649.png"
    assert image_request["ContentType"] == "image/png"
    assert image_request["Body"].startswith(b"\x89PNG\r\n\x1a\n")
    assert "ServerSideEncryption" not in image_request
    assert image_request["Metadata"]["source-url"] == (
        "https://i.imgflip.com/30b1gx.jpg"
    )
    assert catalog_request["Key"] == "meme-templates/v1/catalog.json"
    assert "ServerSideEncryption" not in catalog_request
    catalog = json.loads(catalog_request["Body"])
    assert catalog["schemaVersion"] == 2
    assert catalog["syncedAt"] == "2026-09-10T12:00:00Z"
    assert catalog["templates"][0]["boxCount"] == 2
    assert catalog["templates"][0]["key"] == image_request["Key"]
    assert catalog["templates"][0]["aliases"] == [
        "drakeposting",
        "drake no yes",
    ]
    assert catalog["templates"][0]["textBoxes"][0] == {
        "label": "top right",
        "x": 0.5,
        "y": 0.0,
        "width": 0.5,
        "height": 0.5,
        "horizontalAlign": "center",
        "verticalAlign": "middle",
        "fill": "#000000",
        "stroke": "#FFFFFF",
        "strokeWidth": 0.004,
        "uppercase": False,
        "rotation": 0.0,
    }


def test_sync_rejects_template_urls_outside_imgflip() -> None:
    storage = FakeS3()
    feed = {
        "success": True,
        "data": {
            "memes": [
                {
                    "id": "1",
                    "name": "Unsafe",
                    "url": "https://example.com/template.jpg",
                    "width": 640,
                    "height": 480,
                    "box_count": 2,
                }
            ]
        },
    }

    def fetch(url: str, _maximum_bytes: int) -> bytes:
        if url == sync_meme_templates.IMGFLIP_API_URL:
            return json.dumps(feed).encode()
        if url == "https://imgflip.com/memegenerator/1":
            return b"<html>no layout metadata</html>"
        raise AssertionError("unsafe URL should not be fetched")

    with pytest.raises(ValueError, match="unsupported template URL"):
        sync_meme_templates.sync_templates("files", s3_client=storage, fetch=fetch)
    assert storage.requests == []


def test_missing_layout_metadata_uses_safe_default_text_boxes() -> None:
    boxes = sync_meme_templates._normalized_text_boxes(
        None, box_count=2, width=640, height=480
    )

    assert [box["label"] for box in boxes] == ["top", "bottom"]
    assert all(box["uppercase"] is True for box in boxes)
