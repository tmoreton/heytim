from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from shared.github_app import (
    GITHUB_API_URL,
    GITHUB_API_VERSION,
    github_app_config,
    github_app_jwt,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_AWS_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"total_max_attempts": 3, "mode": "adaptive"},
)
_dynamodb = boto3.resource("dynamodb", config=_AWS_CONFIG)
_secrets = boto3.client("secretsmanager", config=_AWS_CONFIG)
_table = _dynamodb.Table(os.environ.get("TABLE_NAME", "missing"))

_MARKER = "FROGBOT_TERMINAL_ERROR "
_SAFE_SOURCE = re.compile(r"[a-z0-9_.-]{1,64}")
_SAFE_CATEGORY = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SAFE_EXCEPTION = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,127}")
_SAFE_LOCATION = re.compile(r"[A-Za-z0-9_./:-]{1,200}")
_SAFE_FINGERPRINT = re.compile(r"[a-f0-9]{24}")
_SAFE_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_SAFE_EVENT_TYPE = re.compile(r"[a-z0-9_-]{1,80}")
_MAX_LOG_EVENTS = 10_000
_MAX_DECOMPRESSED_BYTES = 1_100_000


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _positive_integer_environment(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    if not raw.isdigit() or not 1 <= int(raw) <= maximum:
        raise RuntimeError(f"{name} is invalid")
    return int(raw)


def _decode_logs_event(event: dict[str, Any]) -> dict[str, Any]:
    encoded = event.get("awslogs", {}).get("data")
    if not isinstance(encoded, str) or len(encoded) > 2_000_000:
        raise ValueError("CloudWatch Logs event is invalid")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        raw = gzip.decompress(compressed)
    except (ValueError, OSError) as exc:
        raise ValueError("CloudWatch Logs event is invalid") from exc
    if len(raw) > _MAX_DECOMPRESSED_BYTES:
        raise ValueError("CloudWatch Logs event is too large")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise TypeError("CloudWatch Logs event is invalid")
    return document


def _safe_marker(document: object) -> dict[str, object] | None:
    if not isinstance(document, dict) or document.get("schema") != 1:
        return None
    fields = {
        "source": (_SAFE_SOURCE, document.get("source")),
        "category": (_SAFE_CATEGORY, document.get("category")),
        "code": (_SAFE_CODE, document.get("code")),
        "exception": (_SAFE_EXCEPTION, document.get("exception")),
        "location": (_SAFE_LOCATION, document.get("location")),
        "fingerprint": (_SAFE_FINGERPRINT, document.get("fingerprint")),
    }
    if any(
        not isinstance(value, str) or pattern.fullmatch(value) is None
        for pattern, value in fields.values()
    ):
        return None
    return {name: value for name, (_pattern, value) in fields.items()}


def extract_incidents(event: dict[str, Any]) -> list[dict[str, object]]:
    document = _decode_logs_event(event)
    if document.get("messageType") == "CONTROL_MESSAGE":
        return []
    log_group = document.get("logGroup")
    allowed_groups = {
        value
        for value in os.environ.get("AUTOFIX_ALLOWED_LOG_GROUPS", "").split(",")
        if value
    }
    if not isinstance(log_group, str) or log_group not in allowed_groups:
        raise ValueError("CloudWatch Logs source is not authorized")
    log_events = document.get("logEvents")
    if not isinstance(log_events, list) or len(log_events) > _MAX_LOG_EVENTS:
        raise ValueError("CloudWatch Logs event list is invalid")
    incidents: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    for log_event in log_events:
        if not isinstance(log_event, dict):
            continue
        message = log_event.get("message")
        timestamp = log_event.get("timestamp")
        if (
            not isinstance(message, str)
            or _MARKER not in message
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp < 0
        ):
            continue
        marker_text = message.split(_MARKER, 1)[1].lstrip()
        try:
            marker, _end = decoder.raw_decode(marker_text)
        except json.JSONDecodeError:
            continue
        safe = _safe_marker(marker)
        if safe is None:
            continue
        occurred_at = datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(
            timespec="seconds"
        )
        incidents.append({**safe, "logGroup": log_group, "occurredAt": occurred_at})
    return incidents


def _github_request(
    method: str,
    path: str,
    token: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, Any]]:
    encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(
        f"{GITHUB_API_URL}{path}",
        data=encoded,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "FroggyBot-production-autofix",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - URL always uses the fixed GitHub API host.
            request, timeout=10
        ) as response:
            response_body = response.read(200_001)
            if len(response_body) > 200_000:
                raise RuntimeError("GitHub response was too large")
            return response.status, json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API request failed with status {exc.code}") from exc


def _github_installation_token(repository: str) -> str:
    secret_arn = _required_environment("AUTOFIX_GITHUB_APP_SECRET_ARN")
    secret = _secrets.get_secret_value(SecretId=secret_arn)
    document = json.loads(secret.get("SecretString", ""))
    config = github_app_config(document)
    app_jwt = github_app_jwt(config["appId"], config["privateKey"])
    owner, name = repository.split("/", 1)
    repository_path = "/".join(
        urllib.parse.quote(part, safe="") for part in (owner, name)
    )
    _status, installation = _github_request(
        "GET", f"/repos/{repository_path}/installation", app_jwt
    )
    installation_id = installation.get("id")
    if isinstance(installation_id, bool) or not isinstance(installation_id, int):
        raise TypeError("GitHub installation response is invalid")
    if installation_id <= 0:
        raise RuntimeError("FroggyBot GitHub App is not installed on the repository")
    _status, credential = _github_request(
        "POST",
        f"/app/installations/{installation_id}/access_tokens",
        app_jwt,
        {"repositories": [name], "permissions": {"contents": "write"}},
    )
    token = credential.get("token")
    if not isinstance(token, str) or not 20 <= len(token) <= 500:
        raise RuntimeError("GitHub installation token is invalid")
    return token


def _claim_incident(
    incident: dict[str, object],
) -> tuple[dict[str, str], dict[str, str]] | None:
    now = datetime.now(UTC)
    cooldown_hours = _positive_integer_environment("AUTOFIX_COOLDOWN_HOURS", 6, 168)
    daily_limit = _positive_integer_environment("AUTOFIX_DAILY_LIMIT", 3, 24)
    fingerprint_key = {
        "pk": "SYSTEM#AUTOFIX",
        "sk": f"INCIDENT#{incident['fingerprint']}",
    }
    daily_key = {"pk": "SYSTEM#AUTOFIX", "sk": f"DAILY#{now.date().isoformat()}"}
    expires_at = int((now + timedelta(hours=cooldown_hours)).timestamp())
    try:
        _table.put_item(
            Item={**fingerprint_key, "expiresAt": expires_at, "incident": incident},
            ConditionExpression=Attr("pk").not_exists()
            | Attr("expiresAt").lt(int(now.timestamp())),
        )
    except _table.meta.client.exceptions.ConditionalCheckFailedException:
        return None
    try:
        _table.update_item(
            Key=daily_key,
            UpdateExpression=(
                "SET dispatchCount = if_not_exists(dispatchCount, :zero) + :one, expiresAt = :expires"
            ),
            ConditionExpression=Attr("dispatchCount").not_exists()
            | Attr("dispatchCount").lt(daily_limit),
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":expires": int((now + timedelta(days=2)).timestamp()),
            },
        )
    except _table.meta.client.exceptions.ConditionalCheckFailedException:
        _table.delete_item(Key=fingerprint_key)
        return None
    return fingerprint_key, daily_key


def _release_claim(keys: tuple[dict[str, str], dict[str, str]]) -> None:
    fingerprint_key, daily_key = keys
    _table.delete_item(Key=fingerprint_key)
    try:
        _table.update_item(
            Key=daily_key,
            UpdateExpression="ADD dispatchCount :decrement",
            ConditionExpression=Attr("dispatchCount").gt(0),
            ExpressionAttributeValues={":decrement": -1},
        )
    except _table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _dispatch_incident(incident: dict[str, object]) -> None:
    repository = _required_environment("AUTOFIX_REPOSITORY")
    event_type = _required_environment("AUTOFIX_EVENT_TYPE")
    if not _SAFE_REPOSITORY.fullmatch(repository) or not _SAFE_EVENT_TYPE.fullmatch(
        event_type
    ):
        raise RuntimeError("GitHub dispatch configuration is invalid")
    release_sha = os.environ.get("AUTOFIX_RELEASE_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", release_sha):
        release_sha = ""
    token = _github_installation_token(repository)
    encoded_repository = "/".join(
        urllib.parse.quote(part, safe="") for part in repository.split("/", 1)
    )
    payload = {
        **incident,
        "environment": "production",
        "releaseSha": release_sha,
    }
    status, _body = _github_request(
        "POST",
        f"/repos/{encoded_repository}/dispatches",
        token,
        {"event_type": event_type, "client_payload": payload},
    )
    if status != 204:
        raise RuntimeError("GitHub repository dispatch was not accepted")


def handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    incidents = extract_incidents(event)
    dispatched = 0
    suppressed = 0
    for incident in incidents:
        keys = _claim_incident(incident)
        if keys is None:
            suppressed += 1
            continue
        try:
            _dispatch_incident(incident)
        except Exception:
            _release_claim(keys)
            raise
        dispatched += 1
        logger.info(
            "Dispatched production repair fingerprint=%s source=%s category=%s",
            incident["fingerprint"],
            incident["source"],
            incident["category"],
        )
    return {"dispatched": dispatched, "suppressed": suppressed}
