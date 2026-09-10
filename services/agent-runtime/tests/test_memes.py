from __future__ import annotations

import io

import pytest
from PIL import Image

from frogbot_runtime import artifacts
from frogbot_runtime.memes import image_attachments_from_messages, meme_tool


class FakeS3:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def put_object(self, **request) -> None:
        self.requests.append(request)


def _image_bytes(width: int = 640, height: int = 480) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#3984F6").save(output, format="JPEG")
    return output.getvalue()


def _composer(monkeypatch, images: list[bytes]):
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    storage = FakeS3()
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    return meme_tool(prefix, images, client=storage), storage


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
    compose, storage = _composer(monkeypatch, [_image_bytes()])

    result = compose(
        "deployment meme.png",
        top_text="WHEN THE TESTS PASS",
        bottom_text="ON THE FIRST TRY",
    )

    assert result == (
        "Saved deployment meme.png with the supplied image and captions."
    )
    request = storage.requests[0]
    assert request["ContentType"] == "image/png"
    output = Image.open(io.BytesIO(request["Body"]))
    assert output.format == "PNG"
    assert output.size == (640, 480)


def test_caption_bar_adds_space_without_cropping_the_template(monkeypatch) -> None:
    compose, storage = _composer(monkeypatch, [_image_bytes(600, 400)])
    compose("meeting.png", top_text="THIS COULD HAVE BEEN AN EMAIL", layout="caption_bar")

    output = Image.open(io.BytesIO(storage.requests[0]["Body"]))
    assert output.width == 600
    assert output.height > 400


def test_composer_requires_a_valid_latest_message_image(monkeypatch) -> None:
    compose, _ = _composer(monkeypatch, [])
    with pytest.raises(ValueError, match="latest user message"):
        compose("missing.png", top_text="NO TEMPLATE")


def test_composer_rejects_invalid_layout_and_oversized_copy(monkeypatch) -> None:
    compose, _ = _composer(monkeypatch, [_image_bytes()])
    with pytest.raises(ValueError, match="layout must be"):
        compose("bad.png", top_text="Hello", layout="unknown")
    with pytest.raises(ValueError, match="at most 300"):
        compose("long.png", top_text="x" * 301)
    with pytest.raises(ValueError, match="top_only requires"):
        compose("empty-top.png", bottom_text="Wrong field", layout="top_only")
