from __future__ import annotations

import re
from typing import Any

from strands.models import RoutingCandidate, RoutingContext
from strands.types.content import Messages

ADVANCED_REQUEST_MIN_CHARS = 2_000
_ADVANCED_REQUEST = re.compile(
    r"```"
    r"|\b(?:api|backend|frontend|bug|code|coding|debug|docker|git|javascript|"
    r"kubernetes|lambda|programming|python|react|refactor|repository|sql|typescript)\b"
    r"|\b(?:build error|ci/cd|continuous integration|database schema|implementation|"
    r"pull request|software architecture|stack trace|system design|test suite|unit tests?)\b"
    r"|\b(?:complex reasoning|deep analysis|think deeply)\b",
    re.IGNORECASE,
)


def _latest_user_text(messages: Messages) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return "\n".join(
            text
            for block in message.get("content", [])
            if isinstance(block, dict) and isinstance((text := block.get("text")), str)
        )
    return ""


class TaskRoutingStrategy:
    """Route routine requests to candidate zero and technical work to candidate one."""

    async def select(
        self, context: RoutingContext, **_kwargs: Any
    ) -> RoutingCandidate | None:
        # Each candidate owns safe provider failover. Declining after a failure avoids
        # appending a second model's response after partial content has already streamed.
        if context.attempts:
            return None
        if len(context.candidates) != 2:
            raise ValueError("TaskRoutingStrategy requires exactly two candidates")

        request = _latest_user_text(context.messages)
        advanced = (
            len(request) >= ADVANCED_REQUEST_MIN_CHARS
            or _ADVANCED_REQUEST.search(request) is not None
        )
        return context.candidates[1 if advanced else 0]
