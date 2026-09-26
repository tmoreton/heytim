from __future__ import annotations

import json
import unittest
from pathlib import Path


class ManagedRegressionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repository = Path(__file__).parents[5]
        cls.runner = (
            repository / "services/runtime/scripts/run_managed_regression.py"
        ).read_text(encoding="utf-8")
        cls.examples = [
            json.loads(line)
            for line in (
                repository / "agentcore/datasets/HeyTimRegression.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_runner_uses_an_explicit_structured_invoker(self) -> None:
        for value in (
            "DatasetManagementServiceProvider",
            '"tools": []',
            '"skills": []',
            "agentRuntimeArn=runtime_arn",
            "gen_ai.task.input",
            "gen_ai.task.output",
            "kms_key_arn=args.kms_key_arn",
        ):
            self.assertIn(value, self.runner)
        self.assertNotIn(".env.local", self.runner)

    def test_inputs_use_the_runtime_contract(self) -> None:
        self.assertGreaterEqual(len(self.examples), 5)
        for example in self.examples:
            for turn in example["turns"]:
                self.assertIsInstance(turn["input"], str)
                self.assertTrue(turn["input"].strip())


if __name__ == "__main__":
    unittest.main()
