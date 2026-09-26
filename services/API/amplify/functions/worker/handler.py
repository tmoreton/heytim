from __future__ import annotations

import logging
from typing import Any

from shared.job_envelope import decode_job

from .account_cleanup import _delete_account
from .approval_job import process_approval_expiry
from .background_work import _process_background_work
from .device_calls import process_device_call_expiry
from .direct_job import _process_agent_reply
from .email_inbound_job import _process_email_inbound
from .event_routine_job import _process_event_group_round, _process_group_decision_event
from .group_job import (
    _process_group_agent_contributor,
    _process_group_agent_reply,
    _process_group_agent_round,
)
from .memory_cleanup_job import _delete_memory_actor, _delete_memory_session
from .notifications import _check_push_receipts, _send_push_notification
from .plaid_sync import delete_plaid_ledger, process_plaid_sync
from .scheduled_group_job import _process_scheduled_group_round
from .scheduled_job import _process_scheduled_agent_reply, _request_string
from .support import ACTIVE_VISIBILITY_SECONDS, QUEUE_URL, catalog, sqs

RETRY_VISIBILITY_SECONDS = 10

logger = logging.getLogger(__name__)


def _process(record: dict) -> None:
    request = decode_job(record["body"])
    request_type = request["type"]
    if request_type == "CATALOG_REFRESH":
        catalog.sync_official(force=True)
        return
    if request_type == "PLAID_SYNC":
        process_plaid_sync(request)
        return
    if request_type == "PLAID_LEDGER_DELETE":
        delete_plaid_ledger(request)
        return
    if request_type == "DELETE_ACCOUNT":
        _delete_account(
            _request_string(request, "userId", 255),
            _request_string(request, "username", 255),
        )
        return
    if request_type == "DELETE_MEMORY_ACTOR":
        _delete_memory_actor(request)
        return
    if request_type == "DELETE_MEMORY_SESSION":
        _delete_memory_session(request)
        return
    if request_type == "PUSH_NOTIFICATION":
        _send_push_notification(request)
        return
    if request_type == "PUSH_RECEIPTS":
        _check_push_receipts(request)
        return
    if request_type == "EMAIL_INBOUND":
        _process_email_inbound(record, request)
        return
    if request_type == "BACKGROUND_WORK_POLL":
        _process_background_work(record, request)
        return
    if request_type == "APPROVAL_EXPIRY":
        process_approval_expiry(request)
        return
    if request_type == "DEVICE_CALL_EXPIRY":
        process_device_call_expiry(request)
        return
    if request_type == "GROUP_AGENT_REPLY":
        _process_group_agent_reply(record, request)
        return
    if request_type == "GROUP_AGENT_ROUND":
        _process_group_agent_round(record, request)
        return
    if request_type == "GROUP_AGENT_CONTRIBUTOR":
        _process_group_agent_contributor(record, request)
        return
    if request_type == "GROUP_DECISION_EVENT":
        _process_group_decision_event(request)
        return
    if request_type == "EVENT_GROUP_ROUND":
        _process_event_group_round(record, request)
        return
    if request_type == "SCHEDULED_AGENT_REPLY":
        _process_scheduled_agent_reply(record, request)
        return
    if request_type == "SCHEDULED_GROUP_ROUND":
        _process_scheduled_group_round(record, request)
        return
    if request_type != "AGENT_REPLY":
        raise ValueError(f"Unknown job type: {request_type}")
    _process_agent_reply(record, request)


def handler(event: dict, _context: Any) -> dict:
    failures = []
    for record in event.get("Records", []):
        receipt_handle = record.get("receiptHandle")
        if isinstance(receipt_handle, str) and receipt_handle:
            try:
                sqs.change_message_visibility(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=ACTIVE_VISIBILITY_SECONDS,
                )
            except Exception:
                # The queue's longer default still prevents concurrent work. A
                # failed adjustment only means a timed-out retry will arrive later.
                logger.exception(
                    "Could not set active visibility for message %s",
                    record.get("messageId", "unknown"),
                )
        try:
            _process(record)
        except Exception:
            logger.exception(
                "Job failed for message %s", record.get("messageId", "unknown")
            )
            if isinstance(receipt_handle, str) and receipt_handle:
                try:
                    sqs.change_message_visibility(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=receipt_handle,
                        VisibilityTimeout=RETRY_VISIBILITY_SECONDS,
                    )
                except Exception:
                    logger.exception(
                        "Could not shorten retry delay for message %s",
                        record.get("messageId", "unknown"),
                    )
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
