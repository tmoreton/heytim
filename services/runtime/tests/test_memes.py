from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from heytim_runtime import artifacts, meme_templates
from heytim_runtime.memes import image_attachments_from_messages, meme_tools


class FakeNoSuchKey(Exception):
    pass


class FakeS3:
    class exceptions:
        NoSuchKey = FakeNoSuchKey

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.objects: dict[str, bytes] = {}

    def put_object(self, **request) -> None:
        self.requests.append(request)

    def get_object(self, *, Bucket, Key) -> dict:
        try:
            body = self.objects[Key]
        except KeyError as exc:
            raise self.exceptions.NoSuchKey from exc
        return {"Body": io.BytesIO(body)}


def _image_bytes(width: int = 640, height: int = 480) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#3984F6").save(output, format="JPEG")
    return output.getvalue()


def _composer(monkeypatch, images: list[bytes]):
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    storage = FakeS3()
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    tools = {
        item.tool_name: item for item in meme_tools(prefix, images, client=storage)
    }
    return tools, storage


def _stored_template(storage: FakeS3) -> None:
    key = f"{meme_templates.MEME_TEMPLATE_PREFIX}/images/181913649.png"
    storage.objects[key] = _image_bytes(800, 800)
    storage.objects[meme_templates.MEME_CATALOG_KEY] = json.dumps(
        {
            "schemaVersion": 2,
            "templates": [
                {
                    "id": "181913649",
                    "name": "Drake Hotline Bling",
                    "key": key,
                    "boxCount": 2,
                    "aliases": ["drakeposting", "drake no yes"],
                    "description": "Use this format to contrast a rejected and preferred choice.",
                    "textBoxes": [
                        {
                            "label": "top right",
                            "x": 0.52,
                            "y": 0.02,
                            "width": 0.46,
                            "height": 0.45,
                            "horizontalAlign": "center",
                            "verticalAlign": "middle",
                            "fill": "#000000",
                            "stroke": "#FFFFFF",
                            "strokeWidth": 0.004,
                            "uppercase": False,
                            "rotation": 0,
                        },
                        {
                            "label": "bottom right",
                            "x": 0.52,
                            "y": 0.52,
                            "width": 0.46,
                            "height": 0.45,
                            "horizontalAlign": "center",
                            "verticalAlign": "middle",
                            "fill": "#000000",
                            "stroke": "#FFFFFF",
                            "strokeWidth": 0.004,
                            "uppercase": False,
                            "rotation": 0,
                        },
                    ],
                }
            ],
        }
    ).encode()


def test_latest_message_images_are_available_to_the_compositor() -> None:
    first = _image_bytes()
    second = _image_bytes(320, 240)
    messages = [
        {"role": "assistant", "content": [{"text": "Earlier"}]},
        {
            "role": "user",
            "content": [
                {"text": "Caption these"},
                {"image": {"source": {"bytes": first}}},
                {"image": {"source": {"bytes": second}}},
            ],
        },
    ]
    assert image_attachments_from_messages(messages) == [first, second]


def test_composer_overlays_text_and_uploads_a_png(monkeypatch) -> None:
    tools, storage = _composer(monkeypatch, [_image_bytes()])

    result = tools["compose_meme"](
        "deployment meme.png",
        top_text="WHEN THE TESTS PASS",
        bottom_text="ON THE FIRST TRY",
    )

    assert result == (
        "Saved deployment meme.png using the supplied image and captions."
    )
    request = storage.requests[0]
    assert request["ContentType"] == "image/png"
    output = Image.open(io.BytesIO(request["Body"]))
    assert output.format == "PNG"
    assert output.size == (640, 480)


def test_caption_bar_adds_space_without_cropping_the_template(monkeypatch) -> None:
    tools, storage = _composer(monkeypatch, [_image_bytes(600, 400)])
    tools["compose_meme"](
        "meeting.png", top_text="THIS COULD HAVE BEEN AN EMAIL", layout="caption_bar"
    )

    output = Image.open(io.BytesIO(storage.requests[0]["Body"]))
    assert output.width == 600
    assert output.height > 400


def test_composer_requires_a_valid_latest_message_image(monkeypatch) -> None:
    tools, _ = _composer(monkeypatch, [])
    with pytest.raises(ValueError, match="stored template_id"):
        tools["compose_meme"]("missing.png", top_text="NO TEMPLATE")


def test_missing_stored_library_returns_an_actionable_error(monkeypatch) -> None:
    tools, _ = _composer(monkeypatch, [])

    with pytest.raises(ValueError, match="temporarily unavailable"):
        tools["search_meme_templates"]("")


def test_composer_rejects_invalid_layout_and_oversized_copy(monkeypatch) -> None:
    tools, _ = _composer(monkeypatch, [_image_bytes()])
    compose = tools["compose_meme"]
    with pytest.raises(ValueError, match="layout must be"):
        compose("bad.png", top_text="Hello", layout="unknown")
    with pytest.raises(ValueError, match="at most 300"):
        compose("long.png", top_text="x" * 301)
    with pytest.raises(ValueError, match="top_only requires"):
        compose("empty-top.png", bottom_text="Wrong field", layout="top_only")


def test_stored_templates_can_be_searched_and_captioned(monkeypatch) -> None:
    tools, storage = _composer(monkeypatch, [])
    _stored_template(storage)

    result = tools["search_meme_templates"]("drake no yes")
    assert "181913649: Drake Hotline Bling" in result
    assert "Caption order: top right, bottom right" in result

    result = tools["compose_meme"](
        "choice.png",
        template_id="181913649",
        texts=["MANUAL IMAGE GENERATION", "REUSABLE TEMPLATES"],
    )

    assert result == (
        'Saved choice.png using the stored "Drake Hotline Bling" template and captions.'
    )
    output = Image.open(io.BytesIO(storage.requests[0]["Body"]))
    assert output.format == "PNG"
    assert output.size == (800, 800)
    assert output.getpixel((100, 100)) == (57, 132, 247)


def test_stored_template_rejects_more_captions_than_it_has_boxes(monkeypatch) -> None:
    tools, storage = _composer(monkeypatch, [])
    _stored_template(storage)

    with pytest.raises(ValueError, match="accepts at most 2 captions"):
        tools["compose_meme"](
            "too-many.png",
            template_id="181913649",
            texts=["one", "two", "three"],
        )


def test_catalog_cannot_redirect_reads_outside_the_template_prefix(monkeypatch) -> None:
    tools, storage = _composer(monkeypatch, [])
    storage.objects[meme_templates.MEME_CATALOG_KEY] = json.dumps(
        {
            "schemaVersion": 1,
            "templates": [
                {
                    "id": "181913649",
                    "name": "Unsafe",
                    "key": "users/another-user/private.png",
                    "boxCount": 2,
                }
            ],
        }
    ).encode()

    with pytest.raises(ValueError, match="invalid entry"):
        tools["compose_meme"]("unsafe.png", top_text="NO", template_id="181913649")
