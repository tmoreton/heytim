"""Verified GitHub App issue-opened event ingress for room routines."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from datetime import UTC, datetime

from shared.job_envelope import send_job

from .github_oauth import _secret_client
from .support import QUEUE_URL, ApiError, _partition_items, _response, sqs

MAX_WEBHOOK_BYTES = 256_000
_DELIVERY_ID = re.compile(r"[A-Za-z0-9-]{1,128}\Z")
_SIGNATURE = re.compile(r"sha256=([a-f0-9]{64})\Z")


def _webhook_secret() -> str:
    secret_arn = os.environ.get("GITHUB_APP_SECRET_ARN")
    if not secret_arn:
        raise ApiError(503, "GitHub webhooks are not configured")
    raw = _secret_client().get_secret_value(SecretId=secret_arn).get("SecretString")
    try:
        document = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise ApiError(503, "GitHub webhooks are not configured") from exc
    secret = document.get("webhookSecret") if isinstance(document, dict) else None
    if not isinstance(secret, str) or not 32 <= len(secret) <= 500:
        raise ApiError(503, "GitHub webhooks are not configured")
    return secret


def _header(event: dict, name: str) -> str:
    headers = event.get("headers") or {}
    return next(
        (value for key, value in headers.items() if key.lower() == name and isinstance(value, str)),
        "",
    )


def _raw_body(event: dict) -> bytes:
    body = event.get("body")
    if not isinstance(body, str):
        raise ApiError(400, "Webhook payload is invalid")
    try:
        raw = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode("utf-8")
    except (UnicodeError, ValueError, binascii.Error) as exc:
        raise ApiError(400, "Webhook payload is invalid") from exc
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise ApiError(413, "Webhook payload is too large")
    return raw


def _positive_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ApiError(400, "Webhook event identity is invalid")
    return value


def _issue_event(value: object) -> dict:
    if not isinstance(value, dict) or value.get("action") != "opened":
        raise ApiError(400, "Webhook issue event is invalid")
    installation = value.get("installation")
    repository = value.get("repository")
    issue = value.get("issue")
    if not all(isinstance(item, dict) for item in (installation, repository, issue)):
        raise ApiError(400, "Webhook issue event is invalid")
    installation_id = _positive_id(installation.get("id"))
    repository_id = _positive_id(repository.get("id"))
    issue_number = _positive_id(issue.get("number"))
    repository_name = repository.get("full_name")
    title = issue.get("title")
    body = issue.get("body") or ""
    created_at = issue.get("created_at")
    if (
        not isinstance(repository_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_name)
        or not isinstance(title, str) or not title.strip()
        or not isinstance(body, str)
        or not isinstance(created_at, str)
    ):
        raise ApiError(400, "Webhook issue event is invalid")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if parsed_created_at.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise ApiError(400, "Webhook issue event is invalid") from exc
    return {
        "installationId": str(installation_id),
        "repositoryId": repository_id,
        "repositoryName": repository_name,
        "number": issue_number,
        "title": title[:300], "body": body[:4_000],
        "createdAt": parsed_created_at.astimezone(UTC).isoformat(timespec="milliseconds"),
    }


def github_issue_webhook(event: dict) -> dict:
    raw = _raw_body(event)
    signature = _header(event, "x-hub-signature-256")
    match = _SIGNATURE.fullmatch(signature)
    expected = hmac.new(_webhook_secret().encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not match or not hmac.compare_digest(match.group(1), expected):
        raise ApiError(401, "Webhook signature is invalid")
    delivery_id = _header(event, "x-github-delivery")
    if not _DELIVERY_ID.fullmatch(delivery_id):
        raise ApiError(400, "Webhook delivery identity is invalid")
    if _header(event, "x-github-event") != "issues":
        return _response(200, {"accepted": False})
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Webhook payload is invalid") from exc
    if not isinstance(value, dict) or value.get("action") != "opened":
        return _response(200, {"accepted": False})
    issue = _issue_event(value)
    partition = f"GITHUB_EVENT#{issue['installationId']}#{issue['repositoryId']}"
    subscriptions = _partition_items(partition, "ROUTINE#")
    matched = 0
    for subscription in subscriptions:
        if subscription.get("entity") != "GITHUB_ROUTINE_SUBSCRIPTION":
            continue
        send_job(
            sqs,
            QUEUE_URL,
            {
                "type": "EVENT_GROUP_ROUND", "groupId": subscription["groupId"],
                "routineId": subscription["routineId"],
                "deliveryId": delivery_id, "githubIssue": issue,
            },
        )
        matched += 1
    return _response(202, {"accepted": True, "matchedRoutines": matched})
