from __future__ import annotations

import sys
from pathlib import Path

import pytest

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from frogbot_runtime.request import MAX_HISTORY_MESSAGES, messages_from_payload


def test_prompt_is_normalized_to_a_user_message() -> None:
    assert messages_from_payload({"prompt": "  Help me plan.  "}) == [
        {"role": "user", "content": [{"text": "Help me plan."}]}
    ]


def test_trailing_tool_use_is_removed_before_invocation() -> None:
    messages = messages_from_payload(
        {
            "messages": [
                {"role": "user", "content": [{"text": "Research this"}]},
                {"role": "assistant", "content": [{"toolUse": {"name": "web"}}]},
            ]
        }
    )
    assert messages == [{"role": "user", "content": [{"text": "Research this"}]}]


def test_history_is_bounded() -> None:
    raw = [
        {"role": "user", "content": [{"text": f"Message {index}"}]}
        for index in range(MAX_HISTORY_MESSAGES + 5)
    ]
    messages = messages_from_payload({"messages": raw})
    assert len(messages) == MAX_HISTORY_MESSAGES
    assert messages[0]["content"][0]["text"] == "Message 5"


def test_non_text_content_is_rejected() -> None:
    with pytest.raises(TypeError, match="only text"):
        messages_from_payload(
            {
                "messages": [
                    {"role": "user", "content": [{"image": {"source": "unsafe"}}]}
                ]
            }
        )
