"""Score one offline Laya Home Assistant decision. Reads JSON, never calls MCP."""

from __future__ import annotations

import json
import sys

from heytim_runtime.home_assistant_decisions import laya_advisory_candidate


def main() -> int:
    payload = json.load(sys.stdin)
    answer = payload["answer"]
    candidate = laya_advisory_candidate(
        request=payload["request"],
        entity_alias=payload["entityAlias"],
        entity_id=payload["entityId"],
        exposed_to_assist=payload["exposedToAssist"],
        discovered_tools=payload["tools"],
        selected_label=answer["selected"],
        confidence=answer["confidence"],
        action_probability=answer["action_probability"],
        truncated=answer["tokens"] >= answer["bucket"],
    )
    print(candidate["abstractAction"] if candidate else "main_model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
