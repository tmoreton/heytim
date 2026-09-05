from __future__ import annotations

import json
import logging
from typing import Any

from .direct_job import _process_agent_reply
from .group_job import _process_group_agent_reply, _process_group_agent_round
from .notifications import _check_push_receipts, _send_push_notification
from .scheduled_job import _process_scheduled_agent_reply, _request_string
from .support import QUEUE_URL, sqs

RETRY_VISIBILITY_SECONDS = 10

logger = logging.getLogger(__name__)


def _process(record: dict) -> None:
    request = json.loads(record["body"])
    request_type = request.get("type", "AGENT_REPLY")
    if request_type == "DELETE_ACCOUNT":
        from api.account import _delete_account

        _delete_account(
            _request_string(request, "userId", 255),
            _request_string(request, "username", 255),
        )
        return
    if request_type == "PUSH_NOTIFICATION":
        _send_push_notification(request)
        return
    if request_type == "PUSH_RECEIPTS":
        _check_push_receipts(request)
        return
    if request_type == "GROUP_AGENT_REPLY":
        _process_group_agent_reply(record, request)
        return
    if request_type == "GROUP_AGENT_ROUND":
        _process_group_agent_round(record, request)
        return
    if request_type == "SCHEDULED_AGENT_REPLY":
        _process_scheduled_agent_reply(record, request)
        return
    if request_type != "AGENT_REPLY":
        raise ValueError(f"Unknown job type: {request_type}")
    _process_agent_reply(record, request)


def handler(event: dict, _context: Any) -> dict:
    failures = []
    for record in event.get("Records", []):
        try:
            _process(record)
        except Exception:
            logger.exception(
                "Job failed for message %s", record.get("messageId", "unknown")
            )
            receipt_handle = record.get("receiptHandle")
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
