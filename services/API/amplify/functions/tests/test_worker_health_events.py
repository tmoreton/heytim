import json
import logging
import unittest
from unittest.mock import patch

from worker.health_events import (
    record_terminal_error,
    terminal_error_category,
    terminal_error_event,
)


class WorkerHealthEventTests(unittest.TestCase):
    def test_terminal_errors_are_classified_without_storing_the_message(self) -> None:
        self.assertEqual(
            terminal_error_category("OpenRouter rejected the credential"), "provider"
        )
        self.assertEqual(
            terminal_error_category("Image generation failed at the provider"), "image"
        )
        self.assertEqual(
            terminal_error_category("Browser session conflict (429)"), "browser"
        )
        self.assertEqual(
            terminal_error_category("This run stopped reporting its health"), "stalled"
        )
        self.assertEqual(
            terminal_error_category("Unexpected internal problem"), "other"
        )

    def test_structured_marker_fingerprints_the_shape_without_the_message(self) -> None:
        first = terminal_error_event(ValueError("private user content"))
        second = terminal_error_event(ValueError("different private content"))

        self.assertEqual(first, second)
        self.assertEqual(first["exception"], "ValueError")
        self.assertEqual(len(first["fingerprint"]), 24)
        self.assertNotIn("private", json.dumps(first))

    def test_log_marker_never_contains_raw_error_text(self) -> None:
        with patch.object(logging.Logger, "error") as log_error:
            record_terminal_error(RuntimeError("secret-bearing failure"))

        rendered = json.dumps(log_error.call_args.args)
        self.assertIn("HEYTIM_TERMINAL_ERROR", rendered)
        self.assertNotIn("secret-bearing", rendered)
