"""Admit every direct, scheduled, email and room agent job only with live grants."""
from __future__ import annotations

from shared.ai_consent import ConsentRequired, active_grant

from .support import FILES_BUCKET_NAME, s3, table


def grants_for_job(
    user_id: str,
    billing_user_id: str,
    group_context: dict | None,
    consent_subject_ids: set[str] | None,
) -> list[dict]:
    if (
        not isinstance(billing_user_id, str)
        or not billing_user_id.strip()
        or billing_user_id != billing_user_id.strip()
    ):
        raise ValueError("A valid billing user is required for runtime invocation")
    if group_context is not None and not consent_subject_ids:
        raise ConsentRequired("Room AI sharing permission cannot be verified.")
    if not FILES_BUCKET_NAME:
        raise ConsentRequired("AI permission storage is unavailable.")
    subjects = {user_id, billing_user_id} | (consent_subject_ids or set())
    return [
        active_grant(table, s3, FILES_BUCKET_NAME, subject)
        for subject in sorted(subjects)
    ]
