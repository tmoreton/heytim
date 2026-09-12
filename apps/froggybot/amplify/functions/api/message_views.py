from __future__ import annotations

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
                **(
                    {
                        "source": "schedule",
                        "scheduleName": turn.get("scheduleName", "Scheduled task"),
                    }
                    if turn.get("source") == "schedule"
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
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": turn["assistantText"],
                    "createdAt": turn.get("completedAt", turn["createdAt"]),
                    "startedAt": turn.get("startedAt", turn["createdAt"]),
                    "status": turn.get("status", "complete").lower(),
                    "activity": turn.get("activity", []),
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
        }:
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": "",
                    "createdAt": turn["createdAt"],
                    "startedAt": turn.get("startedAt", turn["createdAt"]),
                    "status": str(turn.get("status", "PENDING")).lower(),
                    "activity": turn.get("activity", []),
                    **(
                        {"activityUpdatedAt": turn["activityUpdatedAt"]}
                        if isinstance(turn.get("activityUpdatedAt"), str)
                        else {}
                    ),
                    **(
                        {"approvalTools": turn["approvalTools"]}
                        if isinstance(turn.get("approvalTools"), list)
                        else {}
                    ),
                }
            )
    return messages
