from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from shared.catalog import CatalogError
from shared.catalog_rules import MAX_SKILLS_PER_BOT

from .bot_roles import CHIEF_COLOR, CHIEF_SYSTEM_ROLE, CHIEF_TEMPLATE_ID
from .support import ApiError, _bot_sk, _now, _user_pk, catalog, table

LEGACY_BOT_TEMPLATE_IDS = {
    "starter-trip-planner": "trip-planner",
    "starter-event-planner": "event-planner",
    "starter-research-reports": "research-reports",
}
CHIEF_SKILL_BUILDER_ID = "skill-builder"
CHIEF_SKILL_BUILDER_TEMPLATE_VERSION = 5
CHIEF_SKILL_IMPORT_TEMPLATE_VERSION = 6
CHIEF_SKILL_IMPORT_SKILL_VERSION = 2


def _version_number(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    return int(value) if int(value) == value else None


def _add_chief_default_skill(user_id: str, bot: dict) -> dict:
    """Add or refresh Chief's default Skill Builder without undoing removal."""
    old_version = bot.get("templateVersion")
    old_version_number = _version_number(old_version)
    if bot.get("templateId") != CHIEF_TEMPLATE_ID:
        return bot
    if (
        old_version_number is not None
        and old_version_number >= CHIEF_SKILL_IMPORT_TEMPLATE_VERSION
    ):
        return bot
    old_skill_ids = bot.get("skillIds")
    if not isinstance(old_skill_ids, list) or any(
        not isinstance(skill_id, str) for skill_id in old_skill_ids
    ):
        return bot
    if (
        old_version_number is not None
        and old_version_number >= CHIEF_SKILL_BUILDER_TEMPLATE_VERSION
        and CHIEF_SKILL_BUILDER_ID not in old_skill_ids
    ):
        # The user removed the default after the initial migration.
        return bot
    if (
        CHIEF_SKILL_BUILDER_ID not in old_skill_ids
        and len(set(old_skill_ids)) >= MAX_SKILLS_PER_BOT
    ):
        return bot
    try:
        skill = catalog.get_skill(user_id, CHIEF_SKILL_BUILDER_ID)
    except CatalogError:
        # Backend code may deploy before the corresponding catalog publication.
        return bot
    skill_version = _version_number(skill.get("version"))
    if (
        skill.get("source") != "official"
        or skill_version is None
        or not catalog.get_version(CHIEF_SKILL_BUILDER_ID, skill_version)
    ):
        return bot
    target_template_version = (
        CHIEF_SKILL_IMPORT_TEMPLATE_VERSION
        if skill_version >= CHIEF_SKILL_IMPORT_SKILL_VERSION
        else CHIEF_SKILL_BUILDER_TEMPLATE_VERSION
    )
    if old_version_number is not None and old_version_number >= target_template_version:
        return bot
    skill_ids = list(dict.fromkeys([*old_skill_ids, CHIEF_SKILL_BUILDER_ID]))
    old_skill_versions = bot.get("skillVersions")
    skill_versions = (
        dict(old_skill_versions) if isinstance(old_skill_versions, dict) else {}
    )
    skill_versions[CHIEF_SKILL_BUILDER_ID] = skill_version
    expression_values = {
        ":previousSkillIds": old_skill_ids,
        ":skillIds": skill_ids,
        ":skillVersions": skill_versions,
        ":templateVersion": target_template_version,
        ":now": _now(),
    }
    condition = "skillIds = :previousSkillIds"
    if old_version_number is not None:
        condition += " AND templateVersion = :previousVersion"
        expression_values[":previousVersion"] = old_version_number
    else:
        condition += " AND attribute_not_exists(templateVersion)"
    if isinstance(old_skill_versions, dict):
        condition += " AND skillVersions = :previousSkillVersions"
        expression_values[":previousSkillVersions"] = old_skill_versions
    else:
        condition += " AND attribute_not_exists(skillVersions)"
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
            UpdateExpression=(
                "SET skillIds = :skillIds, skillVersions = :skillVersions, "
                "templateVersion = :templateVersion, updatedAt = :now"
            ),
            ConditionExpression=condition,
            ExpressionAttributeValues=expression_values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # A concurrent edit won; the next bootstrap can retry from fresh state.
        return bot
    return {
        **bot,
        "skillIds": skill_ids,
        "skillVersions": skill_versions,
        "templateVersion": target_template_version,
        "updatedAt": expression_values[":now"],
    }


def _required_chief_template() -> dict:
    try:
        return catalog.get_bot_template(CHIEF_TEMPLATE_ID)
    except CatalogError as exc:
        raise ApiError(
            503,
            "Chief is temporarily unavailable. Please try setup again shortly.",
        ) from exc


def _template_values(
    user_id: str,
    template: dict,
    bot_values: Callable[..., dict],
    system_role: str | None = None,
) -> dict:
    values = bot_values(user_id, template, system_role=system_role)
    values.update(
        {
            "templateId": template["id"],
            "templateVersion": template["version"],
            "lastMessage": "Tell me what you would like help with.",
        }
    )
    return values


def _create_template_bot(
    user_id: str,
    template: dict,
    bot_values: Callable[..., dict],
    put_bot: Callable[..., dict],
    system_role: str | None = None,
) -> dict:
    return put_bot(
        user_id,
        _template_values(user_id, template, bot_values, system_role),
        bot_id=f"catalog-{template['id']}",
        system_role=system_role,
    )


def ensure_chief(
    user_id: str,
    bots: list[dict],
    bot_values: Callable[..., dict],
    put_bot: Callable[..., dict],
) -> list[dict]:
    existing = next(
        (bot for bot in bots if bot.get("systemRole") == CHIEF_SYSTEM_ROLE), None
    )
    if existing:
        if existing.get("templateId") == CHIEF_TEMPLATE_ID:
            return sorted(
                [
                    _add_chief_default_skill(user_id, bot)
                    if bot["id"] == existing["id"]
                    else bot
                    for bot in bots
                ],
                key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE,
            )
        template = _required_chief_template()
        linked_version = min(
            template["version"], CHIEF_SKILL_BUILDER_TEMPLATE_VERSION - 1
        )
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(existing["id"])},
            UpdateExpression=(
                "SET templateId = :templateId, templateVersion = :templateVersion"
            ),
            ExpressionAttributeValues={
                ":templateId": template["id"],
                ":templateVersion": linked_version,
            },
        )
        return sorted(
            [
                _add_chief_default_skill(
                    user_id,
                    {
                        **bot,
                        "templateId": template["id"],
                        "templateVersion": linked_version,
                    },
                )
                if bot["id"] == existing["id"]
                else bot
                for bot in bots
            ],
            key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE,
        )

    legacy = next(
        (bot for bot in bots if str(bot.get("name", "")).strip().casefold() == "chief"),
        None,
    )
    if legacy:
        template = _required_chief_template()
        linked_version = min(
            template["version"], CHIEF_SKILL_BUILDER_TEMPLATE_VERSION - 1
        )
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(legacy["id"])},
            UpdateExpression=(
                "SET systemRole = :role, color = :color, updatedAt = :now, "
                "templateId = :templateId, templateVersion = :templateVersion"
            ),
            ExpressionAttributeValues={
                ":role": CHIEF_SYSTEM_ROLE,
                ":color": CHIEF_COLOR,
                ":now": _now(),
                ":templateId": template["id"],
                ":templateVersion": linked_version,
            },
        )
        return sorted(
            [
                _add_chief_default_skill(
                    user_id,
                    {
                        **bot,
                        "systemRole": CHIEF_SYSTEM_ROLE,
                        "color": CHIEF_COLOR,
                        "templateId": template["id"],
                        "templateVersion": linked_version,
                    },
                )
                if bot["id"] == legacy["id"]
                else bot
                for bot in bots
            ],
            key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE,
        )

    chief = _create_template_bot(
        user_id,
        _required_chief_template(),
        bot_values,
        put_bot,
        CHIEF_SYSTEM_ROLE,
    )
    return [chief, *bots]


def install_bot_template(
    user_id: str,
    template_id: str,
    list_bots: Callable[[str], list[dict]],
    bot_values: Callable[..., dict],
    put_bot: Callable[..., dict],
) -> dict:
    try:
        template = catalog.get_bot_template(template_id)
    except CatalogError as exc:
        raise ApiError(404, str(exc)) from exc
    existing_bots = list_bots(user_id)
    if any(bot.get("templateId") == template["id"] for bot in existing_bots):
        raise ApiError(409, "This bot is already in your team")
    system_role = (
        CHIEF_SYSTEM_ROLE if template["id"] == CHIEF_TEMPLATE_ID else None
    )
    if system_role and any(
        bot.get("systemRole") == CHIEF_SYSTEM_ROLE for bot in existing_bots
    ):
        raise ApiError(409, "Chief is already in your team")
    return _create_template_bot(
        user_id, template, bot_values, put_bot, system_role
    )
