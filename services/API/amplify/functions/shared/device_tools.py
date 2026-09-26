"""Validation and selection for short-lived client-executed tool capabilities."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .device_contract import (
    DEVICE_OPERATION_PLATFORMS,
    DEVICE_TOOL_IDS,
    DEVICE_TOOL_OPERATIONS,
    MAX_DEVICE_OPERATIONS,
)

DEVICE_LEASE_SECONDS = 180
MAX_DEVICES_PER_ACCOUNT = 12


def validate_device_binding(value: Any) -> dict:
    if not isinstance(value, dict):
        raise TypeError("device tool runtime is invalid")
    platform = value.get("platform")
    operations = value.get("operations")
    interactive = value.get("interactiveOperations", [])
    if (
        platform not in {"ios", "macos"}
        or not isinstance(operations, list)
        or not 1 <= len(operations) <= MAX_DEVICE_OPERATIONS
        or not all(isinstance(operation, str) for operation in operations)
        or len(operations) != len(set(operations))
        or any(
            not isinstance(operation, str)
            or DEVICE_OPERATION_PLATFORMS.get(operation) != platform
            for operation in operations
        )
        or not isinstance(interactive, list)
        or not all(isinstance(operation, str) for operation in interactive)
        or len(interactive) != len(set(interactive))
        or not set(interactive).issubset(operations)
    ):
        raise ValueError("device tool runtime is invalid")
    return {
        "kind": "device",
        "platform": platform,
        "operations": operations,
        "interactiveOperations": interactive,
    }


def _active_devices(table: Any, user_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":prefix": "DEVICE#",
        },
        ConsistentRead=True,
    ).get("Items", [])
    now = int(datetime.now(UTC).timestamp())
    return [
        item
        for item in items[:MAX_DEVICES_PER_ACCOUNT]
        if item.get("entity") == "DEVICE_CAPABILITIES"
        and isinstance(item.get("deviceId"), str)
        and item.get("platform") in {"ios", "macos"}
        and int(item.get("leaseExpiresAt", 0)) > now
    ]


def _grants(item: dict, bot_id: str, tool_id: str) -> bool:
    return any(
        isinstance(grant, dict)
        and grant.get("botId") == bot_id
        and isinstance(grant.get("toolIds"), list)
        and tool_id in grant["toolIds"]
        for grant in item.get("botGrants", [])
    )


def _operations(item: dict, tool_id: str) -> set[str]:
    for capability in item.get("tools", []):
        if (
            isinstance(capability, dict)
            and capability.get("id") == tool_id
            and isinstance(capability.get("operations"), list)
        ):
            return {
                operation
                for operation in capability["operations"]
                if isinstance(operation, str)
            }
    return set()


def available_device_tools(
    table: Any,
    user_id: str,
    bot_id: str,
    resolved_tools: list[dict],
) -> list[dict]:
    devices = _active_devices(table, user_id)
    result = []
    for item in resolved_tools:
        runtime = item.get("runtime", {})
        if runtime.get("kind") != "device":
            result.append(item)
            continue
        tool_id = item.get("id")
        platform = runtime.get("platform")
        available = set()
        for device in devices:
            if device.get("platform") == platform and _grants(device, bot_id, tool_id):
                available.update(_operations(device, tool_id))
        operations = [
            operation
            for operation in runtime.get("operations", [])
            if operation in available
        ]
        if not operations:
            continue
        result.append(
            {
                **item,
                "runtime": {
                    **runtime,
                    "operations": operations,
                    "interactiveOperations": [
                        operation
                        for operation in runtime.get("interactiveOperations", [])
                        if operation in operations
                    ],
                },
            }
        )
    return result


def select_device(
    table: Any,
    user_id: str,
    bot_id: str,
    *,
    tool_id: str,
    operation: str,
    platform: str,
) -> dict | None:
    candidates = [
        item
        for item in _active_devices(table, user_id)
        if item.get("platform") == platform
        and _grants(item, bot_id, tool_id)
        and operation in _operations(item, tool_id)
    ]
    return max(candidates, key=lambda item: item.get("lastSeenAt", ""), default=None)


__all__ = [
    "DEVICE_LEASE_SECONDS",
    "DEVICE_OPERATION_PLATFORMS",
    "DEVICE_TOOL_IDS",
    "DEVICE_TOOL_OPERATIONS",
    "available_device_tools",
    "select_device",
    "validate_device_binding",
]
