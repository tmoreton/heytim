"""Legacy bot address preservation for account-isolation planning."""

from __future__ import annotations

import base64
import hashlib
import uuid


def legacy_mail_address(user_id: str, bot_id: str, token: str) -> str:
    owner = (
        base64.b32encode(uuid.UUID(user_id).bytes).decode("ascii").rstrip("=").lower()
    )
    bot = base64.b32encode(hashlib.sha256(bot_id.encode()).digest()[:10]).decode(
        "ascii"
    )
    return f"b-{owner}.{bot.rstrip('=').lower()}.{token}@bots.heytim.ai"


def mail_alias_key(address: str) -> dict[str, str]:
    return {
        "pk": f"MAIL_ALIAS#{hashlib.sha256(address.encode()).hexdigest()}",
        "sk": "ROUTE",
    }
