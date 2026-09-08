from __future__ import annotations

from collections.abc import Callable

from .attachments import (
    _complete_upload,
    _create_upload,
    _download_file,
    _download_group_file,
)
from .bot_documents import _list_bot_documents
from .bots import (
    _bootstrap,
    _clear_bot_chat,
    _create_bot,
    _delete_bot,
    _get_bot,
    _list_turns,
    _messages_from_turns,
    _update_bot,
)
from .connections import _connections, _delete_connection, _save_connection
from .direct_chat import (
    _approve_bot_turn,
    _cancel_bot_turn,
    _run_schedule_now,
    _send_message,
)
from .google_oauth import _begin_gmail_authorization
from .group_messages import _list_group_messages, _send_group_message
from .groups import (
    _create_group,
    _create_group_invite,
    _delete_group,
    _join_group,
    _remove_group_member,
    _update_group,
)
from .memories import (
    _delete_user_memory_record,
    _export_user_memories,
    _list_user_memories,
    _update_user_memory,
)
from .schedules import (
    _create_schedule,
    _delete_schedule,
    _list_schedules,
    _update_schedule,
)
from .sharing import (
    _create_share,
    _get_skill,
    _import_share,
    _import_skill,
    _list_shares,
    _register_push_token,
    _revoke_share,
    _save_skill,
    _share_skill,
    _unregister_push_token,
)
from .support import ApiError, _body, _response

Route = Callable[[str, str, str, str, dict, dict], dict | None]


def _library_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "GET" and path == "/connections":
        return _response(200, _connections(user_id))
    if method == "POST" and path == "/connections/gmail/authorization":
        return _response(200, _begin_gmail_authorization(user_id, _body(event)))
    if method == "POST" and path == "/connections":
        return _response(201, _save_connection(user_id, _body(event)))
    if method == "PUT" and path.startswith("/connections/"):
        return _response(
            200,
            _save_connection(user_id, _body(event), params.get("connectionId", "")),
        )
    if method == "DELETE" and path.startswith("/connections/"):
        return _response(
            200, _delete_connection(user_id, params.get("connectionId", ""))
        )
    if method == "GET" and path == "/memory":
        return _response(200, _list_user_memories(user_id))
    if method == "POST" and path == "/memory/export":
        return _response(200, _export_user_memories(user_id))
    if method == "PUT" and path.startswith("/memory/"):
        return _response(
            200,
            _update_user_memory(
                user_id, params.get("memoryRecordId", ""), _body(event)
            ),
        )
    if method == "DELETE" and path.startswith("/memory/"):
        return _response(
            200,
            _delete_user_memory_record(user_id, params.get("memoryRecordId", "")),
        )
    return None


def _group_message_route(
    user_id: str,
    display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "GET" and path.startswith("/groups/") and path.endswith("/messages"):
        return _response(
            200,
            {"messages": _list_group_messages(user_id, params.get("groupId", ""))},
        )
    if method == "POST" and path.startswith("/groups/") and path.endswith("/messages"):
        return _response(
            202,
            _send_group_message(
                user_id, display_name, params.get("groupId", ""), _body(event)
            ),
        )
    if (
        method == "GET"
        and path.startswith("/groups/")
        and "/files/" in path
        and path.endswith("/download")
    ):
        return _response(
            200,
            _download_group_file(
                user_id, params.get("groupId", ""), params.get("fileId", "")
            ),
        )
    return None


def _group_admin_route(
    user_id: str,
    display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "POST" and path == "/groups":
        return _response(201, _create_group(user_id, display_name, _body(event)))
    if method == "PUT" and path.startswith("/groups/") and "/members/" not in path:
        return _response(
            200, _update_group(user_id, params.get("groupId", ""), _body(event))
        )
    if method == "POST" and path.startswith("/groups/") and path.endswith("/invites"):
        return _response(201, _create_group_invite(user_id, params.get("groupId", "")))
    if (
        method == "POST"
        and path.startswith("/group-invites/")
        and path.endswith("/join")
    ):
        return _response(
            201, _join_group(user_id, display_name, params.get("token", ""))
        )
    if method == "DELETE" and path.startswith("/groups/") and "/members/" in path:
        return _response(
            200,
            _remove_group_member(
                user_id, params.get("groupId", ""), params.get("memberId", "")
            ),
        )
    if method == "DELETE" and path.startswith("/groups/"):
        return _response(200, _delete_group(user_id, params.get("groupId", "")))
    return None


def _schedule_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "GET" and path.startswith("/bots/") and path.endswith("/schedules"):
        return _response(
            200, {"schedules": _list_schedules(user_id, params.get("botId", ""))}
        )
    if method == "POST" and path.startswith("/bots/") and path.endswith("/schedules"):
        return _response(
            201, _create_schedule(user_id, params.get("botId", ""), _body(event))
        )
    if method == "POST" and path.endswith("/run") and "/schedules/" in path:
        return _response(
            202,
            _run_schedule_now(
                user_id, params.get("botId", ""), params.get("scheduleId", "")
            ),
        )
    if method == "PUT" and "/schedules/" in path:
        return _response(
            200,
            _update_schedule(
                user_id,
                params.get("botId", ""),
                params.get("scheduleId", ""),
                _body(event),
            ),
        )
    if method == "DELETE" and "/schedules/" in path:
        return _response(
            200,
            _delete_schedule(
                user_id, params.get("botId", ""), params.get("scheduleId", "")
            ),
        )
    return None


def _bot_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    bot_id = params.get("botId", "")
    if method == "GET" and path == "/bootstrap":
        return _response(200, _bootstrap(user_id))
    if method == "POST" and path == "/bots":
        return _response(201, _create_bot(user_id, _body(event)))
    if method == "PUT" and path.startswith("/bots/"):
        return _response(200, _update_bot(user_id, bot_id, _body(event)))
    if method == "DELETE" and path.startswith("/bots/"):
        return _response(200, _delete_bot(user_id, bot_id))
    return None


def _direct_chat_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    bot_id = params.get("botId", "")
    if method == "GET" and path.startswith("/bots/") and path.endswith("/documents"):
        _get_bot(user_id, bot_id)
        return _response(200, {"documents": _list_bot_documents(user_id, bot_id)})
    if method == "GET" and path.startswith("/bots/") and path.endswith("/messages"):
        _get_bot(user_id, bot_id)
        return _response(
            200, {"messages": _messages_from_turns(_list_turns(user_id, bot_id))}
        )
    if method == "POST" and path.startswith("/bots/") and path.endswith("/messages"):
        return _response(202, _send_message(user_id, bot_id, _body(event)))
    if method == "POST" and path.startswith("/bots/") and path.endswith("/approve"):
        return _response(
            202,
            _approve_bot_turn(
                user_id,
                bot_id,
                params.get("turnId", ""),
                _body(event).get("always") is True,
            ),
        )
    if method == "POST" and path.startswith("/bots/") and path.endswith("/cancel"):
        return _response(
            200, _cancel_bot_turn(user_id, bot_id, params.get("turnId", ""))
        )
    if method == "DELETE" and path.startswith("/bots/") and path.endswith("/messages"):
        return _response(200, _clear_bot_chat(user_id, bot_id))
    return None


def _file_and_device_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "PUT" and path == "/devices/push-token":
        return _response(200, _register_push_token(user_id, _body(event)))
    if method == "DELETE" and path == "/devices/push-token":
        return _response(200, _unregister_push_token(user_id, _body(event)))
    if method == "POST" and path == "/uploads":
        return _response(201, _create_upload(user_id, _body(event)))
    if method == "POST" and path.startswith("/uploads/") and path.endswith("/complete"):
        return _response(200, _complete_upload(user_id, params.get("fileId", "")))
    if method == "GET" and path.startswith("/files/") and path.endswith("/download"):
        return _response(200, _download_file(user_id, params.get("fileId", "")))
    return None


def _sharing_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "POST" and path == "/shares":
        return _response(201, _create_share(user_id, _body(event)))
    if method == "GET" and path == "/shares":
        return _response(200, {"shares": _list_shares(user_id)})
    if method == "DELETE" and path.startswith("/shares/"):
        return _response(200, _revoke_share(user_id, params.get("token", "")))
    if method == "POST" and path.endswith("/import") and path.startswith("/shares/"):
        return _response(201, _import_share(user_id, params.get("token", "")))
    return None


def _skill_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    if method == "POST" and path == "/skills":
        return _response(201, _save_skill(user_id, _body(event)))
    if method == "GET" and path.startswith("/skills/"):
        return _response(200, _get_skill(user_id, params.get("skillId", "")))
    if method == "PUT" and path.startswith("/skills/"):
        return _response(
            200, _save_skill(user_id, _body(event), params.get("skillId", ""))
        )
    if method == "POST" and path.startswith("/skills/") and path.endswith("/share"):
        return _response(201, _share_skill(user_id, params.get("skillId", "")))
    if (
        method == "POST"
        and path.startswith("/skill-shares/")
        and path.endswith("/import")
    ):
        return _response(201, _import_skill(user_id, params.get("token", "")))
    return None


ROUTES: tuple[Route, ...] = (
    _library_route,
    _group_message_route,
    _group_admin_route,
    _schedule_route,
    _direct_chat_route,
    _bot_route,
    _file_and_device_route,
    _sharing_route,
    _skill_route,
)


def route_authenticated(
    user_id: str, display_name: str, method: str, path: str, params: dict, event: dict
) -> dict:
    for route in ROUTES:
        response = route(user_id, display_name, method, path, params, event)
        if response is not None:
            return response
    raise ApiError(404, "Route not found")
