from __future__ import annotations

from collections.abc import Callable

from .api_contract import authenticated_route_keys, authenticated_routes
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
    _install_bot_template,
    _list_turn_page,
    _messages_from_turns,
    _update_bot,
)
from .browser_sessions import browser_session_route
from .connections import (
    _begin_connection_authorization,
    _connections,
    _delete_connection,
)
from .direct_chat import (
    _approve_bot_turn,
    _cancel_bot_turn,
    _run_schedule_now,
    _send_message,
)
from .github_skills import preview_github_skill, scan_github_skills
from .group_messages import _list_group_message_page, _send_group_message
from .group_routines import (
    _delete_group_routine,
    _list_group_routine_runs,
    _list_group_routines,
    _preview_group_routine,
    _save_group_routine,
)
from .group_runs import _cancel_group_run, _decide_group_action
from .group_schedules import group_schedule_route
from .groups import (
    _create_group,
    _create_group_invite,
    _delete_group,
    _delete_group_decision,
    _join_group,
    _remove_group_member,
    _save_group_decision,
    _update_group,
)
from .memories import (
    _create_bot_memory,
    _create_group_memory,
    _create_user_memory,
    _delete_bot_memory_record,
    _delete_group_memory_record,
    _delete_user_memory_record,
    _export_user_memories,
    _list_bot_memories,
    _list_group_memories,
    _list_user_memories,
    _update_bot_memory,
    _update_group_memory,
    _update_user_memory,
)
from .schedules import (
    _create_schedule,
    _delete_schedule,
    _list_schedule_runs,
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
from .workspaces import (
    _add_workspace_file,
    _delete_workspace_file,
    _download_workspace_file,
    _export_workspace_files,
    _list_workspace_files,
)

Route = Callable[[str, str, str, str, dict, dict], dict | None]


def _workspace_route(
    user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict
) -> dict | None:
    kind = "bot" if path.startswith("/bots/") else "group"
    scope_id = params.get("botId", "") if kind == "bot" else params.get("groupId", "")
    file_id = params.get("workspaceFileId", "")
    if method == "GET" and path.endswith("/export"):
        return _response(200, _export_workspace_files(user_id, kind, scope_id))
    if method == "GET" and path.endswith("/download"):
        return _response(200, _download_workspace_file(user_id, kind, scope_id, file_id))
    if method == "DELETE":
        return _response(200, _delete_workspace_file(user_id, kind, scope_id, file_id))
    if method == "GET":
        return _response(200, _list_workspace_files(user_id, kind, scope_id))
    if method == "POST":
        return _response(201, _add_workspace_file(user_id, kind, scope_id, _body(event)))
    return None


def _group_routine_route(
    user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict
) -> dict | None:
    group_id = params.get("groupId", "")
    routine_id = params.get("routineId", "")
    if method == "POST" and path.endswith("/preview"):
        return _response(200, _preview_group_routine(user_id, group_id, _body(event)))
    if method == "GET" and path.endswith("/runs"):
        return _response(200, _list_group_routine_runs(user_id, group_id))
    if method == "GET":
        return _response(200, _list_group_routines(user_id, group_id))
    if method == "POST":
        return _response(201, _save_group_routine(user_id, group_id, _body(event)))
    if method == "PUT":
        return _response(200, _save_group_routine(user_id, group_id, _body(event), routine_id))
    if method == "DELETE":
        return _response(200, _delete_group_routine(user_id, group_id, routine_id))
    return None


def _group_run_route(
    user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict
) -> dict | None:
    if method == "POST" and path.endswith("/cancel"):
        return _response(202, _cancel_group_run(
            user_id, params.get("groupId", ""), params.get("runId", "")
        ))
    if method == "POST" and path.endswith("/approval"):
        decision = _body(event).get("approved")
        if not isinstance(decision, bool):
            raise ApiError(400, "approved must be true or false")
        return _response(202, _decide_group_action(
            user_id, params.get("groupId", ""), params.get("runId", ""),
            params.get("taskId", ""), decision,
        ))
    return None


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
    if method == "POST" and path.endswith("/authorization"):
        return _response(
            200,
            _begin_connection_authorization(
                user_id, params.get("providerId", ""), _body(event)
            ),
        )
    if method == "DELETE" and path.startswith("/connections/"):
        return _response(
            200, _delete_connection(user_id, params.get("connectionId", ""))
        )
    if method == "GET" and path == "/memory":
        return _response(200, _list_user_memories(user_id))
    if method == "POST" and path == "/memory":
        return _response(201, _create_user_memory(user_id, _body(event)))
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
        query = event.get("queryStringParameters") or {}
        messages, next_token = _list_group_message_page(
            user_id, params.get("groupId", ""), query.get("cursor")
        )
        return _response(
            200,
            {"messages": messages, **({"nextToken": next_token} if next_token else {})},
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
    group_id = params.get("groupId", "")
    if method == "POST" and path.endswith("/decisions"):
        return _response(
            201,
            _save_group_decision(user_id, display_name, group_id, _body(event)),
        )
    if method == "DELETE" and "/decisions/" in path:
        return _response(
            200,
            _delete_group_decision(
                user_id, group_id, params.get("decisionId", "")
            ),
        )
    if method == "GET" and path.endswith("/memory"):
        return _response(200, _list_group_memories(user_id, group_id))
    if method == "POST" and path.endswith("/memory"):
        return _response(201, _create_group_memory(user_id, group_id, _body(event)))
    if method == "PUT" and "/memory/" in path:
        return _response(
            200,
            _update_group_memory(
                user_id,
                group_id,
                params.get("memoryRecordId", ""),
                _body(event),
            ),
        )
    if method == "DELETE" and "/memory/" in path:
        return _response(
            200,
            _delete_group_memory_record(
                user_id, group_id, params.get("memoryRecordId", "")
            ),
        )
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
    if method == "GET" and path.startswith("/bots/") and path.endswith("/runs"):
        return _response(
            200, {"runs": _list_schedule_runs(user_id, params.get("botId", ""))}
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
    if method == "POST" and path.startswith("/bot-templates/"):
        return _response(
            201, _install_bot_template(user_id, params.get("templateId", ""))
        )
    if method == "POST" and path == "/bots":
        return _response(201, _create_bot(user_id, _body(event)))
    if method == "GET" and path.endswith("/memory"):
        return _response(200, _list_bot_memories(user_id, bot_id))
    if method == "POST" and path.endswith("/memory"):
        return _response(201, _create_bot_memory(user_id, bot_id, _body(event)))
    if method == "PUT" and "/memory/" in path:
        return _response(
            200,
            _update_bot_memory(
                user_id, bot_id, params.get("memoryRecordId", ""), _body(event)
            ),
        )
    if method == "DELETE" and "/memory/" in path:
        return _response(
            200,
            _delete_bot_memory_record(user_id, bot_id, params.get("memoryRecordId", "")),
        )
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
        query = event.get("queryStringParameters") or {}
        turns, next_token = _list_turn_page(user_id, bot_id, query.get("cursor"))
        return _response(
            200,
            {
                "messages": _messages_from_turns(turns),
                **({"nextToken": next_token} if next_token else {}),
            },
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
        return _response(
            200,
            _clear_bot_chat(
                user_id,
                bot_id,
                forget_memory=_body(event).get("forgetMemory") is True,
            ),
        )
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
    if method == "POST" and path == "/skills/github/scan":
        return _response(200, scan_github_skills(_body(event)))
    if method == "POST" and path == "/skills/github/preview":
        return _response(200, preview_github_skill(_body(event)))
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


_HANDLERS: dict[str, Route] = {
    "bot": _bot_route,
    "browser": browser_session_route,
    "directChat": _direct_chat_route,
    "fileAndDevice": _file_and_device_route,
    "groupAdmin": _group_admin_route,
    "groupMessage": _group_message_route,
    "groupSchedule": group_schedule_route,
    "groupRoutine": _group_routine_route,
    "groupRun": _group_run_route,
    "library": _library_route,
    "schedule": _schedule_route,
    "sharing": _sharing_route,
    "skill": _skill_route,
    "workspace": _workspace_route,
}
ROUTE_HANDLERS: dict[str, Route] = {
    f"{route['method']} {route['path']}": _HANDLERS[route["handler"]]
    for route in authenticated_routes()
    if route["handler"] != "account"
}
AUTHENTICATED_ROUTE_KEYS = authenticated_route_keys()


def route_authenticated(
    user_id: str,
    display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
    *,
    route_key: str,
) -> dict:
    route = ROUTE_HANDLERS.get(route_key)
    if route is None:
        raise ApiError(404, "Route not found")
    response = route(user_id, display_name, method, path, params, event)
    if response is None:
        raise ApiError(404, "Route not found")
    return response
