"""Authenticated, explicit AI-sharing permission controls."""
from __future__ import annotations

from shared.ai_consent import (
    CONSENT_VERSION,
    ConsentBusy,
    ConsentRequired,
    active_grant,
    consent_status,
    group_subject_ids,
    set_consent,
)

from .support import FILES_BUCKET_NAME, ApiError, s3, table


def current_consent(user_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "AI permission storage is unavailable")
    return consent_status(table, s3, FILES_BUCKET_NAME, user_id)


def require_request_consent(user_id: str, group_id: str | None = None) -> None:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "AI permission storage is unavailable")
    try:
        subjects = ({user_id} if group_id is None
                    else group_subject_ids(table, group_id) | {user_id})
        for subject in sorted(subjects):
            active_grant(table, s3, FILES_BUCKET_NAME, subject)
    except ConsentRequired as exc:
        raise ApiError(409, str(exc), code="ai_consent_required") from exc


def grant_consent(user_id: str, value: dict) -> dict:
    if value != {"version": CONSENT_VERSION, "granted": True}:
        raise ApiError(400, "Confirm the current AI sharing disclosure to continue")
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "AI permission storage is unavailable")
    try:
        return set_consent(table, s3, FILES_BUCKET_NAME, user_id, True)
    except ConsentBusy as exc:
        raise ApiError(409, str(exc), code="ai_consent_busy") from exc


def revoke_consent(user_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "AI permission storage is unavailable")
    try:
        return set_consent(table, s3, FILES_BUCKET_NAME, user_id, False)
    except ConsentBusy as exc:
        raise ApiError(409, str(exc), code="ai_consent_busy") from exc
