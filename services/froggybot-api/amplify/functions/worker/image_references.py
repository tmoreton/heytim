from __future__ import annotations

from collections.abc import Callable
from typing import Any

from boto3.dynamodb.conditions import Key

MAX_RECENT_IMAGE_REFERENCES = 5
RECENT_IMAGE_REFERENCE_TURNS = 20


def recent_image_references(
    table: Any,
    turn_partition_key: str,
    user_id: str,
    attachment_blocks: Callable[[dict, str], list[dict]],
) -> list[dict]:
    """Return recent images owned by this user and shared in this bot chat."""
    turns = table.query(
        KeyConditionExpression=Key("pk").eq(turn_partition_key)
        & Key("sk").begins_with("TURN#"),
        ScanIndexForward=False,
        Limit=RECENT_IMAGE_REFERENCE_TURNS,
        ConsistentRead=True,
    ).get("Items", [])
    references = []
    seen = set()
    for turn in turns:
        attachments = turn.get("attachments", [])
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            attachment_id = (
                attachment.get("id") if isinstance(attachment, dict) else None
            )
            if (
                not isinstance(attachment, dict)
                or attachment.get("kind") != "image"
                or not isinstance(attachment_id, str)
                or not attachment_id
                or attachment_id in seen
            ):
                continue
            try:
                blocks = attachment_blocks({"attachments": [attachment]}, user_id)
            except (TypeError, ValueError):
                # Historical uploads are optional context. One malformed record
                # must not prevent the user's current message from running.
                continue
            if not blocks or "image" not in blocks[0]:
                continue
            attachment_name = attachment.get("name")
            references.append(
                {
                    "name": (
                        attachment_name
                        if isinstance(attachment_name, str) and attachment_name.strip()
                        else f"Image {len(references) + 1}"
                    ),
                    "image": blocks[0]["image"],
                }
            )
            seen.add(attachment_id)
            if len(references) >= MAX_RECENT_IMAGE_REFERENCES:
                return references
    return references
