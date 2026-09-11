from __future__ import annotations

import asyncio
import base64
import io
import json

import pytest
from PIL import Image

from frogbot_runtime import artifacts
from frogbot_runtime.image_generation import image_generation_tools


class FakeS3:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def put_object(self, **request) -> None:
        self.requests.append(request)


class FakeBedrock:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.requests: list[dict] = []

    def invoke_model(self, **request) -> dict:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        return {"body": io.BytesIO(json.dumps(payload).encode())}


def _image_bytes(width: int = 640, height: int = 480, mode: str = "RGB") -> bytes:
    output = io.BytesIO()
    color = (88, 190, 170, 255) if mode == "RGBA" else "#58BEAA"
    Image.new(mode, (width, height), color).save(output, format="PNG")
    return output.getvalue()


def _factory(monkeypatch, payloads: list[dict], references: list[dict] | None = None):
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    storage = FakeS3()
    bedrock = FakeBedrock(payloads)
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    tools = {
        item.tool_name: item
        for item in image_generation_tools(
            prefix,
            references,
            s3_client=storage,
            bedrock_client=bedrock,
        )
    }
    return tools, storage, bedrock


def test_image_generator_calls_bedrock_and_saves_png(monkeypatch) -> None:
    encoded = base64.b64encode(_image_bytes()).decode()
    tools, storage, bedrock = _factory(
        monkeypatch, [{"images": [encoded], "finish_reasons": [None]}]
    )

    result = asyncio.run(
        tools["generate_image"](
            "frog launch.png",
            "A cheerful frog launching a tiny rocket",
            aspect_ratio="youtube",
        )
    )

    assert result == (
        "Saved frog launch.png as an original image created with Amazon Bedrock."
    )
    request = bedrock.requests[0]
    assert request["modelId"] == "stability.stable-image-core-v1:1"
    assert request["contentType"] == "application/json"
    body = json.loads(request["body"])
    assert body["prompt"] == "A cheerful frog launching a tiny rocket"
    assert body["aspect_ratio"] == "16:9"
    assert body["output_format"] == "png"
    saved = storage.requests[0]
    assert saved["ContentType"] == "image/png"
    assert saved["ServerSideEncryption"] == "AES256"
    output = Image.open(io.BytesIO(saved["Body"]))
    assert output.format == "PNG"
    assert output.size == (640, 480)


def test_thumbnail_preserves_selected_recent_images_and_exact_text(monkeypatch) -> None:
    encoded = base64.b64encode(_image_bytes(1200, 700)).decode()
    references = [
        {"name": "logo.png", "body": _image_bytes(400, 400, "RGBA")},
        {"name": "portrait.jpg", "body": _image_bytes(800, 800)},
    ]
    tools, storage, bedrock = _factory(
        monkeypatch,
        [{"images": [encoded], "finish_reasons": [None]}],
        references,
    )

    result = asyncio.run(
        tools["create_youtube_thumbnail"](
            "comparison.png",
            "orange and teal technology faceoff",
            "CLAUDE CODE VS CODEX",
            "WHICH ONE WINS?",
            portrait_image_number=2,
            logo_image_numbers=[1],
        )
    )

    assert result == (
        "Saved comparison.png as a 1280x720 YouTube thumbnail using the selected recent images."
    )
    assert json.loads(bedrock.requests[0]["body"])["aspect_ratio"] == "16:9"
    output = Image.open(io.BytesIO(storage.requests[0]["Body"]))
    assert output.format == "PNG"
    assert output.size == (1280, 720)


def test_image_generator_rejects_invalid_inputs_and_model_data(monkeypatch) -> None:
    tools, storage, _ = _factory(monkeypatch, [{"images": ["not base64"]}])

    with pytest.raises(ValueError, match="end in .png"):
        asyncio.run(tools["generate_image"]("image.jpg", "a frog"))
    with pytest.raises(ValueError, match="between 1 and"):
        asyncio.run(tools["generate_image"]("image.png", ""))
    with pytest.raises(ValueError, match="aspect_ratio"):
        asyncio.run(tools["generate_image"]("image.png", "a frog", "wide"))
    with pytest.raises(RuntimeError, match="invalid image data"):
        asyncio.run(tools["generate_image"]("image.png", "a frog"))
    assert storage.requests == []


def test_thumbnail_rejects_an_unavailable_reference(monkeypatch) -> None:
    tools, _, bedrock = _factory(monkeypatch, [], [])
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(
            tools["create_youtube_thumbnail"](
                "missing.png",
                "technology faceoff",
                "ONE VS TWO",
                portrait_image_number=1,
            )
        )
    assert bedrock.requests == []
