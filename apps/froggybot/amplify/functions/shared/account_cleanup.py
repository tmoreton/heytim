from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr

from shared.cleanup import delete_share_record, purge_group
from shared.keys import group_pk, push_owner_key, user_pk, user_state_key
from shared.memory_cleanup import delete_group_memory, delete_user_memory
from shared.memory_identity import direct_session_id, memory_actor_id, scoped_session_id
from shared.schedules import delete_remote_schedule
from shared.storage import delete_object_versions


@dataclass(frozen=True)
class AccountCleanupConfig:
    user_pool_id: str
    schedule_group_name: str
    agent_runtime_arn: str | None
    agent_runtime_qualifier: str
    memory_id: str | None
    files_bucket_name: str | None


class AccountCleanupService:
    """Restart-safe application cleanup used by the account deletion worker."""

    def __init__(
        self,
        *,
        table: Any,
        invite_access_table: Any,
        catalog: Any,
        agentcore: Any,
        cognito: Any,
        scheduler: Any,
        s3: Any,
        config: AccountCleanupConfig,
        now: Callable[[], str],
    ) -> None:
        self.table = table
        self.invite_access_table = invite_access_table
        self.catalog = catalog
        self.agentcore = agentcore
        self.cognito = cognito
        self.scheduler = scheduler
        self.s3 = s3
        self.config = config
        self.now = now

    def partition_items(
        self, partition_key: str, sort_prefix: str | None = None
    ) -> list[dict]:
        expression = "pk = :pk"
        values = {":pk": partition_key}
        if sort_prefix is not None:
            expression += " AND begins_with(sk, :prefix)"
            values[":prefix"] = sort_prefix
        request: dict[str, Any] = {
            "KeyConditionExpression": expression,
            "ExpressionAttributeValues": values,
            "ConsistentRead": True,
        }
        items = []
        while True:
            response = self.table.query(**request)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            request["ExclusiveStartKey"] = last_key

    def scan_items(self, filter_expression: Any) -> list[dict]:
        items = []
        request: dict[str, Any] = {"FilterExpression": filter_expression}
        while True:
            response = self.table.scan(**request)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            request["ExclusiveStartKey"] = last_key

    def remove_owned_skills(self, user_id: str, user_items: list[dict]) -> int:
        owned_skill_ids = {
            item["id"]
            for item in user_items
            if item.get("entity") == "USER_SKILL"
            and item.get("source") == "user"
            and item.get("ownerId") == user_id
            and item.get("relationship") == "owner"
            and isinstance(item.get("id"), str)
        }
        for skill_id in owned_skill_ids:
            listings = self.scan_items(
                Attr("entity").eq("USER_SKILL") & Attr("id").eq(skill_id)
            )
            bots = self.scan_items(
                Attr("entity").eq("BOT") & Attr("skillIds").contains(skill_id)
            )
            versions = self.partition_items(f"SKILL#{skill_id}")
            with self.table.batch_writer() as batch:
                for bot in bots:
                    skill_ids = [
                        value for value in bot.get("skillIds", []) if value != skill_id
                    ]
                    skill_versions = dict(bot.get("skillVersions", {}))
                    skill_versions.pop(skill_id, None)
                    batch.put_item(
                        Item={
                            **bot,
                            "skillIds": skill_ids,
                            "skillVersions": skill_versions,
                            "updatedAt": self.now(),
                        }
                    )
                for listing in listings:
                    batch.delete_item(Key={"pk": listing["pk"], "sk": listing["sk"]})
                for version in versions:
                    batch.delete_item(Key={"pk": version["pk"], "sk": version["sk"]})
        return len(owned_skill_ids)

    def remove_invite_access_for_user(self, user_id: str) -> None:
        request: dict[str, Any] = {"FilterExpression": Attr("createdBy").eq(user_id)}
        while True:
            response = self.invite_access_table.scan(**request)
            with self.invite_access_table.batch_writer() as batch:
                for item in response.get("Items", []):
                    token_hash = item.get("tokenHash")
                    if isinstance(token_hash, str):
                        batch.delete_item(Key={"tokenHash": token_hash})
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return
            request["ExclusiveStartKey"] = last_key

    @staticmethod
    def owned_agent_session_ids(
        user_id: str, user_items: list[dict], group_items: dict[str, list[dict]]
    ) -> set[str]:
        session_ids = {
            direct_session_id(user_id, item["id"])
            for item in user_items
            if item.get("entity") == "BOT" and isinstance(item.get("id"), str)
        }
        for group_id, items in group_items.items():
            for item in items:
                bot_id = item.get("botId")
                if (
                    item.get("entity") == "GROUP_BOT"
                    and item.get("botOwnerId") == user_id
                    and isinstance(bot_id, str)
                ):
                    session_ids.add(
                        scoped_session_id(f"group:{group_id}:bot:{bot_id}")
                    )
        return session_ids

    def stop_runtime_sessions(self, session_ids: set[str]) -> None:
        if not self.config.agent_runtime_arn:
            return
        for session_id in session_ids:
            try:
                self.agentcore.stop_runtime_session(
                    agentRuntimeArn=self.config.agent_runtime_arn,
                    qualifier=self.config.agent_runtime_qualifier,
                    runtimeSessionId=session_id,
                )
            except self.agentcore.exceptions.ResourceNotFoundException:
                continue

    def ready_tool_sessions(
        self, operation: str, identifier_key: str, identifier: str
    ) -> list[dict]:
        items = []
        request = {identifier_key: identifier, "status": "READY", "maxResults": 100}
        while True:
            response = getattr(self.agentcore, operation)(**request)
            items.extend(response.get("items", []))
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                return items
            request["nextToken"] = next_token

    def stop_tool_sessions(self, session_ids: set[str]) -> None:
        names = {f"frogbot-{session_id}" for session_id in session_ids}
        if not names:
            return
        for item in self.ready_tool_sessions(
            "list_code_interpreter_sessions",
            "codeInterpreterIdentifier",
            "aws.codeinterpreter.v1",
        ):
            if item.get("name") in names and isinstance(item.get("sessionId"), str):
                self.agentcore.stop_code_interpreter_session(
                    codeInterpreterIdentifier="aws.codeinterpreter.v1",
                    sessionId=item["sessionId"],
                )
        for item in self.ready_tool_sessions(
            "list_browser_sessions", "browserIdentifier", "aws.browser.v1"
        ):
            if item.get("name") in names and isinstance(item.get("sessionId"), str):
                self.agentcore.stop_browser_session(
                    browserIdentifier="aws.browser.v1",
                    sessionId=item["sessionId"],
                )

    def delete_user_files(self, user_id: str) -> int:
        if not self.config.files_bucket_name:
            return 0
        return delete_object_versions(
            self.s3,
            self.config.files_bucket_name,
            f"users/{memory_actor_id(user_id)}/",
            resource_label="user file",
        )

    def owned_share_records(self, user_id: str) -> list[dict]:
        return self.scan_items(
            Attr("entity").is_in(["SHARE", "SKILL_SHARE", "GROUP_INVITE"])
            & (Attr("ownerId").eq(user_id) | Attr("createdBy").eq(user_id))
        )

    def record_phase(self, user_id: str, phase: str) -> None:
        self.table.update_item(
            Key=user_state_key(user_id),
            UpdateExpression="SET deletionPhase = :phase, deletionUpdatedAt = :now",
            ConditionExpression="accountStatus = :deleting",
            ExpressionAttributeValues={
                ":phase": phase,
                ":now": self.now(),
                ":deleting": "DELETING",
            },
        )

    def _delete_groups(
        self,
        user_id: str,
        group_ids: set[str],
        group_items_by_id: dict[str, list[dict]],
    ) -> None:
        for group_id in group_ids:
            group_items = group_items_by_id[group_id]
            meta = next(
                (item for item in group_items if item.get("entity") == "GROUP"), None
            )
            if meta and meta.get("ownerId") == user_id:
                delete_group_memory(self.agentcore, self.config.memory_id, group_id)
                purge_group(
                    self.table,
                    self.invite_access_table,
                    self.s3,
                    self.config.files_bucket_name,
                    group_id,
                    group_items,
                )
                continue
            with self.table.batch_writer() as batch:
                for group_item in group_items:
                    authored_message = (
                        group_item.get("entity") == "GROUP_MESSAGE"
                        and group_item.get("authorType") == "user"
                        and group_item.get("authorId") == user_id
                    )
                    owned_bot_data = group_item.get("botOwnerId") == user_id
                    if authored_message or owned_bot_data:
                        batch.delete_item(
                            Key={"pk": group_item["pk"], "sk": group_item["sk"]}
                        )
                batch.delete_item(
                    Key={"pk": group_pk(group_id), "sk": f"USER#{user_id}"}
                )
                batch.delete_item(
                    Key={"pk": user_pk(user_id), "sk": f"GROUP#{group_id}"}
                )

    def delete_account(self, user_id: str, username: str) -> dict:
        self.table.update_item(
            Key=user_state_key(user_id),
            UpdateExpression=(
                "SET entity = :entity, accountStatus = :status, "
                "deletionStartedAt = if_not_exists(deletionStartedAt, :now)"
            ),
            ExpressionAttributeValues={
                ":entity": "USER_STATE",
                ":status": "DELETING",
                ":now": self.now(),
            },
        )
        user_items = self.partition_items(user_pk(user_id))
        group_ids = {
            item["groupId"]
            for item in user_items
            if item.get("entity") == "USER_GROUP"
            and isinstance(item.get("groupId"), str)
        }
        group_items_by_id = {
            group_id: self.partition_items(group_pk(group_id))
            for group_id in group_ids
        }
        session_ids = self.owned_agent_session_ids(
            user_id, user_items, group_items_by_id
        )

        self.record_phase(user_id, "SESSIONS")
        self.stop_runtime_sessions(session_ids)
        self.stop_tool_sessions(session_ids)
        self.record_phase(user_id, "SCHEDULES")
        for item in user_items:
            if item.get("entity") == "SCHEDULE":
                delete_remote_schedule(
                    self.scheduler, self.config.schedule_group_name, item
                )

        self.record_phase(user_id, "GROUPS")
        self._delete_groups(user_id, group_ids, group_items_by_id)

        self.record_phase(user_id, "SHARES_AND_LIBRARY")
        for share in self.owned_share_records(user_id):
            delete_share_record(
                self.table, self.invite_access_table, user_id, share
            )
        self.remove_invite_access_for_user(user_id)
        deleted_skills = self.remove_owned_skills(user_id, user_items)
        deleted_connections = self.catalog.delete_connection_secrets(user_items)
        deleted_memory = delete_user_memory(
            self.agentcore, self.config.memory_id, user_id
        )
        deleted_files = self.delete_user_files(user_id)

        self.record_phase(user_id, "USER_DATA")
        push_items = [
            item for item in user_items if item.get("entity") == "PUSH_TOKEN"
        ]
        chat_items = self.scan_items(Attr("pk").begins_with(f"CHAT#{user_id}#"))
        with self.table.batch_writer() as batch:
            for push_item in push_items:
                token_id = push_item.get("tokenId")
                if isinstance(token_id, str):
                    batch.delete_item(Key=push_owner_key(token_id))
            for item in chat_items:
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            for item in user_items:
                if item.get("sk") != "STATE":
                    batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

        self.record_phase(user_id, "IDENTITY")
        try:
            self.cognito.admin_user_global_sign_out(
                UserPoolId=self.config.user_pool_id, Username=username
            )
            self.cognito.admin_delete_user(
                UserPoolId=self.config.user_pool_id, Username=username
            )
        except self.cognito.exceptions.UserNotFoundException:
            pass

        self.table.put_item(
            Item={
                **user_state_key(user_id),
                "entity": "USER_STATE",
                "accountStatus": "DELETED",
                "deletedAt": self.now(),
                "expiresAt": int(datetime.now(UTC).timestamp()) + 2 * 24 * 60 * 60,
            }
        )
        return {
            "deleted": True,
            "deletedSkills": deleted_skills,
            "deletedConnections": deleted_connections,
            "deletedMemory": deleted_memory,
            "deletedFileVersions": deleted_files,
        }
