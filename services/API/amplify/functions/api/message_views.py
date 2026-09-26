from __future__ import annotations

import json

from .attachments import _public_file


def messages_from_turns(turns: list[dict]) -> list[dict]:
    messages = []
    for turn in turns:
        messages.append(
            {
                "id": f"{turn['id']}-user",
                "role": "user",
                "text": turn["userText"],
                "createdAt": turn["createdAt"],
                "status": "complete",
                "allowedActions": [],
                **(
                    {
                        "source": "schedule",
                        "scheduleName": turn.get("scheduleName", "Scheduled task"),
                    }
                    if turn.get("source") == "schedule"
                    else {
                        "source": "email",
                        **(
                            {"emailSubject": turn["emailSubject"]}
                            if isinstance(turn.get("emailSubject"), str)
                            and turn["emailSubject"]
                            else {}
                        ),
                    }
                    if turn.get("source") == "email"
                    else {"source": "desktop_action"}
                    if turn.get("source") == "desktop_action"
                    else {}
                ),
                **(
                    {
                        "attachments": [
                            _public_file(item)
                            for item in turn["attachments"]
                            if isinstance(item, dict)
                        ]
                    }
                    if isinstance(turn.get("attachments"), list)
                    else {}
                ),
            }
        )
        if turn.get("assistantText"):
            status = turn.get("status", "complete").lower()
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": turn["assistantText"],
                    "createdAt": turn.get("completedAt", turn["createdAt"]),
                    "startedAt": turn.get("startedAt", turn["createdAt"]),
                    "status": status,
                    **({"source": "desktop_action"} if turn.get("source") == "desktop_action" else {}),
                    "allowedActions": (
                        ["reject", "approveOnce", "approveAlways"]
                        if status == "awaiting_approval"
                        else ["cancel"]
                        if status in {"pending", "running", "awaiting_device"}
                        else []
                    ),
                    "activity": turn.get("activity", []),
                    **(
                        {"configurationChanged": True}
                        if turn.get("configurationChanged") is True
                        else {}
                    ),
                    **(
                        {"activityUpdatedAt": turn["activityUpdatedAt"]}
                        if isinstance(turn.get("activityUpdatedAt"), str)
                        else {}
                    ),
                    **(
                        {"completedAt": turn["completedAt"]}
                        if isinstance(turn.get("completedAt"), str)
                        else {}
                    ),
                    **(
                        {
                            "attachments": [
                                _public_file(item)
                                for item in turn["artifacts"]
                                if isinstance(item, dict)
                            ]
                        }
                        if isinstance(turn.get("artifacts"), list)
                        else {}
                    ),
                }
            )
        elif turn.get("status") in {
            "PENDING",
            "RUNNING",
            "NEEDS_INPUT",
            "AWAITING_APPROVAL",
            "AWAITING_DEVICE",
        }:
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": "",
                    "createdAt": turn["createdAt"],
                    "startedAt": turn.get("startedAt", turn["createdAt"]),
                    "status": str(turn.get("status", "PENDING")).lower(),
                    "allowedActions": (
                        ["reject", "approveOnce", "approveAlways"]
                        if turn.get("status") == "AWAITING_APPROVAL"
                        else ["cancel"]
                        if turn.get("status") in {"PENDING", "RUNNING", "AWAITING_DEVICE"}
                        else []
                    ),
                    "activity": turn.get("activity", []),
                    **(
                        {"activityUpdatedAt": turn["activityUpdatedAt"]}
                        if isinstance(turn.get("activityUpdatedAt"), str)
                        else {}
                    ),
                    **(
                        {"approvalTools": turn["approvalTools"]}
                        if isinstance(turn.get("approvalTools"), list)
                        else {"approvalTools": [turn["approvalRequest"]["toolName"]]}
                        if isinstance(turn.get("approvalRequest"), dict)
                        else {}
                    ),
                    **(
                        {"approvalInput": json.dumps(turn["approvalRequest"].get("input"),
                                                      sort_keys=True, ensure_ascii=False, indent=2)}
                        if isinstance(turn.get("approvalRequest"), dict)
                        else {}
                    ),
                }
            )
    return messages
