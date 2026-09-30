"""Read-only, metadata-only DynamoDB and SQS provider cutover inventory.

The optional identity file is private and contains keys to look up. Neither
those keys nor customer payload fields are copied into the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
REGION = "us-east-1"
ALLOWED_ACCOUNTS = {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}
COUNTS = (
    "stripe_markers", "stripe_billing", "github_subscription_indexes",
    "github_group_messages", "plaid_item_mappings", "plaid_sync_rows",
    "plaid_connections",
)
IDENTITY_FIELDS = {
    "stripeEvents": {"id"},
    "stripeBilling": {"userId"},
    "githubIndexes": {"installationId", "repositoryId"},
    "githubMessages": {"groupId", "deliveryId", "routineId"},
    "plaidItems": {"environment", "itemId"},
    "plaidSync": {"userId", "connectionId"},
}
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,200}\Z")
SAFE_KEY = re.compile(r"[A-Za-z0-9._#-]{1,300}\Z")


def _s(value: str) -> dict[str, str]:
    if not isinstance(value, str) or not SAFE_KEY.fullmatch(value):
        raise ValueError("Identity file contains an invalid identifier")
    return {"S": value}


def _private_identities(path: Path | None) -> dict[str, list[dict[str, str]]]:
    if path is None:
        return {name: [] for name in IDENTITY_FIELDS}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError("Identity file must be a private regular file with mode 0600")
        with os.fdopen(fd, "r") as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict) or set(value) - set(IDENTITY_FIELDS):
        raise ValueError("Identity file has unapproved fields")
    result = {}
    for name, fields in IDENTITY_FIELDS.items():
        entries = value.get(name, [])
        if not isinstance(entries, list) or len(entries) > 500:
            raise ValueError("Identity list is invalid or too large")
        if any(not isinstance(item, dict) or set(item) != fields or
               any(not isinstance(field, str) or not SAFE_ID.fullmatch(field) for field in item.values())
               for item in entries):
            raise ValueError("Identity file has unapproved fields or values")
        result[name] = entries
    return result


def _get(table: Any, table_name: str, pk: str, sk: str, columns: tuple[str, ...]) -> dict:
    # Projection ensures no message, finance, token, or webhook payload is read.
    names = {f"#{i}": field for i, field in enumerate(columns)}
    response = table.get_item(
        TableName=table_name,
        Key={"pk": _s(pk), "sk": _s(sk)},
        ConsistentRead=True,
        ProjectionExpression=",".join(names),
        ExpressionAttributeNames=names,
    )
    return response.get("Item", {})


def _query_index(table: Any, table_name: str, pk: str) -> int:
    paginator = table.get_paginator("query")
    found = 0
    for page in paginator.paginate(
        TableName=table_name,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _s(pk), ":prefix": _s("ROUTINE#")},
        ProjectionExpression="#entity",
        ExpressionAttributeNames={"#entity": "entity"},
        ConsistentRead=True,
    ):
        found += sum(item.get("entity", {}).get("S") == "GITHUB_ROUTINE_SUBSCRIPTION" for item in page.get("Items", []))
    return found


def _query_message(table: Any, table_name: str, group_id: str, delivery_id: str, routine_id: str) -> int:
    paginator = table.get_paginator("query")
    found = 0
    for page in paginator.paginate(
        TableName=table_name,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": _s(f"GROUP#{group_id}")},
        ProjectionExpression="#entity,eventId,routineId,eventType",
        ExpressionAttributeNames={"#entity": "entity"},
        ConsistentRead=True,
    ):
        for item in page.get("Items", []):
            if (item.get("entity", {}).get("S") == "GROUP_MESSAGE"
                and item.get("eventType", {}).get("S") == "github.issue.opened"
                and item.get("eventId", {}).get("S") == delivery_id
                and item.get("routineId", {}).get("S") == routine_id):
                found += 1
    return found


def inventory(session: Any, account: str, table_name: str,
              identities: dict[str, list[dict[str, str]]], jobs_queue_url: str | None = None) -> dict:
    if account not in ALLOWED_ACCOUNTS or session.region_name != REGION:
        raise ValueError("Account or region is not reviewed")
    actual = session.client("sts").get_caller_identity().get("Account")
    if actual != account:
        raise ValueError("AWS account mismatch; no table was queried")
    table = session.client("dynamodb", config=Config(retries={"total_max_attempts": 3, "mode": "standard"}))
    description = table.describe_table(TableName=table_name)["Table"]
    expected_prefix = f"arn:aws:dynamodb:{REGION}:{account}:table/"
    if not description.get("TableArn", "").startswith(expected_prefix) or description.get("TableName") != table_name:
        raise ValueError("DynamoDB table does not belong to the reviewed account")
    counts: Counter[str] = Counter({name: 0 for name in COUNTS})
    plaid_connection_ids: set[str] = set()
    dependency_candidates: list[dict] = []
    paginator = table.get_paginator("scan")
    for page in paginator.paginate(
        TableName=table_name, ConsistentRead=True,
        ProjectionExpression="#entity,#provider,eventType,#id,toolIds,requiredToolIds,#trigger.#connectionId",
        ExpressionAttributeNames={
            "#entity": "entity", "#provider": "provider", "#id": "id",
            "#trigger": "trigger", "#connectionId": "connectionId",
        },
    ):
        for item in page.get("Items", []):
            entity = item.get("entity", {}).get("S")
            provider = item.get("provider", {}).get("S")
            if entity == "STRIPE_EVENT":
                counts["stripe_markers"] += 1
            elif entity == "BILLING" and provider == "stripe":
                counts["stripe_billing"] += 1
            elif entity == "GITHUB_ROUTINE_SUBSCRIPTION":
                counts["github_subscription_indexes"] += 1
            elif entity == "GROUP_MESSAGE" and item.get("eventType", {}).get("S") == "github.issue.opened":
                counts["github_group_messages"] += 1
            elif entity == "PLAID_ITEM_MAPPING":
                counts["plaid_item_mappings"] += 1
            elif entity == "PLAID_SYNC":
                counts["plaid_sync_rows"] += 1
            elif entity == "CONNECTION" and provider == "plaid":
                counts["plaid_connections"] += 1
                connection_id = item.get("id", {}).get("S")
                if isinstance(connection_id, str):
                    plaid_connection_ids.add(connection_id)
            if "toolIds" in item or "requiredToolIds" in item or "trigger" in item:
                dependency_candidates.append(item)
    referencing_items = 0
    routine_trigger_items = 0
    references_by_entity: Counter[str] = Counter()
    for item in dependency_candidates:
        linked = {
            entry.get("S") for field in ("toolIds", "requiredToolIds")
            for entry in item.get(field, {}).get("L", []) if isinstance(entry, dict)
        }
        trigger_id = item.get("trigger", {}).get("M", {}).get("connectionId", {}).get("S")
        if plaid_connection_ids.intersection(linked) or trigger_id in plaid_connection_ids:
            referencing_items += 1
            references_by_entity[item.get("entity", {}).get("S", "UNKNOWN")] += 1
            if trigger_id in plaid_connection_ids:
                routine_trigger_items += 1
    checks: dict[str, list[dict[str, Any]]] = {name: [] for name in IDENTITY_FIELDS}
    for value in identities["stripeEvents"]:
        item = _get(table, table_name, "SYSTEM#STRIPE_EVENT", f"EVENT#{value['id']}",
                    ("entity", "eventType"))
        checks["stripeEvents"].append({"markerPresent": item.get("entity", {}).get("S") == "STRIPE_EVENT"})
    for value in identities["stripeBilling"]:
        item = _get(table, table_name, f"USER#{value['userId']}", "BILLING",
                    ("entity", "provider", "stripeEventId"))
        checks["stripeBilling"].append({"billingPresent": item.get("entity", {}).get("S") == "BILLING" and item.get("provider", {}).get("S") == "stripe"})
    for value in identities["githubIndexes"]:
        count = _query_index(table, table_name, f"GITHUB_EVENT#{value['installationId']}#{value['repositoryId']}")
        checks["githubIndexes"].append({"subscriptionCount": count})
    for value in identities["githubMessages"]:
        count = _query_message(table, table_name, value["groupId"], value["deliveryId"], value["routineId"])
        checks["githubMessages"].append({"matchingMessageCount": count})
    for value in identities["plaidItems"]:
        if value["environment"] not in {"sandbox", "production"}:
            raise ValueError("Plaid environment is invalid")
        item = _get(table, table_name, f"PLAID_ITEM#{value['environment']}#{value['itemId']}", "CONNECTION",
                    ("entity", "userId", "connectionId"))
        checks["plaidItems"].append({"mappingPresent": item.get("entity", {}).get("S") == "PLAID_ITEM_MAPPING"})
    for value in identities["plaidSync"]:
        item = _get(table, table_name, f"USER#{value['userId']}", f"PLAID_SYNC#{value['connectionId']}",
                    ("entity", "status", "revision", "webhookConfigured"))
        checks["plaidSync"].append({
            "syncPresent": item.get("entity", {}).get("S") == "PLAID_SYNC",
            "status": item.get("status", {}).get("S", "UNKNOWN") if item else "ABSENT",
            "revision": int(item.get("revision", {}).get("N", "-1")) if item else -1,
            "webhookConfigured": item.get("webhookConfigured", {}).get("BOOL") is True if item else False,
        })
    queue: dict[str, int] | None = None
    if jobs_queue_url:
        sqs = session.client("sqs", config=Config(retries={"total_max_attempts": 3, "mode": "standard"}))
        attributes = sqs.get_queue_attributes(
            QueueUrl=jobs_queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesDelayed", "ApproximateNumberOfMessagesNotVisible", "QueueArn"],
        )["Attributes"]
        if f":{account}:" not in attributes.get("QueueArn", ""):
            raise ValueError("SQS queue does not belong to the reviewed account")
        queue = {
            "visibleApproximate": int(attributes.get("ApproximateNumberOfMessages", "-1")),
            "delayedApproximate": int(attributes.get("ApproximateNumberOfMessagesDelayed", "-1")),
            "inFlightApproximate": int(attributes.get("ApproximateNumberOfMessagesNotVisible", "-1")),
        }
    return {
        "status": "INVENTORY_ONLY", "observedAtUTC": datetime.now(UTC).isoformat(),
        "account": account, "region": REGION, "tableItemCountApproximate": description.get("ItemCount", -1),
        "projectedCounts": dict(counts),
        "plaidConnectionReferences": {
            "referencingItems": referencing_items,
            "routineTriggerItems": routine_trigger_items,
            "byEntity": dict(references_by_entity),
        },
        "exactChecks": checks, "jobsQueue": queue,
        "note": "Read-only metadata projection. Scan is not a point-in-time snapshot; queue counts are approximate. No provider delivery listing or job identity is proved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True, choices=sorted(ALLOWED_ACCOUNTS))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--identities-file", type=Path)
    parser.add_argument("--jobs-queue-url")
    args = parser.parse_args()
    try:
        identities = _private_identities(args.identities_file)
        session = boto3.Session(profile_name=args.profile, region_name=REGION)
        print(json.dumps(inventory(session, args.account, args.table, identities, args.jobs_queue_url), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, BotoCoreError, ClientError, json.JSONDecodeError) as exc:
        # Avoid echoing errors that may contain table keys or resource identifiers.
        print(f"Provider inventory failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
