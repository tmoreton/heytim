"""Validate and pin the editable bot recipe."""
from __future__ import annotations

from shared.catalog import CatalogError
from shared.client_contract import (
    BOT_NAME_MAX_LENGTH,
    BOT_PROMPT_MAX_LENGTH,
    BOT_TAGLINE_MAX_LENGTH,
)

from .bot_roles import ALLOWED_COLORS, CHIEF_COLOR, CHIEF_SYSTEM_ROLE, DEFAULT_BOT_COLOR
from .support import ApiError, _validate_string, catalog


def _bot_values(
    user_id: str,
    value: dict,
    previous: dict | None = None,
    system_role: str | None = None,
) -> dict:
    previous = previous or {}
    role = system_role or previous.get("systemRole")
    color = value.get("color", previous.get("color", DEFAULT_BOT_COLOR))
    if role == CHIEF_SYSTEM_ROLE:
        color = CHIEF_COLOR
    elif color == CHIEF_COLOR:
        if "color" in value:
            raise ApiError(400, "FroggyBot green is reserved for Chief")
        color = DEFAULT_BOT_COLOR
    if color not in ALLOWED_COLORS:
        raise ApiError(400, "Choose one of the available bot colors")
    try:
        skill_ids = value.get("skillIds", previous.get("skillIds", []))
        skill_versions = catalog.validate_and_pin(
            user_id, skill_ids, previous.get("skillVersions")
        )
        required_tools = []
        for skill_id, version in skill_versions.items():
            skill = catalog.get_version(skill_id, version)
            if skill:
                required_tools.extend(skill.get("requiredToolIds", []))
        if "toolIds" in value:
            extra_tool_ids = catalog.validate_tools(user_id, value.get("toolIds"))
        elif isinstance(previous.get("extraToolIds"), list):
            extra_tool_ids = catalog.available_tool_ids(
                user_id, previous["extraToolIds"]
            )
        else:
            required_tool_set = set(required_tools)
            extra_tool_ids = catalog.available_tool_ids(
                user_id,
                [
                    tool_id
                    for tool_id in previous.get("toolIds", [])
                    if tool_id not in required_tool_set
                ],
            )
        tool_ids = catalog.validate_tools(user_id, [*extra_tool_ids, *required_tools])
        if "githubRepositoryAccess" in value:
            raw_github_access = value["githubRepositoryAccess"]
        else:
            previous_access = previous.get("githubRepositoryAccess", {})
            raw_github_access = {
                connection_id: repositories
                for connection_id, repositories in (
                    previous_access.items() if isinstance(previous_access, dict) else []
                )
                if connection_id in tool_ids
            }
        github_repository_access = catalog.validate_github_repository_access(
            user_id, tool_ids, raw_github_access
        )
        if "jiraProjectAccess" in value:
            raw_jira_access = value["jiraProjectAccess"]
        else:
            previous_jira_access = previous.get("jiraProjectAccess", {})
            raw_jira_access = {
                connection_id: projects
                for connection_id, projects in (
                    previous_jira_access.items()
                    if isinstance(previous_jira_access, dict) else []
                )
                if connection_id in tool_ids
            }
        jira_project_access = catalog.validate_jira_project_access(
            user_id, tool_ids, raw_jira_access
        )
        if "teamsChannelAccess" in value:
            raw_teams_access = value["teamsChannelAccess"]
        else:
            previous_teams_access = previous.get("teamsChannelAccess", {})
            raw_teams_access = {
                connection_id: channels
                for connection_id, channels in (
                    previous_teams_access.items()
                    if isinstance(previous_teams_access, dict) else []
                )
                if connection_id in tool_ids
            }
        teams_channel_access = catalog.validate_teams_channel_access(
            user_id, tool_ids, raw_teams_access
        )
        if "resourceAccess" in value:
            raw_resource_access = value["resourceAccess"]
        else:
            previous_resource_access = previous.get("resourceAccess", {})
            raw_resource_access = {
                connection_id: resources
                for connection_id, resources in (
                    previous_resource_access.items()
                    if isinstance(previous_resource_access, dict) else []
                )
                if connection_id in tool_ids
            }
        resource_access = catalog.validate_resource_access(
            user_id, tool_ids, raw_resource_access
        )
        raw_always_allowed = value.get(
            "alwaysAllowedToolIds", previous.get("alwaysAllowedToolIds", [])
        )
        if not isinstance(raw_always_allowed, list) or not all(
            isinstance(tool_id, str) for tool_id in raw_always_allowed
        ):
            raise ApiError(400, "alwaysAllowedToolIds must be a list")
        interactive_tool_ids = set(catalog.approval_tool_ids(user_id, tool_ids))
        raw_previously_allowed = previous.get("alwaysAllowedToolIds", [])
        previously_allowed = (
            set(raw_previously_allowed)
            if isinstance(raw_previously_allowed, list)
            and all(isinstance(tool_id, str) for tool_id in raw_previously_allowed)
            else set()
        )
        requested_always_allowed = set(raw_always_allowed) & previously_allowed
        always_allowed_tool_ids = [
            tool_id
            for tool_id in tool_ids
            if tool_id in requested_always_allowed and tool_id in interactive_tool_ids
        ]
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc
    return {
        "name": _validate_string(
            value.get("name", previous.get("name", "")), "name", BOT_NAME_MAX_LENGTH
        ),
        "tagline": _validate_string(
            value.get("tagline", previous.get("tagline", "")),
            "tagline",
            BOT_TAGLINE_MAX_LENGTH,
            required=False,
        ),
        "prompt": _validate_string(
            value.get("prompt", previous.get("prompt", "")), "prompt", BOT_PROMPT_MAX_LENGTH
        ),
        "color": color,
        "toolIds": tool_ids,
        "extraToolIds": extra_tool_ids,
        "alwaysAllowedToolIds": always_allowed_tool_ids,
        "githubRepositoryAccess": github_repository_access,
        "jiraProjectAccess": jira_project_access,
        "teamsChannelAccess": teams_channel_access,
        "resourceAccess": resource_access,
        "skillIds": list(skill_versions),
        "skillVersions": skill_versions,
    }
