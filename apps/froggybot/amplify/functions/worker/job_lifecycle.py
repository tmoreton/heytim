from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .work import _finish_work, _release_work

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Attempt:
    receive_count: int


class FailureDisposition(Enum):
    RETRY = "retry"
    FINISHED = "finished"
    LOST_LEASE = "lost_lease"


@dataclass(frozen=True)
class FailureOutcome:
    disposition: FailureDisposition
    completed_at: str | None = None


def begin_attempt(record: dict, cleanup_artifacts: Callable[[], None]) -> Attempt:
    receive_count = int(
        record.get("attributes", {}).get("ApproximateReceiveCount", "1")
    )
    if receive_count > 1:
        cleanup_artifacts()
    return Attempt(receive_count=max(1, receive_count))


def finish_failed_attempt(
    attempt: Attempt,
    work_key: dict,
    lease_owner: str,
    answer_field: str,
    failure_answer: str,
    cleanup_artifacts: Callable[[], None],
) -> FailureOutcome:
    if attempt.receive_count < MAX_ATTEMPTS:
        _release_work(work_key, lease_owner)
        return FailureOutcome(FailureDisposition.RETRY)
    cleanup_artifacts()
    completed_at = _finish_work(
        work_key,
        lease_owner,
        "ERROR",
        answer_field,
        failure_answer,
    )
    if not completed_at:
        return FailureOutcome(FailureDisposition.LOST_LEASE)
    return FailureOutcome(FailureDisposition.FINISHED, completed_at)
