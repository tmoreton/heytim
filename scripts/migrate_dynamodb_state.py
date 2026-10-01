#!/usr/bin/env python3
"""Plan and migrate the production application table across AWS accounts.

Dry run is the default. Customer records are held in memory and never printed or
written to a local manifest. Apply requires an unchanged source snapshot, an
explicit plan digest, and the guarded cutover environment flag.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import _connection_reconnect_plan as reconnect
from _mail_alias_plan import legacy_mail_address, mail_alias_key

SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
SOURCE_OUTPUTS = Path(__file__).resolve().parents[1] / "services/API/amplify_outputs.source-rollback.json"
DESTINATION_OUTPUTS = Path(__file__).resolve().parents[1] / (
    "services/API/amplify_outputs.production-candidate.json"
)
ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
BOT_EMAIL_FIELDS = ("emailToken", "emailInboundMode", "emailDeliveryMode", "emailOwnerAddress")
MAIL_TOKEN_PATTERN = re.compile(r"^[a-z2-7]{16}$")


class MigrationError(RuntimeError):
    """A fail-closed cutover precondition failed."""


def digest(value: Any) -> str:
    def normalize(part: Any) -> Any:
        if isinstance(part, Decimal):
            return {"decimal": str(part)}
        if isinstance(part, (bytes, bytearray)):
            return {"base64": base64.b64encode(bytes(part)).decode("ascii")}
        if isinstance(part, dict):
            return {str(key): normalize(item) for key, item in sorted(part.items())}
        if isinstance(part, (list, tuple)):
            return [normalize(item) for item in part]
        if isinstance(part, set):
            return sorted(
                (normalize(item) for item in part),
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        return part

    encoded = json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def table_digest(items: list[dict]) -> str:
    ordered = sorted(items, key=lambda item: (item["pk"], item["sk"]))
    return digest(ordered)


def actor_id(user_id: str) -> str:
    return hashlib.sha256(f"user:{user_id}".encode()).hexdigest()


def direct_session_id(user_id: str, bot_id: str) -> str:
    return hashlib.sha256(f"{user_id}:{bot_id}".encode()).hexdigest()


def schedule_name(user_id: str, schedule_id: str) -> str:
    return (
        "heytim-" + hashlib.sha256(f"{user_id}:{schedule_id}".encode()).hexdigest()[:40]
    )


def record_class(item: dict) -> str:
    pk, sk = item.get("pk"), item.get("sk")
    if not isinstance(pk, str) or not isinstance(sk, str):
        raise MigrationError("A source record is missing string pk/sk")
    return f"{pk.split('#', 1)[0]}/{sk.split('#', 1)[0]}"


def exclusion_reason(item: dict) -> str | None:
    pk, sk = item["pk"], item["sk"]
    if item.get("entity") == "OAUTH_STATE" or pk.startswith("OAUTH#"):
        return "unfinished-oauth-authorization"
    if item.get("entity") == "PLAID_ITEM_MAPPING" or pk.startswith("PLAID_ITEM#"):
        return "plaid-provider-mapping"
    if pk.startswith("PUSH_TOKEN#") or sk.startswith("PUSH#"):
        return "push-token-or-endpoint"
    if sk.startswith("DEVICE#"):
        return "device-registration"
    if sk.startswith("CONNECTION#"):
        return "provider-connection"
    return None


def bot_ids_for_user(items: list[dict], user_id: str) -> set[str]:
    bot_ids: set[str] = set()
    for item in items:
        pk, sk = item["pk"], item["sk"]
        if pk == f"USER#{user_id}" and sk.startswith("BOT#"):
            bot_ids.add(sk.split("#", 1)[1])
        if pk.startswith(f"CHAT#{user_id}#"):
            bot_ids.add(pk.split("#", 2)[2])
    if not bot_ids or any(not bot_id for bot_id in bot_ids):
        raise MigrationError("Could not derive complete direct-chat bot IDs")
    return bot_ids


def assert_owned_user_partitions(items: list[dict], user_id: str) -> None:
    """Do not copy records belonging to a user without a destination identity."""
    user_pk = f"USER#{user_id}"
    chat_prefix = f"CHAT#{user_id}#"
    for item in items:
        pk, sk = item["pk"], item["sk"]
        if pk.startswith("USER#") and pk != user_pk:
            raise MigrationError("A user partition has no reviewed Cognito mapping")
        if pk.startswith("CHAT#") and not pk.startswith(chat_prefix):
            raise MigrationError("A chat owner has no reviewed Cognito mapping")
        if pk.startswith("GROUP#") and sk.startswith("USER#") and sk != user_pk:
            raise MigrationError("A group member has no reviewed Cognito mapping")


@dataclass(frozen=True)
class Identity:
    old_sub: str
    new_sub: str
    old_actor: str
    new_actor: str
    direct_sessions: dict[str, str]

    @classmethod
    def build(cls, old_sub: str, new_sub: str, bot_ids: set[str]) -> Identity:
        if not UUID_PATTERN.fullmatch(old_sub) or not UUID_PATTERN.fullmatch(new_sub):
            raise MigrationError("Cognito subject has an unexpected format")
        if old_sub == new_sub:
            raise MigrationError("Source and destination Cognito subjects must differ")
        return cls(
            old_sub,
            new_sub,
            actor_id(old_sub),
            actor_id(new_sub),
            {
                direct_session_id(old_sub, bot): direct_session_id(new_sub, bot)
                for bot in bot_ids
            },
        )


def replace_identity_string(value: str, identity: Identity) -> str:
    result = value.replace(identity.old_actor, identity.new_actor)
    for old_session, new_session in identity.direct_sessions.items():
        result = result.replace(old_session, new_session)
    # Cognito UUIDs appear inside PKs, ownership fields, and some serialized
    # references. Boundaries avoid changing unrelated free-form identifiers.
    boundary = r"(?<![0-9a-f-])" + re.escape(identity.old_sub) + r"(?![0-9a-f-])"
    return re.sub(boundary, identity.new_sub, result)


def replace_identity(value: Any, identity: Identity) -> Any:
    if isinstance(value, str):
        return replace_identity_string(value, identity)
    if isinstance(value, dict):
        return {key: replace_identity(item, identity) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_identity(item, identity) for item in value]
    if isinstance(value, set):
        transformed = {replace_identity(item, identity) for item in value}
        if len(transformed) != len(value):
            raise MigrationError("Identity remap would collapse a DynamoDB set")
        return transformed
    return value


def contains_old_identity(value: Any, identity: Identity) -> bool:
    if isinstance(value, str):
        return (
            identity.old_sub in value
            or identity.old_actor in value
            or any(old in value for old in identity.direct_sessions)
        )
    if isinstance(value, dict):
        return any(contains_old_identity(item, identity) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_old_identity(item, identity) for item in value)
    return False


def make_plan(source_items: list[dict], identity: Identity) -> tuple[list[dict], dict]:
    assert_owned_user_partitions(source_items, identity.old_sub)
    excluded_connections = reconnect.excluded_connection_ids(source_items)
    planned: list[dict] = []
    exclusions: Counter[str] = Counter()
    reconnect_repairs: Counter[str] = Counter()
    stripped_email = 0
    preserved_email = 0
    aliases: list[dict] = []
    paused_schedules = 0
    billing_rows = 0
    old_account_references = 0
    cancelled_pending_work_removed = 0
    keys: set[tuple[str, str]] = set()
    for original in source_items:
        category = record_class(original)
        reason = exclusion_reason(original)
        if reason:
            exclusions[reason] += 1
            continue
        item = replace_identity(original, identity)
        removed = reconnect.remove_excluded_connection_references(
            item, category, excluded_connections
        )
        if removed:
            reconnect_repairs.update({"bots": 1, "bindings": removed})
        if category == "USER/BOT":
            token = item.get("emailToken")
            if token:
                bot_id = item.get("id")
                if (
                    not isinstance(token, str)
                    or not MAIL_TOKEN_PATTERN.fullmatch(token)
                    or not isinstance(bot_id, str)
                    or not bot_id
                    or item.get("sk") != f"BOT#{bot_id}"
                ):
                    raise MigrationError("An active bot email route is malformed")
                address = legacy_mail_address(identity.old_sub, bot_id, token)
                item["legacyEmailAddress"] = address
                aliases.append(
                    {
                        **mail_alias_key(address),
                        "entity": "MAIL_ALIAS",
                        "address": address,
                        "targetUserId": identity.new_sub,
                        "targetBotId": bot_id,
                    }
                )
                preserved_email += 1
            elif any(field in item for field in BOT_EMAIL_FIELDS):
                stripped_email += 1
                for field in BOT_EMAIL_FIELDS:
                    item.pop(field, None)
        if category == "USER/SCHEDULE":
            schedule_id = item.get("id")
            if not isinstance(schedule_id, str) or not schedule_id:
                raise MigrationError("A schedule has no ID")
            item["schedulerName"] = schedule_name(identity.new_sub, schedule_id)
            item["enabled"] = False
            paused_schedules += 1
        if category == "USER/BILLING":
            billing_rows += 1
        if (
            category == "CHAT/TURN"
            and item.get("status") == "CANCELLED"
            and "pendingWork" in item
        ):
            # A cancelled turn cannot be resumed. Its stale source AgentCore
            # resource ARN must not become live state in the new account.
            item.pop("pendingWork")
            cancelled_pending_work_removed += 1
        if contains_old_identity(item, identity):
            raise MigrationError(f"Unmapped source identity remains in {category}")
        if SOURCE_ACCOUNT in json.dumps(item, default=str):
            if category != "CHAT/TURN" or item.get("status") not in {
                "COMPLETE",
                "ERROR",
                "CANCELLED",
            }:
                raise MigrationError(
                    f"Live source account reference remains in {category}"
                )
            old_account_references += 1
        key = (item["pk"], item["sk"])
        if key in keys:
            raise MigrationError("Identity remap produced a duplicate DynamoDB key")
        keys.add(key)
        planned.append(item)
    if len(planned) + sum(exclusions.values()) != len(source_items):
        raise MigrationError(
            "The migration plan does not account for every source item"
        )
    for alias in aliases:
        key = (alias["pk"], alias["sk"])
        if key in keys:
            raise MigrationError("A bot mail alias collides with existing state")
        keys.add(key)
        planned.append(alias)
    return planned, {
        "sourceItems": len(source_items),
        "plannedItems": len(planned),
        "excluded": dict(sorted(exclusions.items())),
        "connectionReconnectRepairs": dict(sorted(reconnect_repairs.items())),
        "botEmailTokensRemoved": stripped_email,
        "botEmailTokensPreserved": preserved_email,
        "mailAliasesCreated": len(aliases),
        "schedulesPaused": paused_schedules,
        "billingRowsRequiringReconciliation": billing_rows,
        "cancelledTurnPendingWorkRemoved": cancelled_pending_work_removed,
        "historicalTurnRowsWithSourceAccountReferences": old_account_references,
        "directSessionMappings": len(identity.direct_sessions),
        "sourceDigest": table_digest(source_items),
        "plannedDigest": table_digest(planned),
    }


def load_outputs(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("custom", {}).get("environment") != "production":
        raise MigrationError("An Amplify output is not production")
    if not all(
        data.get("custom", {}).get(key)
        for key in ("dataTableName", "inviteTableName", "filesBucketName")
    ):
        raise MigrationError("An Amplify output is missing storage identifiers")
    if not data.get("auth", {}).get("user_pool_id"):
        raise MigrationError("An Amplify output is missing the Cognito pool")
    return data


def assert_identity(session: Any, expected: str) -> None:
    actual = session.client("sts").get_caller_identity()["Account"]
    if actual != expected:
        raise MigrationError(f"AWS profile is in account {actual}; expected {expected}")


def pool_users(client: Any, pool_id: str) -> list[dict]:
    return [
        user
        for page in client.get_paginator("list_users").paginate(UserPoolId=pool_id)
        for user in page.get("Users", [])
    ]


def attributes(user: dict) -> dict[str, str]:
    return {item["Name"]: item["Value"] for item in user.get("Attributes", [])}


def match_cognito_identity(
    source: Any, destination: Any, source_pool: str, destination_pool: str
) -> tuple[str, str]:
    originals = pool_users(source, source_pool)
    if len(originals) != 1:
        raise MigrationError(
            "Expected exactly one source Cognito user; review identity mapping"
        )
    old_user = originals[0]
    old = attributes(old_user)
    if old_user.get("UserStatus") != "CONFIRMED" or old.get("email_verified") != "true":
        raise MigrationError(
            "Source Cognito identity is not confirmed with verified email"
        )
    email = old.get("email", "").strip().casefold()
    if not email:
        raise MigrationError("Source Cognito identity has no email")
    matches = [
        user
        for user in pool_users(destination, destination_pool)
        if attributes(user).get("email", "").strip().casefold() == email
        and attributes(user).get("email_verified") == "true"
        and user.get("UserStatus") == "CONFIRMED"
    ]
    if len(matches) != 1:
        raise MigrationError(
            "Destination has no unique confirmed, verified matching identity"
        )
    return old["sub"], attributes(matches[0])["sub"]


def table_items(table: Any) -> list[dict]:
    client = table.meta.client
    result: list[dict] = []
    for page in client.get_paginator("scan").paginate(
        TableName=table.name,
        ConsistentRead=True,
        PaginationConfig={"PageSize": 100},
    ):
        result.extend(page.get("Items", []))
    return result


def assert_table(table: Any, expected_account: str) -> None:
    details = table.meta.client.describe_table(TableName=table.name)["Table"]
    if (
        details.get("TableStatus") != "ACTIVE"
        or f":{expected_account}:" not in details["TableArn"]
    ):
        raise MigrationError("Table is not ACTIVE in the expected account")
    keys = [(part["AttributeName"], part["KeyType"]) for part in details["KeySchema"]]
    if keys != [("pk", "HASH"), ("sk", "RANGE")]:
        raise MigrationError("Table key schema differs from the expected pk/sk layout")


def assert_empty_invite_tables(
    source: Any, destination: Any, source_name: str, destination_name: str
) -> None:
    for table in (source.Table(source_name), destination.Table(destination_name)):
        response = table.scan(Select="COUNT", ConsistentRead=True)
        if response.get("LastEvaluatedKey") or response.get("Count") != 0:
            raise MigrationError(
                "Invite table is not empty; this migration does not copy invite grants"
            )


def write_private_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.stat().st_mode & 0o077):
        raise MigrationError("Existing manifest has unsafe file permissions")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_destination(existing: list[dict], planned: list[dict]) -> int:
    wanted = {(item["pk"], item["sk"]): item for item in planned}
    if len(existing) > len(wanted):
        raise MigrationError("Destination has more rows than the migration plan")
    for item in existing:
        key = (item["pk"], item["sk"])
        if key not in wanted or digest(item) != digest(wanted[key]):
            raise MigrationError("Destination contains an unexpected or divergent item")
    return len(existing)


def apply_plan(table: Any, planned: list[dict], existing: list[dict]) -> int:
    present = {(item["pk"], item["sk"]) for item in existing}
    written = 0
    for item in planned:
        if (item["pk"], item["sk"]) in present:
            continue
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
        written += 1
    return written


def parser() -> argparse.ArgumentParser:
    argument = argparse.ArgumentParser(description=__doc__)
    argument.add_argument("--source-profile", required=True)
    argument.add_argument("--destination-profile", required=True)
    argument.add_argument("--source-account", default=SOURCE_ACCOUNT)
    argument.add_argument("--destination-account", default=DESTINATION_ACCOUNT)
    argument.add_argument("--region", default="us-east-1")
    argument.add_argument("--source-outputs", type=Path, default=SOURCE_OUTPUTS)
    argument.add_argument(
        "--destination-outputs", type=Path, default=DESTINATION_OUTPUTS
    )
    argument.add_argument("--manifest", type=Path, required=True)
    argument.add_argument(
        "--expected-plan-digest", help="Required on apply; copy from a reviewed dry run"
    )
    argument.add_argument("--apply", action="store_true")
    return argument


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not ACCOUNT_PATTERN.fullmatch(
            args.source_account
        ) or not ACCOUNT_PATTERN.fullmatch(args.destination_account):
            raise MigrationError("AWS account IDs must contain twelve digits")
        if (
            args.source_account != SOURCE_ACCOUNT
            or args.destination_account != DESTINATION_ACCOUNT
        ):
            raise MigrationError(
                "This reviewed migration is bound to the source and destination account IDs"
            )
        if (
            args.source_account == args.destination_account
            or args.source_profile == args.destination_profile
        ):
            raise MigrationError("Source and destination profiles/accounts must differ")
        if args.apply and (
            not args.expected_plan_digest
            or os.environ.get("HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED") != "true"
        ):
            raise MigrationError(
                "Apply requires the reviewed plan digest and cutover approval flag"
            )

        # Keep boto3 optional for pure planning tests and import it only here.
        import boto3
        from botocore.config import Config

        source_outputs = load_outputs(args.source_outputs)
        destination_outputs = load_outputs(args.destination_outputs)
        config = Config(
            retries={"mode": "adaptive", "total_max_attempts": 5},
            connect_timeout=5,
            read_timeout=60,
        )
        source_session = boto3.Session(
            profile_name=args.source_profile, region_name=args.region
        )
        destination_session = boto3.Session(
            profile_name=args.destination_profile, region_name=args.region
        )
        assert_identity(source_session, args.source_account)
        assert_identity(destination_session, args.destination_account)
        source_client = source_session.client("cognito-idp", config=config)
        destination_client = destination_session.client("cognito-idp", config=config)
        old_sub, new_sub = match_cognito_identity(
            source_client,
            destination_client,
            source_outputs["auth"]["user_pool_id"],
            destination_outputs["auth"]["user_pool_id"],
        )
        source_resource = source_session.resource("dynamodb", config=config)
        destination_resource = destination_session.resource("dynamodb", config=config)
        source_table = source_resource.Table(source_outputs["custom"]["dataTableName"])
        destination_table = destination_resource.Table(
            destination_outputs["custom"]["dataTableName"]
        )
        assert_table(source_table, args.source_account)
        assert_table(destination_table, args.destination_account)
        assert_empty_invite_tables(
            source_resource,
            destination_resource,
            source_outputs["custom"]["inviteTableName"],
            destination_outputs["custom"]["inviteTableName"],
        )
        originals = table_items(source_table)
        if not originals:
            raise MigrationError("Source table is empty")
        identity = Identity.build(
            old_sub, new_sub, bot_ids_for_user(originals, old_sub)
        )
        planned, summary = make_plan(originals, identity)
        existing = table_items(destination_table)
        summary["destinationItemsAlreadyMatching"] = verify_destination(
            existing, planned
        )
        summary["sourceAccount"] = args.source_account
        summary["destinationAccount"] = args.destination_account
        summary["sourceTable"] = source_table.name
        summary["destinationTable"] = destination_table.name
        summary["region"] = args.region
        summary["identityMap"] = (
            "unique verified Cognito email; subjects remapped in memory"
        )
        summary["sourceInviteItems"] = 0
        summary["destinationInviteItems"] = 0
        if not args.apply:
            write_private_manifest(args.manifest, summary)
            print(json.dumps({"mode": "dry-run", **summary}, sort_keys=True))
            return 0
        if args.expected_plan_digest != summary["plannedDigest"]:
            raise MigrationError(
                "Source or identity mapping changed since the reviewed dry run"
            )
        written = apply_plan(destination_table, planned, existing)
        if table_digest(table_items(source_table)) != summary["sourceDigest"]:
            raise MigrationError(
                "Source table changed during import; keep traffic on source"
            )
        after = table_items(destination_table)
        if (
            len(after) != len(planned)
            or table_digest(after) != summary["plannedDigest"]
        ):
            raise MigrationError(
                "Destination count or canonical digest differs from the plan"
            )
        write_private_manifest(args.manifest, summary)
        print(
            json.dumps(
                {"mode": "applied", "written": written, **summary}, sort_keys=True
            )
        )
        return 0
    except (MigrationError, OSError, ValueError, KeyError) as error:
        print(f"DynamoDB migration stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
