"""Prepare the dedicated release fixture's live AI grant without exposing it."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import uuid
from typing import Any

import boto3
import httpx

from run_managed_regression import RELEASE_TEST_ACTOR_ID

ACCOUNT_ID = "820323452649"
REGION = "us-east-1"
USER_POOL_ID = "us-east-1_biJejrNQF"
API_URL = "https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com"
FILES_BUCKET = f"heytim-production-user-files-{ACCOUNT_ID}-{REGION}"
SYNTHETIC_EMAIL = "release-smoke-20260930@heytim.ai"


def _claims_from_cognito_token(token: str, client_id: str) -> dict[str, Any]:
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, TypeError) as exc:
        raise ValueError("release fixture identity token is invalid") from exc
    if not isinstance(claims, dict) or claims.get("email") != SYNTHETIC_EMAIL:
        raise ValueError("release fixture must use the dedicated synthetic account")
    subject = claims.get("sub")
    try:
        if not isinstance(subject, str) or str(uuid.UUID(subject)) != subject:
            raise ValueError("invalid subject")
    except ValueError as exc:
        raise ValueError("release fixture identity is invalid") from exc
    actor = hashlib.sha256(f"user:{subject}".encode()).hexdigest()
    if (
        actor != RELEASE_TEST_ACTOR_ID
        or claims.get("iss") != f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
        or claims.get("aud") != client_id
        or claims.get("token_use") != "id"
        or not isinstance(claims.get("exp"), int)
        or claims["exp"] <= int(time.time())
    ):
        raise ValueError("release fixture identity does not match the destination")
    return claims


def _api_json(http: Any, method: str, path: str, token: str, body: dict | None = None) -> dict:
    request = http.get if method == "GET" else http.put
    kwargs: dict[str, Any] = {"headers": {"Authorization": f"Bearer {token}"}}
    if body is not None:
        kwargs["json"] = body
    response = request(f"{API_URL}{path}", **kwargs)
    if response.status_code != 200:
        raise RuntimeError("synthetic AI permission API request failed")
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("synthetic AI permission API response is invalid")
    return value


def prepare_consent(
    *,
    session: Any,
    http: Any,
    refresh_token: str,
    client_id: str,
    output_path: str,
) -> None:
    """Grant only the synthetic user, then read its current S3 revoke fence."""
    if session.client("sts").get_caller_identity().get("Account") != ACCOUNT_ID:
        raise ValueError("release fixture requires the destination AWS account")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("release fixture refresh token is missing")
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("release fixture client ID is missing")
    auth = session.client("cognito-idp").initiate_auth(
        AuthFlow="REFRESH_TOKEN_AUTH",
        ClientId=client_id,
        AuthParameters={"REFRESH_TOKEN": refresh_token},
    )
    id_token = auth.get("AuthenticationResult", {}).get("IdToken")
    if not isinstance(id_token, str):
        raise ValueError("release fixture ID token is missing")
    _claims_from_cognito_token(id_token, client_id)

    bootstrap = _api_json(http, "GET", "/bootstrap", id_token)
    status = bootstrap.get("aiSharingConsent")
    if not isinstance(status, dict) or status.get("version") != 1:
        raise ValueError("synthetic AI permission status is invalid")
    if status.get("granted") is not True:
        granted = _api_json(
            http, "PUT", "/account/ai-sharing", id_token,
            {"version": 1, "granted": True},
        )
        if granted != {"version": 1, "granted": True}:
            raise ValueError("synthetic AI permission was not granted")

    response = session.client("s3").get_object(
        Bucket=FILES_BUCKET,
        Key=f"users/{RELEASE_TEST_ACTOR_ID}/ai-sharing-consent.json",
    )
    with response["Body"] as body:
        raw = body.read(513)
    if len(raw) > 512:
        raise ValueError("synthetic AI permission fence is too large")
    fence = json.loads(raw)
    epoch = fence.get("epoch") if isinstance(fence, dict) else None
    if (
        not isinstance(fence, dict)
        or fence.get("version") != 1
        or fence.get("granted") is not True
        or not isinstance(epoch, str)
        or str(uuid.UUID(epoch)) != epoch
    ):
        raise ValueError("synthetic AI permission fence is invalid")
    consent = {"version": 1, "subjects": [
        {"actorId": RELEASE_TEST_ACTOR_ID, "epoch": epoch},
    ]}
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(consent, target, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare synthetic release evaluation consent.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        session = boto3.Session(region_name=REGION)
        with httpx.Client(timeout=15, follow_redirects=False) as http:
            prepare_consent(
                session=session,
                http=http,
                refresh_token=os.environ.get("HEYTIM_RELEASE_TEST_REFRESH_TOKEN", ""),
                client_id=args.client_id,
                output_path=args.output,
            )
    except Exception as exc:  # noqa: BLE001 - redact third-party responses and tokens
        print(f"Synthetic release consent preparation failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("Synthetic release evaluation permission is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
