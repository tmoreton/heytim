from __future__ import annotations


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


def bot_sk(bot_id: str) -> str:
    return f"BOT#{bot_id}"


def bot_key(user_id: str, bot_id: str) -> dict[str, str]:
    return {"pk": user_pk(user_id), "sk": bot_sk(bot_id)}


def turn_pk(user_id: str, bot_id: str) -> str:
    return f"CHAT#{user_id}#{bot_id}"


def user_state_key(user_id: str) -> dict[str, str]:
    return {"pk": user_pk(user_id), "sk": "STATE"}


def schedule_key(user_id: str, schedule_id: str) -> dict[str, str]:
    return {"pk": user_pk(user_id), "sk": f"SCHEDULE#{schedule_id}"}


def group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def push_token_key(user_id: str, token_id: str) -> dict[str, str]:
    return {"pk": user_pk(user_id), "sk": f"PUSH#{token_id}"}


def push_owner_key(token_id: str) -> dict[str, str]:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}
