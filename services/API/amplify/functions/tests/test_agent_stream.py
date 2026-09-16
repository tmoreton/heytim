from __future__ import annotations

import json
import unittest

from shared.agent_stream import AgentTerminalError, read_agent_stream


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

    def test_emits_platform_control_without_mixing_it_into_the_answer(self) -> None:
        controls = []
        pending = [{"provider": "agentcore_code_interpreter", "taskId": "task-1"}]
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "Work started."}}}),
            _line({"messageStop": {"stopReason": "end_turn"}}),
            _line({"frogbotControl": {"pendingWork": pending}}),
        ]

        answer = read_agent_stream(lines, on_control=controls.append)

        self.assertEqual(answer, "Work started.")
        self.assertEqual(controls, [{"pendingWork": pending}])

    def test_control_can_pause_after_tool_use_without_a_final_message(self) -> None:
        controls = []
        pending = [{"provider": "agentcore_code_interpreter", "taskId": "task-1"}]
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line(
                {
                    "contentBlockStart": {
                        "start": {"toolUse": {"name": "background_command"}}
                    }
                }
            ),
            _line({"messageStop": {"stopReason": "tool_use"}}),
            _line({"frogbotControl": {"pendingWork": pending}}),
        ]

        answer = read_agent_stream(lines, on_control=controls.append)

        self.assertEqual(answer, "Background work started.")
        self.assertEqual(controls, [{"pendingWork": pending}])

    def test_usage_control_does_not_mask_an_incomplete_turn(self) -> None:
        lines = [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"messageStop": {"stopReason": "tool_use"}}),
            _line({"frogbotControl": {"usage": {"models": []}}}),
        ]

        with self.assertRaisesRegex(ValueError, "without a completed assistant turn"):
            read_agent_stream(lines)

    def test_terminal_runtime_error_is_non_retryable_and_user_readable(self) -> None:
        lines = [
            _line(
                {
                    "frogbotControl": {
                        "terminalError": {
                            "code": "TURN_TIMEOUT",
                            "message": "This response exceeded its time limit.",
                        }
                    }
                }
            )
        ]

        with self.assertRaisesRegex(
            AgentTerminalError, "exceeded its time limit"
        ):
            read_agent_stream(lines)


if __name__ == "__main__":
    unittest.main()
