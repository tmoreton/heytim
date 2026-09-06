from __future__ import annotations

import json
import unittest

from shared.agent_stream import read_agent_stream


def _line(event: dict) -> bytes:
    return f"data: {json.dumps({'event': event})}".encode()


class AgentStreamTests(unittest.TestCase):
    def test_separates_tool_narration_from_final_markdown(self) -> None:
        updates: list[list[str]] = []
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "I will search the web."}}}),
            _line(
                {"contentBlockStart": {"start": {"toolUse": {"name": "web_search"}}}}
            ),
            _line({"messageStop": {"stopReason": "tool_use"}}),
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "## Answer\n\n"}}}),
            _line({"contentBlockDelta": {"delta": {"text": "- One\n- Two"}}}),
            _line({"messageStop": {"stopReason": "end_turn"}}),
        ]

        answer = read_agent_stream(lines, updates.append)

        self.assertEqual(answer, "## Answer\n\n- One\n- Two")
        self.assertEqual(updates, [["I will search the web."]])

    def test_describes_silent_tool_use(self) -> None:
        updates: list[list[str]] = []
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line(
                {"contentBlockStart": {"start": {"toolUse": {"name": "current_time"}}}}
            ),
            _line({"messageStop": {"stopReason": "tool_use"}}),
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "It is noon."}}}),
            _line({"messageStop": {"stopReason": "end_turn"}}),
        ]

        answer = read_agent_stream(lines, updates.append)

        self.assertEqual(answer, "It is noon.")
        self.assertEqual(updates, [["Using current time"]])

    def test_unframed_stream_falls_back_to_all_text(self) -> None:
        answer = read_agent_stream(
            [_line({"contentBlockDelta": {"delta": {"text": "Hello"}}})]
        )

        self.assertEqual(answer, "Hello")

    def test_tool_progress_is_not_accepted_as_a_completed_answer(self) -> None:
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "I will inspect it."}}}),
            _line(
                {"contentBlockStart": {"start": {"toolUse": {"name": "read"}}}}
            ),
            _line({"messageStop": {"stopReason": "tool_use"}}),
        ]

        with self.assertRaisesRegex(ValueError, "without a completed assistant turn"):
            read_agent_stream(lines)

    def test_max_tokens_stop_is_not_accepted_as_a_completed_answer(self) -> None:
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "Partial answer"}}}),
            _line({"messageStop": {"stopReason": "max_tokens"}}),
        ]

        with self.assertRaisesRegex(ValueError, "last stop reason: max_tokens"):
            read_agent_stream(lines)


if __name__ == "__main__":
    unittest.main()
