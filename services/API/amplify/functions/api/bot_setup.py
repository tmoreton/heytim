from __future__ import annotations

from collections.abc import Callable

from shared.catalog import CatalogError

from .bot_roles import CHIEF_COLOR, CHIEF_SYSTEM_ROLE, CHIEF_TEMPLATE_ID
from .support import ApiError, _bot_sk, _now, _user_pk, catalog, table

LEGACY_BOT_TEMPLATE_IDS = {
    "starter-trip-planner": "trip-planner",
    "starter-event-planner": "event-planner",
    "starter-research-reports": "research-reports",
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
                bots, key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE
            )
        template = _required_chief_template()
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(existing["id"])},
            UpdateExpression=(
                "SET templateId = :templateId, templateVersion = :templateVersion"
            ),
            ExpressionAttributeValues={
                ":templateId": template["id"],
                ":templateVersion": template["version"],
            },
        )
        return sorted(
            [
                {
                    **bot,
                    "templateId": template["id"],
                    "templateVersion": template["version"],
                }
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
                ":templateVersion": template["version"],
            },
        )
        return sorted(
            [
                {
                    **bot,
                    "systemRole": CHIEF_SYSTEM_ROLE,
                    "color": CHIEF_COLOR,
                    "templateId": template["id"],
                    "templateVersion": template["version"],
                }
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
