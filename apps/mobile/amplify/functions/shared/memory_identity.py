from __future__ import annotations

import hashlib


def memory_actor_id(user_id: str) -> str:
    """Return the non-PII AgentCore Memory actor identifier for a user."""
    return hashlib.sha256(f"user:{user_id}".encode()).hexdigest()


def direct_session_id(user_id: str, bot_id: str) -> str:
    """Keep one stable runtime and memory session per user/bot conversation."""
    return hashlib.sha256(f"{user_id}:{bot_id}".encode()).hexdigest()


def group_session_id(group_id: str, bot_id: str) -> str:
    return hashlib.sha256(f"group:{group_id}:bot:{bot_id}".encode()).hexdigest()


def scoped_session_id(scope: str) -> str:
    return hashlib.sha256(scope.encode()).hexdigest()
