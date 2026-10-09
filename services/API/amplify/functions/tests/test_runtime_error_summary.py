import importlib.util
import json
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[3] / "scripts/runtime-error-summary.py"
spec = importlib.util.spec_from_file_location("runtime_error_summary", path)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class RuntimeErrorSummaryTests(unittest.TestCase):
    def test_keeps_only_structural_failure_fields(self):
        marker = {
            "schema": 1,
            "category": "provider",
            "exception": "RuntimeError",
            "location": "models.py:invoke:42",
            "message": "private-user-content",
            "token": "private-token",
            "userId": "private-user-id",
        }
        events = [{"message": "ERROR HEYTIM_TERMINAL_ERROR " + json.dumps(marker)}] * 2
        result = summary.summarize(events)
        self.assertEqual(
            result,
            [
                {
                    "category": "provider",
                    "exception": "RuntimeError",
                    "location": "models.py:invoke:42",
                    "count": 2,
                }
            ],
        )
        self.assertNotIn("private", json.dumps(result))

    def test_ignores_raw_and_malformed_messages(self):
        events = [
            {"message": "private-user-content"},
            {"message": "HEYTIM_TERMINAL_ERROR not-json"},
            {"message": "HEYTIM_TERMINAL_ERROR []"},
        ]
        self.assertEqual(summary.summarize(events), [])


if __name__ == "__main__":
    unittest.main()
