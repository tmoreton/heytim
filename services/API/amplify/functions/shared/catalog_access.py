from __future__ import annotations

import re
from typing import Any

from .catalog_rules import CatalogError


class CatalogAccessMixin:
    def validate_github_repository_access(
        self, user_id: str, tool_ids: list[str], access: Any
    ) -> dict[str, list[int]]:
        if not isinstance(access, dict):
            raise CatalogError("githubRepositoryAccess must be an object")
        if not access:
            return {}
        connections = {
            item["id"]: item
            for item in self._active_connection_items(user_id)
            if item.get("provider") == "github" and item.get("id") in tool_ids
        }
        result: dict[str, list[int]] = {}
        for connection_id, selected in access.items():
            if connection_id not in connections:
                raise CatalogError("GitHub repository access requires an assigned installation")
            installed = {
                repo.get("id")
                for repo in connections[connection_id].get("repositories", [])
                if isinstance(repo, dict)
            }
            if (
                not isinstance(selected, list)
                or not selected
                or len(selected) > 500
                or any(type(value) is not int for value in selected)
                or len(selected) != len(set(selected))
                or any(value not in installed for value in selected)
            ):
                raise CatalogError("Choose repositories from the connected GitHub installation")
            result[connection_id] = selected
        return result

    def validate_jira_project_access(
        self, user_id: str, tool_ids: list[str], access: Any
    ) -> dict[str, list[str]]:
        if not isinstance(access, dict):
            raise CatalogError("jiraProjectAccess must be an object")
        if not access:
            return {}
        connections = {
            item["id"]: item
            for item in self._active_connection_items(user_id)
            if item.get("provider") == "jira" and item.get("id") in tool_ids
        }
        result: dict[str, list[str]] = {}
        for connection_id, projects in access.items():
            if connection_id not in connections:
                raise CatalogError("Jira project access requires an assigned site")
            if (
                not isinstance(projects, list)
                or not 1 <= len(projects) <= 100
                or any(
                    not isinstance(key, str)
                    or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", key)
                    for key in projects
                )
                or len(projects) != len(set(projects))
            ):
                raise CatalogError("Enter valid Jira project keys")
            result[connection_id] = projects
        return result

    def validate_teams_channel_access(
        self, user_id: str, tool_ids: list[str], access: Any
    ) -> dict[str, list[str]]:
        if not isinstance(access, dict):
            raise CatalogError("teamsChannelAccess must be an object")
        if not access:
            return {}
        connections = {
            item["id"] for item in self._active_connection_items(user_id)
            if item.get("provider") == "microsoft_teams" and item.get("id") in tool_ids
        }
        pattern = re.compile(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/[A-Za-z0-9:_@.\-]{5,200}"
        )
        result = {}
        for connection_id, channels in access.items():
            if connection_id not in connections:
                raise CatalogError("Teams channel access requires an assigned connection")
            if (
                not isinstance(channels, list)
                or not 1 <= len(channels) <= 100
                or any(not isinstance(value, str) or not pattern.fullmatch(value) for value in channels)
                or len(channels) != len(set(channels))
            ):
                raise CatalogError("Enter valid Teams team/channel IDs")
            result[connection_id] = channels
        return result

    def validate_resource_access(
        self, user_id: str, tool_ids: list[str], access: Any
    ) -> dict[str, list[str]]:
        if not isinstance(access, dict):
            raise CatalogError("resourceAccess must be an object")
        if not access:
            return {}
        connections = {
            item["id"]: item
            for item in self._active_connection_items(user_id)
            if item.get("id") in tool_ids
            and item.get("provider") in {
                "slack", "notion", "google_workspace", "plaid"
            }
        }
        patterns = {
            "slack": re.compile(r"[A-Z0-9]{2,32}"),
            "notion": re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
            "google_workspace": re.compile(
                r"(?:file|sheet):[A-Za-z0-9_-]{8,256}|calendar:[A-Za-z0-9_.@%+\-]{1,256}"
            ),
            "plaid": re.compile(r"[A-Za-z0-9_-]{8,200}"),
        }
        result = {}
        for connection_id, resource_ids in access.items():
            connection = connections.get(connection_id)
            if connection is None:
                raise CatalogError("Resource access requires an assigned connection")
            provider = connection.get("provider")
            if (
                not isinstance(resource_ids, list)
                or not 1 <= len(resource_ids) <= 100
                or any(
                    not isinstance(value, str)
                    or not patterns[provider].fullmatch(value)
                    for value in resource_ids
                )
                or len(resource_ids) != len(set(resource_ids))
            ):
                raise CatalogError("Enter valid resource IDs")
            if provider == "plaid":
                available = {
                    account.get("id")
                    for account in connection.get("plaidAccounts", [])
                    if isinstance(account, dict)
                }
                if not available or any(item not in available for item in resource_ids):
                    raise CatalogError(
                        "Choose accounts from the connected Plaid institution"
                    )
            result[connection_id] = resource_ids
        return result

    def apply_resource_access(
        self, item: dict, runtime: dict, resource_ids: list[str]
    ) -> dict | None:
        if not resource_ids:
            return None
        if item.get("provider") != "plaid":
            runtime["resourceIds"] = resource_ids
            return runtime
        available = {
            account.get("id")
            for account in item.get("plaidAccounts", [])
            if isinstance(account, dict)
        }
        allowed = [account_id for account_id in resource_ids if account_id in available]
        if not allowed:
            return None
        runtime["accountIds"] = allowed
        return runtime
