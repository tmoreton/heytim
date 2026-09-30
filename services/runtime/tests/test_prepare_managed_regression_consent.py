from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import prepare_managed_regression_consent as preparation

SUBJECT = "00000000-0000-4000-8000-000000000001"
ACTOR = hashlib.sha256(f"user:{SUBJECT}".encode()).hexdigest()
EPOCH = "00000000-0000-4000-8000-000000000002"


def token(email: str = preparation.SYNTHETIC_EMAIL) -> str:
    claims = {
        "email": email,
        "sub": SUBJECT,
        "iss": f"https://cognito-idp.{preparation.REGION}.amazonaws.com/{preparation.USER_POOL_ID}",
        "aud": "client",
        "token_use": "id",
        "exp": int(time.time()) + 300,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeSession:
    def __init__(self, id_token: str, fence: dict | None = None) -> None:
        self.id_token = id_token
        self.fence = fence or {"version": 1, "granted": True, "epoch": EPOCH}
        self.keys: list[dict] = []

    def client(self, service: str):
        session = self
        if service == "sts":
            class Sts:
                def get_caller_identity(self):
                    return {"Account": preparation.ACCOUNT_ID}
            return Sts()
        if service == "cognito-idp":
            class Cognito:
                def initiate_auth(self, **_kwargs):
                    return {"AuthenticationResult": {"IdToken": session.id_token}}
            return Cognito()
        if service == "s3":
            class S3:
                def get_object(self, **kwargs):
                    session.keys.append(kwargs)
                    return {"Body": io.BytesIO(json.dumps(session.fence).encode())}
            return S3()
        raise AssertionError(service)


class FakeHttp:
    def __init__(self, granted: bool = False) -> None:
        self.granted = granted
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        return FakeResponse({"aiSharingConsent": {"version": 1, "granted": self.granted}})

    def put(self, url: str, **kwargs):
        self.calls.append(url)
        assert kwargs["json"] == {"version": 1, "granted": True}
        return FakeResponse({"version": 1, "granted": True})


class FakeResponse:
    status_code = 200

    def __init__(self, value: dict) -> None:
        self.value = value

    def json(self):
        return self.value


def test_prepares_private_grant_for_only_synthetic_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(preparation, "RELEASE_TEST_ACTOR_ID", ACTOR)
    session = FakeSession(token())
    http = FakeHttp()
    path = tmp_path / "consent.json"
    preparation.prepare_consent(
        session=session, http=http, refresh_token="synthetic-refresh",
        client_id="client", output_path=str(path),
    )
    assert [item.removeprefix(preparation.API_URL) for item in http.calls] == [
        "/bootstrap", "/account/ai-sharing",
    ]
    assert session.keys == [{
        "Bucket": preparation.FILES_BUCKET,
        "Key": f"users/{ACTOR}/ai-sharing-consent.json",
    }]
    assert path.stat().st_mode & 0o077 == 0
    assert json.loads(path.read_text()) == {"version": 1, "subjects": [
        {"actorId": ACTOR, "epoch": EPOCH},
    ]}
    assert "synthetic-refresh" not in path.read_text()


def test_existing_grant_is_reused_without_rotating_epoch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(preparation, "RELEASE_TEST_ACTOR_ID", ACTOR)
    http = FakeHttp(granted=True)
    preparation.prepare_consent(
        session=FakeSession(token()), http=http, refresh_token="refresh",
        client_id="client", output_path=str(tmp_path / "consent.json"),
    )
    assert http.calls == [f"{preparation.API_URL}/bootstrap"]


def test_rejects_other_user_and_revoked_fence_before_writing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(preparation, "RELEASE_TEST_ACTOR_ID", ACTOR)
    path = tmp_path / "consent.json"
    http = FakeHttp()
    with pytest.raises(ValueError, match="dedicated synthetic account"):
        preparation.prepare_consent(
            session=FakeSession(token("real@example.invalid")), http=http,
            refresh_token="refresh", client_id="client", output_path=str(path),
        )
    assert http.calls == []
    with pytest.raises(ValueError, match="fence is invalid"):
        preparation.prepare_consent(
            session=FakeSession(token(), {"version": 1, "granted": False, "epoch": EPOCH}),
            http=http, refresh_token="refresh", client_id="client", output_path=str(path),
        )
    assert not path.exists()
