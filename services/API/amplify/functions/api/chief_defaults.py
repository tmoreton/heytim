"""Additive, one-time Chief defaults without replacing a user's bot recipe."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from shared.catalog import CatalogError
from shared.client_contract import MAX_SKILLS_PER_BOT, MAX_TOOLS_PER_BOT

from .support import ApiError, _bot_sk, _now, _user_pk, catalog, table

CHIEF_DEFAULTS_VERSION = 9
CHIEF_BUILTIN_TOOL_IDS = frozenset({
    "web", "web_search", "calculator", "current_time", "bot_manager", "meme_lord",
    "image_generator", "task_list", "code_interpreter", "browser", "mac_computer", "mac_terminal",
})


def _ids(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(dict.fromkeys(value))


def upgrade_chief_defaults(user_id: str, bot: dict, bot_values: Callable[..., dict]) -> dict:
    """Merge published defaults once, preserving custom settings and later removals."""
    previous_version = bot.get("templateVersion")
    if (
        bot.get("systemRole") != "chief"
        or bot.get("templateId") != "chief"
        or isinstance(previous_version, bool)
        or not isinstance(previous_version, (int, Decimal))
        or previous_version != int(previous_version)
        or previous_version >= CHIEF_DEFAULTS_VERSION
    ):
        return bot
    old_tools = _ids(bot.get("toolIds"))
    old_skills = _ids(bot.get("skillIds"))
    old_extra = _ids(bot.get("extraToolIds", old_tools))
    if old_tools is None or old_skills is None or old_extra is None:
        return bot
    # A saved delegate or delegate-dependent custom skill cannot coexist with
    # interactive tools. Do not silently discard a user's selected capability.
    if "delegate" in old_tools:
        return bot
    try:
        template = catalog.get_bot_template("chief")
        if template.get("version", 0) < CHIEF_DEFAULTS_VERSION:
            return bot
        defaults = _ids(template.get("toolIds"))
        default_skills = _ids(template.get("skillIds"))
        if defaults is None or default_skills is None or set(defaults) != CHIEF_BUILTIN_TOOL_IDS:
            return bot
        extra = list(dict.fromkeys([*old_extra, *defaults]))
        skills = list(dict.fromkeys([*old_skills, *default_skills]))
        if len(extra) > MAX_TOOLS_PER_BOT or len(skills) > MAX_SKILLS_PER_BOT:
            return bot
        values = bot_values(user_id, {"toolIds": extra, "skillIds": skills}, previous=bot)
        if (
            "delegate" in values["toolIds"]
            or set(values["toolIds"]) - set(old_tools) - CHIEF_BUILTIN_TOOL_IDS
        ):
            # A newer/custom skill may require an integration. Defaults must
            # never create a new account grant on the user's behalf.
            return bot
    except (ApiError, CatalogError):
        # Backend and catalog publish independently. Preserve the saved recipe
        # until all reviewed tools and skills are available for this account.
        return bot
    changes = {key: values[key] for key in (
        "toolIds", "extraToolIds", "skillIds", "skillVersions", "alwaysAllowedToolIds",
    )}
    changes.update({"templateVersion": CHIEF_DEFAULTS_VERSION, "updatedAt": _now()})
    expression_values = {f":new_{key}": value for key, value in changes.items()}
    conditions = []
    for key in (
        "templateVersion", "toolIds", "extraToolIds", "skillIds", "skillVersions",
        "actionApprovalMode", "alwaysAllowedToolIds", "githubRepositoryAccess",
        "jiraProjectAccess", "teamsChannelAccess", "resourceAccess",
    ):
        if key in bot:
            conditions.append(f"{key} = :old_{key}")
            expression_values[f":old_{key}"] = bot[key]
        else:
            conditions.append(f"attribute_not_exists({key})")
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
            UpdateExpression="SET " + ", ".join(f"{key} = :new_{key}" for key in changes),
            ConditionExpression=" AND ".join(conditions),
            ExpressionAttributeValues=expression_values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return bot
    return {**bot, **changes}
