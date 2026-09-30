"""Recheck versioned AI permission immediately before third-party model calls."""
from __future__ import annotations

import asyncio
import json
import re
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .artifacts import FILES_BUCKET_NAME

CONSENT_VERSION = 1


class AIConsentRevoked(RuntimeError):
    """The current run no longer has permission to contact an AI provider."""


def _subjects(payload: dict) -> list[dict]:
    value = payload.get("aiConsent")
    if not isinstance(value, dict) or value.get("version") != CONSENT_VERSION:
        raise AIConsentRevoked("AI processing permission is required.")
    subjects = value.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise AIConsentRevoked("AI processing permission is required.")
    seen: set[str] = set()
    for subject in subjects:
        if not isinstance(subject, dict):
            raise AIConsentRevoked("AI processing permission is invalid.")
        actor = subject.get("actorId")
        epoch = subject.get("epoch")
        if (
            not isinstance(actor, str)
            or not re.fullmatch(r"[0-9a-f]{64}", actor)
            or actor in seen
            or not isinstance(epoch, str)
        ):
            raise AIConsentRevoked("AI processing permission is invalid.")
        try:
            uuid.UUID(epoch)
        except ValueError as exc:
            raise AIConsentRevoked("AI processing permission is invalid.") from exc
        seen.add(actor)
    return subjects


def _fence_matches(storage, actor: str, epoch: str) -> bool:
    try:
        response = storage.get_object(
            Bucket=FILES_BUCKET_NAME,
            Key=f"users/{actor}/ai-sharing-consent.json",
        )
        with response["Body"] as body:
            raw = body.read(513)
        if len(raw) > 512:
            return False
        fence = json.loads(raw)
    except (BotoCoreError, ClientError, KeyError, OSError, ValueError, UnicodeDecodeError):
        return False
    return (
        isinstance(fence, dict)
        and fence.get("version") == CONSENT_VERSION
        and fence.get("granted") is True
        and fence.get("epoch") == epoch
    )


async def check_ai_consent(payload: dict, *, s3_client=None) -> None:
    """Deny if any subject's fence changed since the worker assembled the job."""
    subjects = _subjects(payload)
    if not FILES_BUCKET_NAME:
        raise AIConsentRevoked("AI processing permission storage is unavailable.")
    storage = s3_client or boto3.client("s3")
    for subject in subjects:
        allowed = await asyncio.to_thread(
            _fence_matches, storage, subject["actorId"], subject["epoch"]
        )
        if not allowed:
            raise AIConsentRevoked("AI processing permission was revoked.")
