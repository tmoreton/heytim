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


def new_mail_token() -> str:
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=").lower()


def _bot_digest(bot_id: str) -> str:
    return base64.b32encode(hashlib.sha256(bot_id.encode("utf-8")).digest()[:10]).decode(
        "ascii"
    ).rstrip("=").lower()


def mail_address(user_id: str, bot_id: str, token: str, domain: str = MAIL_DOMAIN) -> str:
    owner = base64.b32encode(uuid.UUID(user_id).bytes).decode("ascii").rstrip("=").lower()
    return f"b-{owner}.{_bot_digest(bot_id)}.{token}@{domain}"


def resolve_mail_address(table, address: str, domain: str = MAIL_DOMAIN) -> tuple[str, dict] | None:
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
            return None
        request["ExclusiveStartKey"] = last_key
