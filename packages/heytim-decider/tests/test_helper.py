import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from heytim_decider.helper import Decider, MODEL_ID, MODEL_REVISION, prepare, select_result, validate_params


class InputAndRoutingTests(unittest.TestCase):
    def test_duplicate_candidate_ids_cannot_change_authorized_route(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_params({"text": "hello", "bots": [{"id": "same"}, {"id": "same"}]})

    def test_reserved_abstention_id_cannot_be_a_bot(self):
        with self.assertRaisesRegex(ValueError, "clarify"):
            validate_params({"text": "hello", "bots": [{"id": "clarify"}]})

    def test_transcript_byte_limit_handles_non_ascii(self):
        with self.assertRaisesRegex(ValueError, "16384-byte"):
            validate_params({"text": "🙂" * 4097, "bots": []})

    def test_empty_candidate_set_requires_review_without_model(self):
        result = Decider(Path("/nonexistent/model")).decide({"text": "hi", "bots": []})
        self.assertIsNone(result["botId"])
        self.assertTrue(result["needsReview"])
        self.assertEqual(result["reason"], "no_candidates")
        self.assertTrue(result["reasoningDeferred"])
        self.assertEqual(result["reasoningEffort"], "high")

    def test_low_confidence_never_automatically_selects_top_bot(self):
        answer = {"agent": {"choice": "travel", "confidence": 0.79,
                            "probabilities": {"travel": 0.85, "clarify": 0.15}},
                  "effort": {"choice": "high", "confidence": 0.5}}
        result = select_result(answer, minimum_confidence=0.8, minimum_margin=0.15)
        self.assertIsNone(result["botId"])
        self.assertEqual(result["reason"], "low_confidence")
        self.assertTrue(result["reasoningDeferred"])

    def test_clarify_does_not_become_an_executable_bot_id(self):
        answer = {"agent": {"choice": "clarify", "confidence": 0.99,
                            "probabilities": {"travel": 0.005, "clarify": 0.995}},
                  "effort": {"choice": "low", "confidence": 0.8}}
        result = select_result(answer, minimum_confidence=0.8, minimum_margin=0.15)
        self.assertIsNone(result["botId"])
        self.assertEqual(result["reason"], "clarification")

    def test_nonfinite_model_output_is_an_error_not_an_automatic_route(self):
        answer = {"agent": {"choice": "travel", "confidence": float("nan"),
                            "probabilities": {"travel": 0.9, "clarify": 0.1}},
                  "effort": {"choice": "low", "confidence": 0.8}}
        with self.assertRaisesRegex(ValueError, "invalid"):
            select_result(answer, minimum_confidence=0.8, minimum_margin=0.15)

    def test_uncertain_effort_preserves_selected_bot_saved_preference(self):
        answer = {"agent": {"choice": "travel", "confidence": 0.95,
                            "probabilities": {"travel": 0.975, "clarify": 0.025}},
                  "effort": {"choice": "high", "confidence": 0.4}}
        result = select_result(answer, minimum_confidence=0.8, minimum_margin=0.15,
                               bot_preferences={"travel": "low"})
        self.assertEqual(result["botId"], "travel")
        self.assertTrue(result["reasoningDeferred"])
        self.assertEqual(result["reasoningEffort"], "low")
        self.assertEqual(result["suggestedReasoningEffort"], "high")

    def test_confident_effort_can_override_saved_preference_at_frozen_threshold(self):
        answer = {"agent": {"choice": "travel", "confidence": 0.95,
                            "probabilities": {"travel": 0.975, "clarify": 0.025}},
                  "effort": {"choice": "max", "confidence": 0.5}}
        result = select_result(answer, minimum_confidence=0.8, minimum_margin=0.15,
                               bot_preferences={"travel": "high"})
        self.assertFalse(result["reasoningDeferred"])
        self.assertEqual(result["reasoningEffort"], "max")


class ProtocolTests(unittest.TestCase):
    def test_bad_line_does_not_corrupt_next_request(self):
        with tempfile.TemporaryDirectory() as root:
            process = subprocess.run(
                [sys.executable, "-m", "heytim_decider", "--model-root", root],
                input='not json\n{"id":"health-1","method":"health"}\n',
                text=True, capture_output=True, check=True,
            )
        lines = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertIn("error", lines[0])
        self.assertEqual(lines[1]["id"], "health-1")
        self.assertEqual(lines[1]["result"]["modelId"], MODEL_ID)
        self.assertEqual(lines[1]["result"]["modelRevision"], MODEL_REVISION)
        self.assertFalse(lines[1]["result"]["modelInstalled"])
        self.assertEqual(process.stderr, "")

    def test_oversized_request_is_drained_before_next_line(self):
        with tempfile.TemporaryDirectory() as root:
            process = subprocess.run(
                [sys.executable, "-m", "heytim_decider", "--model-root", root],
                input="x" * 150_000 + '\n{"id":2,"method":"health"}\n',
                text=True, capture_output=True, check=True,
            )
        lines = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertIn("131072-byte", lines[0]["error"]["message"])
        self.assertEqual(lines[1]["id"], 2)


class PreparationProgressTests(unittest.TestCase):
    def test_disabled_progress_base_without_unit_supports_initialization_and_update(self):
        class DisabledProgress:
            """tqdm's disabled path does not initialize its usual .unit member."""
            def __init__(self, *args, **kwargs):
                self.total = kwargs.get("total")
                self.update(0)

            def update(self, n=1):
                return None

        hub = types.ModuleType("huggingface_hub")
        parent = types.ModuleType("tqdm")
        parent.__path__ = []
        auto = types.ModuleType("tqdm.auto")
        auto.tqdm = DisabledProgress

        def download(**kwargs):
            progress = kwargs["tqdm_class"](total=100, unit="B")
            progress.update(100)
            raise RuntimeError("stop after progress")

        hub.snapshot_download = download
        events = []
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {}), \
                mock.patch.dict(sys.modules, {"huggingface_hub": hub, "tqdm": parent, "tqdm.auto": auto}), \
                mock.patch("heytim_decider.helper.emit", side_effect=events.append):
            with self.assertRaisesRegex(RuntimeError, "stop after progress"):
                prepare(Decider(Path(root)))
        self.assertEqual(events[-1]["downloadedBytes"], 100)
        self.assertEqual(events[-1]["totalBytes"], 100)


if __name__ == "__main__":
    unittest.main()
