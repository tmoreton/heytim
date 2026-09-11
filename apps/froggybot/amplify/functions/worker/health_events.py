from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def terminal_error_category(message: object) -> str:
    text = str(message).lower()
    if any(term in text for term in ("image generation", "image-generator", "image model")):
        return "image"
    if any(term in text for term in ("browser", "concurrent connection", "session conflict")):
        return "browser"
    if any(term in text for term in ("stopped reporting", "eight-hour limit", "heartbeat")):
        return "stalled"
    if any(term in text for term in ("openrouter", "bedrock", "provider", "model", "credential", "rate limit")):
        return "provider"
    return "other"


def record_terminal_error(message: object) -> None:
    # The stable marker is safe to retain because it excludes raw error text.
    logger.error("FROGBOT_TERMINAL_ERROR category=%s", terminal_error_category(message))
