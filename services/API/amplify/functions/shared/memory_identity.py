from __future__ import annotations

import hashlib


def memory_actor_id(user_id: str) -> str:
    """Return the non-PII AgentCore Memory actor identifier for a user."""
    return hashlib.sha256(f"user:{user_id}".encode()).hexdigest()


def group_memory_actor_id(group_id: str) -> str:
    """Return an isolated actor id shared by members and bots in one group."""
    return hashlib.sha256(f"group:{group_id}".encode()).hexdigest()


def group_memory_session_id(group_id: str) -> str:
    """Return one long-term conversation stream for the whole group."""
    return hashlib.sha256(f"group-session:{group_id}".encode()).hexdigest()


def direct_session_id(user_id: str, bot_id: str) -> str:
    """Keep one stable runtime and memory session per user/bot conversation."""
    return hashlib.sha256(f"{user_id}:{bot_id}".encode()).hexdigest()


def scoped_session_id(scope: str) -> str:
    return hashlib.sha256(scope.encode()).hexdigest()
