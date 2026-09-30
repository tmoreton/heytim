from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid

from shared.keys import user_pk

MAIL_DOMAIN = "bots.heytim.ai"
_ADDRESS_PATTERN = re.compile(r"^b-([a-z2-7]{26})\.([a-z2-7]{16})\.([a-z2-7]{16})$")
_RECIPIENT_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


def validated_email_recipient(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Email recipient must be an address")
    address = value.strip().lower()
    if len(address) > 320 or not _RECIPIENT_PATTERN.fullmatch(address):
        raise ValueError("Email recipient must be a valid address")
    return address


def new_mail_token() -> str:
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=").lower()


def _bot_digest(bot_id: str) -> str:
    return (
        base64.b32encode(hashlib.sha256(bot_id.encode("utf-8")).digest()[:10])
        .decode("ascii")
        .rstrip("=")
        .lower()
    )


def mail_address(
    user_id: str, bot_id: str, token: str, domain: str = MAIL_DOMAIN
) -> str:
    owner = (
        base64.b32encode(uuid.UUID(user_id).bytes).decode("ascii").rstrip("=").lower()
    )
    return f"b-{owner}.{_bot_digest(bot_id)}.{token}@{domain}"


def current_mail_address(user_id: str, bot: dict) -> str:
    bot_id = bot["id"]
    token = bot["emailToken"]
    legacy = bot.get("legacyEmailAddress")
    if isinstance(legacy, str):
        local, separator, host = legacy.lower().rpartition("@")
        match = _ADDRESS_PATTERN.fullmatch(local)
        if (
            separator
            and host == MAIL_DOMAIN
            and match
            and hmac.compare_digest(match.group(2), _bot_digest(bot_id))
            and hmac.compare_digest(match.group(3), token)
        ):
            return legacy.lower()
    return mail_address(user_id, bot_id, token)


def mail_alias_key(address: str) -> dict[str, str]:
    canonical = address.strip().lower()
    return {
        "pk": f"MAIL_ALIAS#{hashlib.sha256(canonical.encode()).hexdigest()}",
        "sk": "ROUTE",
    }


def _resolve_legacy_alias(table, address: str, bot_part: str, token_part: str):
    alias = table.get_item(Key=mail_alias_key(address), ConsistentRead=True).get("Item")
    if not alias or alias.get("entity") != "MAIL_ALIAS":
        return None
    user_id = alias.get("targetUserId")
    bot_id = alias.get("targetBotId")
    if not isinstance(user_id, str) or not isinstance(bot_id, str):
        return None
    bot = table.get_item(
        Key={"pk": user_pk(user_id), "sk": f"BOT#{bot_id}"}, ConsistentRead=True
    ).get("Item")
    if not bot or bot.get("id") != bot_id:
        return None
    token = bot.get("emailToken")
    legacy = bot.get("legacyEmailAddress")
    if (
        isinstance(token, str)
        and isinstance(legacy, str)
        and isinstance(alias.get("address"), str)
        and hmac.compare_digest(_bot_digest(bot_id), bot_part)
        and hmac.compare_digest(token, token_part)
        and hmac.compare_digest(legacy.lower(), address)
        and hmac.compare_digest(alias["address"].lower(), address)
    ):
        return user_id, bot
    return None


def resolve_mail_address(
    table, address: str, domain: str = MAIL_DOMAIN
) -> tuple[str, dict] | None:
    local, separator, host = address.strip().lower().rpartition("@")
    if not separator or host != domain.lower():
        return None
    match = _ADDRESS_PATTERN.fullmatch(local)
    if not match:
        return None
    owner_part, bot_part, token_part = match.groups()
    try:
        user_id = str(uuid.UUID(bytes=base64.b32decode(owner_part.upper() + "======")))
    except (ValueError, TypeError):
        return None
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": user_pk(user_id), ":prefix": "BOT#"},
        "ConsistentRead": True,
    }
    while True:
        response = table.query(**request)
        for bot in response.get("Items", []):
            bot_id = bot.get("id")
            token = bot.get("emailToken")
            if (
                isinstance(bot_id, str)
                and isinstance(token, str)
                and hmac.compare_digest(_bot_digest(bot_id), bot_part)
                and hmac.compare_digest(token, token_part)
            ):
                return user_id, bot
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return _resolve_legacy_alias(
                table, address.strip().lower(), bot_part, token_part
            )
        request["ExclusiveStartKey"] = last_key
