from __future__ import annotations

import asyncio
import base64
import io

import pytest
from PIL import Image, ImageDraw

from frogbot_runtime import artifacts, image_generation
from frogbot_runtime.image_generation import image_generation_tools
from model.usage import (
    ProviderCallLimitExceeded,
    ProviderCallLimits,
    UsageAccumulator,
)


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


def _image_bytes(width: int = 640, height: int = 480) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#58BEAA").save(output, format="PNG")
    return output.getvalue()


def _logo_bytes() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((40, 40, 360, 360), fill=(95, 94, 255, 255))
    image.save(output, format="PNG")
    return output.getvalue()


def _factory(
    monkeypatch,
    responses: list[FakeResponse],
    references: list[dict] | None = None,
    usage: UsageAccumulator | None = None,
):
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    storage = FakeS3()
    http = FakeHttpClient(responses)

    async def api_key() -> str:
        return "secret-openrouter-key"

    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    tools = {
        item.tool_name: item
        for item in image_generation_tools(
            prefix,
            references,
            s3_client=storage,
            http_client=http,
            api_key_loader=api_key,
            usage=usage,
        )
    }
    return tools, storage, http


def _success(width: int = 640, height: int = 480) -> FakeResponse:
    encoded = base64.b64encode(_image_bytes(width, height)).decode()
    return FakeResponse(200, {"data": [{"b64_json": encoded}]})


def test_image_generator_calls_openrouter_and_saves_png(monkeypatch) -> None:
    tools, storage, http = _factory(monkeypatch, [_success()])

    result = asyncio.run(
        tools["generate_image"](
            "frog launch.png",
            "A cheerful frog launching a tiny rocket",
            aspect_ratio="youtube",
        )
    )

    assert result == (
        "Saved frog launch.png as an original image created with OpenRouter."
    )
    request = http.requests[0]
    assert request["url"] == "https://openrouter.ai/api/v1/images"
    assert request["headers"]["Authorization"] == "Bearer secret-openrouter-key"
    assert request["json"] == {
        "model": "openai/gpt-image-2.5-sunburst",
        "prompt": "A cheerful frog launching a tiny rocket",
        "aspect_ratio": "16:9",
        "quality": "high",
        "output_format": "png",
    }
    saved = storage.requests[0]
    assert saved["ContentType"] == "image/png"
    assert "ServerSideEncryption" not in saved
    output = Image.open(io.BytesIO(saved["Body"]))
    assert output.format == "PNG"
    assert output.size == (640, 480)


def test_thumbnail_sends_full_composition_and_references_to_openrouter(
    monkeypatch,
) -> None:
    references = [
        {"name": "logo.png", "body": _logo_bytes()},
        {"name": "portrait.jpg", "body": _image_bytes(800, 800)},
    ]
    tools, storage, http = _factory(monkeypatch, [_success(1536, 1024)], references)

    result = asyncio.run(
        tools["create_youtube_thumbnail"](
            "comparison.png",
            "two coding assistants racing through processor tracks",
            "I TESTED BOTH",
            "ONE WINS",
            portrait_image_number=2,
            logo_image_numbers=[1],
        )
    )

    assert result == (
        "Saved comparison.png as an OpenRouter-generated 1280x720 YouTube thumbnail "
        "using the selected recent images."
    )
    request = http.requests[0]["json"]
    assert request["aspect_ratio"] == "16:9"
    assert request["quality"] == "high"
    assert "complete, finished premium YouTube thumbnail" in request["prompt"]
    assert 'headline: "I TESTED BOTH"' in request["prompt"]
    assert 'secondary line: "ONE WINS"' in request["prompt"]
    assert "do not put them inside a circle" in request["prompt"]
    assert "or place it inside a white tile" in request["prompt"]
    assert len(request["input_references"]) == 2
    portrait = request["input_references"][0]["image_url"]["url"]
    logo = request["input_references"][1]["image_url"]["url"]
    assert portrait.startswith("data:image/jpeg;base64,")
    assert logo.startswith("data:image/png;base64,")
    output = Image.open(io.BytesIO(storage.requests[0]["Body"]))
    assert output.format == "PNG"
    assert output.size == (1280, 720)


def test_thumbnail_keeps_single_subject_briefs_out_of_comparison_mode(
    monkeypatch,
) -> None:
    tools, _, http = _factory(monkeypatch, [_success(1200, 700)])

    asyncio.run(
        tools["create_youtube_thumbnail"](
            "launch.png",
            "a frog launching a new coding tool",
            "SHIP FASTER",
        )
    )

    prompt = http.requests[0]["json"]["prompt"]
    assert "one unmistakable focal story" in prompt
    assert "warm-amber versus cool-cyan" not in prompt
    assert "input_references" not in http.requests[0]["json"]


def test_image_generator_retries_a_transient_openrouter_failure(monkeypatch) -> None:
    usage = UsageAccumulator()
    tools, storage, http = _factory(
        monkeypatch, [FakeResponse(502, {}), _success()], usage=usage
    )

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(image_generation.asyncio, "sleep", no_sleep)
    asyncio.run(tools["generate_image"]("retry.png", "A frog trying again"))

    assert len(http.requests) == 2
    assert len(storage.requests) == 1
    assert usage.snapshot()["tools"] == [
        {
            "provider": "openrouter",
            "operation": "generate_image",
            "callCount": 2,
        }
    ]


def test_image_retry_reserves_each_http_attempt_before_dispatch(monkeypatch) -> None:
    usage = UsageAccumulator(
        ProviderCallLimits(
            model_calls=10,
            provider_tool_calls=10,
            image_calls=1,
        )
    )
    tools, storage, http = _factory(
        monkeypatch, [FakeResponse(502, {}), _success()], usage=usage
    )

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(image_generation.asyncio, "sleep", no_sleep)
    with pytest.raises(ProviderCallLimitExceeded, match="image-generation"):
        asyncio.run(tools["generate_image"]("retry.png", "A frog trying again"))

    assert len(http.requests) == 1
    assert storage.requests == []


def test_image_generation_limit_blocks_before_openrouter_call(monkeypatch) -> None:
    usage = UsageAccumulator(
        ProviderCallLimits(
            model_calls=10,
            provider_tool_calls=10,
            image_calls=1,
        )
    )
    tools, _, http = _factory(monkeypatch, [_success()], usage=usage)

    asyncio.run(tools["generate_image"]("first.png", "A frog"))
    with pytest.raises(ProviderCallLimitExceeded, match="image-generation"):
        asyncio.run(tools["generate_image"]("second.png", "Another frog"))

    assert len(http.requests) == 1


def test_image_generator_does_not_retry_an_auth_failure(monkeypatch) -> None:
    tools, storage, http = _factory(monkeypatch, [FakeResponse(401, {})])

    with pytest.raises(RuntimeError, match="rejected.*credential"):
        asyncio.run(tools["generate_image"]("auth.png", "A frog"))

    assert len(http.requests) == 1
    assert storage.requests == []


def test_image_generator_rejects_invalid_inputs_and_remote_data(monkeypatch) -> None:
    tools, storage, _ = _factory(
        monkeypatch, [FakeResponse(200, {"data": [{"b64_json": "not base64"}]})]
    )

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
    tools, _, http = _factory(monkeypatch, [], [])
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(
            tools["create_youtube_thumbnail"](
                "missing.png",
                "technology faceoff",
                "ONE VS TWO",
                portrait_image_number=1,
            )
        )
    assert http.requests == []
