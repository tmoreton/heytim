from __future__ import annotations

from .support import (
    _decode_page_cursor,
    _encode_page_cursor,
    _turn_pk,
    table,
)


def _list_turn_page(
    user_id: str, bot_id: str, cursor: object = None, limit: int = 50
) -> tuple[list[dict], str | None]:
    partition_key = _turn_pk(user_id, bot_id)
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": partition_key,
            ":prefix": "TURN#",
        },
        "ScanIndexForward": False,
        "Limit": limit,
        "ConsistentRead": True,
    }
    start_key = _decode_page_cursor(cursor, partition_key, "TURN#")
    if start_key:
        request["ExclusiveStartKey"] = start_key
    response = table.query(**request)
    items = response.get("Items", [])
    return (
        sorted(items, key=lambda item: item["createdAt"]),
        _encode_page_cursor(response.get("LastEvaluatedKey")),
    )
