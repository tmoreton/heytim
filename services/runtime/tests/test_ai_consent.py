from __future__ import annotations

import asyncio
import io
import json
import uuid

import pytest

from heytim_runtime import ai_consent
from heytim_runtime.image_generation import _invoke_image
from model.load import IncompleteOpenRouterResponseError, ResilientOpenRouterModel


class FakeS3:
    def __init__(self, fences: dict[str, dict]) -> None:
        self.fences = fences

    def get_object(self, *, Key: str, **_kwargs):
        return {"Body": io.BytesIO(json.dumps(self.fences[Key]).encode())}


def test_runtime_requires_matching_permission_for_every_room_subject(monkeypatch) -> None:
    monkeypatch.setattr(ai_consent, "FILES_BUCKET_NAME", "files")
    first, second = "a" * 64, "b" * 64
    epoch = str(uuid.uuid4())
    payload = {
        "aiConsent": {
            "version": 1,
            "subjects": [
                {"actorId": first, "epoch": epoch},
                {"actorId": second, "epoch": epoch},
            ],
        }
    }
    storage = FakeS3({
        f"users/{actor}/ai-sharing-consent.json": {
            "version": 1, "granted": True, "epoch": epoch
        }
        for actor in (first, second)
    })
    asyncio.run(ai_consent.check_ai_consent(payload, s3_client=storage))

    storage.fences[f"users/{second}/ai-sharing-consent.json"]["granted"] = False
    with pytest.raises(ai_consent.AIConsentRevoked):
        asyncio.run(ai_consent.check_ai_consent(payload, s3_client=storage))


def test_runtime_denies_missing_or_malformed_permission(monkeypatch) -> None:
    monkeypatch.setattr(ai_consent, "FILES_BUCKET_NAME", "files")
    with pytest.raises(ai_consent.AIConsentRevoked):
        asyncio.run(ai_consent.check_ai_consent({}, s3_client=FakeS3({})))
    with pytest.raises(ai_consent.AIConsentRevoked):
        asyncio.run(ai_consent.check_ai_consent({"aiConsent": {"version": 1, "subjects": []}}, s3_client=FakeS3({})))


def test_model_retry_rechecks_consent_before_second_provider_call() -> None:
    class FakeModel:
        calls = 0

        async def stream(self, *_args, **_kwargs):
            self.calls += 1
            raise IncompleteOpenRouterResponseError("retry")
            yield {}

        def get_config(self):
            return {"model_id": "test"}

    underlying = FakeModel()
    checks = 0

    async def check() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ai_consent.AIConsentRevoked("revoked")

    async def run() -> None:
        model = ResilientOpenRouterModel(underlying, before_dispatch=check)
        async for _ in model.stream([]):
            pass

    with pytest.raises(ai_consent.AIConsentRevoked):
        asyncio.run(run())
    assert checks == 2
    assert underlying.calls == 1


def test_image_call_checks_consent_before_http_dispatch() -> None:
    class FakeHTTP:
        calls = 0

        async def post(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("Provider must not receive a revoked request")

    async def revoked() -> None:
        raise ai_consent.AIConsentRevoked("revoked")

    client = FakeHTTP()
    with pytest.raises(ai_consent.AIConsentRevoked):
        asyncio.run(_invoke_image(client, "key", "prompt", "1:1", before_dispatch=revoked))
    assert client.calls == 0
