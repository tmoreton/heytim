import unittest

from worker.health_events import terminal_error_category


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
