from __future__ import annotations

import asyncio
import base64
import io

import pytest
from PIL import Image

from frogbot_runtime import artifacts, image_generation
from frogbot_runtime.image_generation import image_generation_tool


class FakeS3:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def put_object(self, **request) -> None:
        self.requests.append(request)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self) -> dict:
        return self.payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    async def post(self, url: str, **request) -> FakeResponse:
        self.requests.append({"url": url, **request})
        return self.responses.pop(0)


def _jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (640, 480), "#58BEAA").save(output, format="JPEG")
    return output.getvalue()


def _tool(monkeypatch, responses: list[FakeResponse]):
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    storage = FakeS3()
    http = FakeHttpClient(responses)

    async def api_key() -> str:
        return "secret-openrouter-key"

    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    return (
        image_generation_tool(
            prefix,
            s3_client=storage,
            http_client=http,
            api_key_loader=api_key,
        ),
        storage,
        http,
    )


def test_image_generator_calls_muse_with_prompt_only_and_saves_png(monkeypatch) -> None:
    encoded = base64.b64encode(_jpeg_bytes()).decode()
    generate, storage, http = _tool(
        monkeypatch,
        [FakeResponse(200, {"data": [{"b64_json": encoded, "media_type": "image/jpeg"}]})],
    )

    result = asyncio.run(
        generate("frog launch.png", "A cheerful frog launching a tiny rocket")
    )

    assert result == (
        "Saved frog launch.png as an original image created with Muse Image."
    )
    assert http.requests == [
        {
            "url": "https://openrouter.ai/api/v1/images",
            "headers": {
                "Authorization": "Bearer secret-openrouter-key",
                "HTTP-Referer": "https://froggybot.com",
                "X-OpenRouter-Title": "FroggyBot",
            },
            "json": {
                "model": "meta/muse-image",
                "prompt": "A cheerful frog launching a tiny rocket",
            },
        }
    ]
    request = storage.requests[0]
    assert request["ContentType"] == "image/png"
    assert request["ServerSideEncryption"] == "AES256"
    output = Image.open(io.BytesIO(request["Body"]))
    assert output.format == "PNG"
    assert output.size == (640, 480)


def test_image_generator_retries_a_non_billable_upstream_failure(monkeypatch) -> None:
    encoded = base64.b64encode(_jpeg_bytes()).decode()
    generate, storage, http = _tool(
        monkeypatch,
        [
            FakeResponse(502, {}),
            FakeResponse(200, {"data": [{"b64_json": encoded}]}),
        ],
    )

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(image_generation.asyncio, "sleep", no_sleep)
    asyncio.run(generate("retry.png", "A frog trying one more time"))

    assert len(http.requests) == 2
    assert len(storage.requests) == 1


def test_image_generator_rejects_invalid_inputs_and_remote_data(monkeypatch) -> None:
    generate, storage, _ = _tool(
        monkeypatch,
        [FakeResponse(200, {"data": [{"b64_json": "not base64"}]})],
    )

    with pytest.raises(ValueError, match="end in .png"):
        asyncio.run(generate("image.jpg", "a frog"))
    with pytest.raises(ValueError, match="between 1 and"):
        asyncio.run(generate("image.png", ""))
    with pytest.raises(RuntimeError, match="invalid image data"):
        asyncio.run(generate("image.png", "a frog"))
    assert storage.requests == []
