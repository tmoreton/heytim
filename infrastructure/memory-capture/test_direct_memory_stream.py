"""The direct Memory tool must be scoped, journaled, and non-retrying."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import direct_memory_stream as direct
from source_memory_attachment import load_config


class FakeControl:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def update_memory(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ConnectionError("uncertain response")
        return {"memory": {"status": "UPDATING"}}


class FakeSession:
    def __init__(self, control):
        self.control = control
        self.write_configs = []

    def client(self, service, **kwargs):
        if service == "bedrock-agentcore-control":
            if "config" in kwargs:
                self.write_configs.append(kwargs["config"])
            return self.control
        raise AssertionError(f"unexpected service {service}")


class DirectMemoryStreamTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.hashes = {key: "a" * 64 for key in (
            "runtimeEnvironment", "runtimePolicy", "evaluationDataSource", "evaluationPolicy")}
        self.plan = direct.fresh_plan(self.config, self.hashes)

    def test_update_payload_contains_only_id_token_and_stream(self):
        attach = direct.update_arguments(self.config, self.plan["attachToken"], rollback=False)
        self.assertEqual(set(attach), {"memoryId", "clientToken", "streamDeliveryResources"})
        self.assertEqual(attach["streamDeliveryResources"], direct.api_stream(self.config))
        rollback = direct.update_arguments(self.config, self.plan["rollbackToken"], rollback=True)
        self.assertEqual(set(rollback), set(attach))
        self.assertEqual(rollback["streamDeliveryResources"], {"resources": []})
        self.assertNotEqual(attach["clientToken"], rollback["clientToken"])

    def test_private_journal_and_exact_source_binding(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "journal.json"
            direct.write_plan(path, self.plan)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(direct.load_plan(path, self.config)["state"], "PREPARED")
            wrong = copy.deepcopy(self.config)
            wrong["streamArn"] = "arn:aws:kinesis:us-east-1:820323452649:stream/other"
            with self.assertRaisesRegex(ValueError, "pinned source"):
                direct.load_plan(path, wrong)

    def test_attach_once_and_rollback_with_distinct_token(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "journal.json"
            direct.write_plan(path, self.plan)
            control = FakeControl()
            session = FakeSession(control)
            with patch.object(direct, "read_live"), patch.object(direct, "verify_dependents"), \
                    patch.object(direct, "poll_memory"):
                direct.single_update(session, self.config, self.plan, path, rollback=False)
                self.assertEqual(len(control.calls), 1)
                self.assertEqual(session.write_configs[0].retries["total_max_attempts"], 1)
                self.assertEqual(control.calls[0]["clientToken"], self.plan["attachToken"])
                self.assertEqual(direct.load_plan(path, self.config)["state"], "ATTACHED")
                direct.single_update(session, self.config, self.plan, path, rollback=True)
                self.assertEqual(len(control.calls), 2)
                self.assertEqual(control.calls[1]["clientToken"], self.plan["rollbackToken"])
                self.assertEqual(control.calls[1]["streamDeliveryResources"], {"resources": []})
                self.assertEqual(direct.load_plan(path, self.config)["state"], "ROLLED_BACK")

    def test_uncertain_attach_never_retries_automatically(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "journal.json"
            direct.write_plan(path, self.plan)
            control = FakeControl(fail=True)
            session = FakeSession(control)
            with patch.object(direct, "read_live"), patch.object(direct, "verify_dependents"):
                with self.assertRaises(ConnectionError):
                    direct.single_update(session, self.config, self.plan, path, rollback=False)
                self.assertEqual(len(control.calls), 1)
                self.assertEqual(direct.load_plan(path, self.config)["state"], "ATTACH_REQUESTED")
                with self.assertRaisesRegex(ValueError, "Journal state prevents"):
                    direct.single_update(session, self.config, self.plan, path, rollback=False)
                self.assertEqual(len(control.calls), 1)

    def test_journal_lock_rejects_concurrent_operator(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "journal.json"
            direct.write_plan(path, self.plan)
            with direct.exclusive_journal(path):
                with self.assertRaisesRegex(ValueError, "another operator"):
                    with direct.exclusive_journal(path):
                        pass

    def test_async_poll_checks_identity_contract_and_final_stream(self):
        base = {"id": self.config["memoryId"], "arn": self.config["memoryArn"],
                "name": self.config["memoryName"], "eventExpiryDuration": 30,
                "memoryExecutionRoleArn": self.config["memoryRoleArn"],
                "encryptionKeyArn": self.config["memoryEncryptionKeyArn"], "strategies": []}
        self.config["expectedMemoryContractSha256"] = direct.sha256(direct.memory_contract(base))

        class Reads:
            def __init__(self, memories):
                self.memories = iter(memories)

            def get_memory(self, **kwargs):
                return {"memory": next(self.memories)}

        old_active = {**base, "status": "ACTIVE", "streamDeliveryResources": None}
        updating = {**base, "status": "UPDATING", "streamDeliveryResources": None}
        active = {**base, "status": "ACTIVE", "streamDeliveryResources": direct.api_stream(self.config)}
        direct.poll_memory(Reads([old_active, updating, active]), self.config, direct.api_stream(self.config), None,
                           timeout_seconds=10, sleep=lambda _: None, monotonic=lambda: 0)
        with self.assertRaisesRegex(ValueError, "stream changed unexpectedly"):
            direct.poll_memory(Reads([{**active, "streamDeliveryResources": {"resources": []}}]), self.config,
                               direct.api_stream(self.config), None, monotonic=lambda: 0)
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            direct.poll_memory(Reads([{**active, "eventExpiryDuration": 31}]), self.config,
                               direct.api_stream(self.config), None, monotonic=lambda: 0)


if __name__ == "__main__":
    unittest.main()
