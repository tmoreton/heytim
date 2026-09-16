from __future__ import annotations

import re

from shared.memory_cleanup import delete_actor_memory, delete_memory_session

from .support import FROGBOT_MEMORY_ID, agentcore

_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _identity(request: dict, key: str, maximum: int) -> str:
    value = request.get(key)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or not _IDENTITY_PATTERN.fullmatch(value)
    ):
        raise ValueError(f"{key} is invalid")
    return value


def _delete_memory_actor(request: dict) -> None:
    delete_actor_memory(
        agentcore,
        FROGBOT_MEMORY_ID,
        _identity(request, "actorId", 255),
    )


def _delete_memory_session(request: dict) -> None:
    delete_memory_session(
        agentcore,
        FROGBOT_MEMORY_ID,
        _identity(request, "actorId", 255),
        _identity(request, "sessionId", 100),
    )
