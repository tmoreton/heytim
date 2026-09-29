from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "migrate_dynamodb_state.py"
SPEC = importlib.util.spec_from_file_location("migrate_dynamodb_state", SOURCE)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)

sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)

OLD_SUB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NEW_SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
IDENTITY = migration.Identity.build(OLD_SUB, NEW_SUB, {"bot-1"})


class MigrationPlanningTests(unittest.TestCase):
    def test_recursive_identity_remap_preserves_types(self) -> None:
        original = {
            "pk": f"CHAT#{OLD_SUB}#bot-1",
            "sk": "TURN#1",
            "nested": {
                "actorPath": f"users/{IDENTITY.old_actor}/work/file",
                "session": migration.direct_session_id(OLD_SUB, "bot-1"),
                "owner": OLD_SUB,
                "amount": Decimal("12.50"),
                "tags": {OLD_SUB, "other"},
            },
        }
        changed = migration.replace_identity(original, IDENTITY)
        self.assertEqual(changed["pk"], f"CHAT#{NEW_SUB}#bot-1")
        self.assertEqual(
            changed["nested"]["actorPath"], f"users/{IDENTITY.new_actor}/work/file"
        )
        self.assertEqual(
            changed["nested"]["session"], migration.direct_session_id(NEW_SUB, "bot-1")
        )
        self.assertEqual(changed["nested"]["tags"], {NEW_SUB, "other"})
        self.assertEqual(changed["nested"]["amount"], Decimal("12.50"))
        self.assertFalse(migration.contains_old_identity(changed, IDENTITY))

    def test_plan_excludes_credentials_and_push_and_pauses_schedule(self) -> None:
        originals = [
            {
                "pk": f"USER#{OLD_SUB}",
                "sk": "BOT#bot-1",
                "emailToken": "secret",
                "emailOwnerAddress": "owner@example.test",
            },
            {
                "pk": f"USER#{OLD_SUB}",
                "sk": "CONNECTION#service",
                "secretArn": "arn:secret",
            },
            {"pk": f"USER#{OLD_SUB}", "sk": "PUSH#token", "pushToken": "secret"},
            {"pk": "PUSH_TOKEN#token", "sk": "OWNER", "userId": OLD_SUB},
            {"pk": f"USER#{OLD_SUB}", "sk": "DEVICE#device", "userId": OLD_SUB},
            {
                "pk": "PLAID_ITEM#production#item_12345678",
                "sk": "CONNECTION",
                "entity": "PLAID_ITEM_MAPPING",
                "userId": OLD_SUB,
                "connectionId": "connection_0123456789abcdef0123",
            },
            {
                "pk": "OAUTH#state-digest",
                "sk": "STATE",
                "entity": "OAUTH_STATE",
                "userId": OLD_SUB,
                "verifier": "source-verifier",
                "clientSecretArn": "arn:aws:secretsmanager:us-east-1:188757775631:secret:old",
            },
            {
                "pk": f"USER#{OLD_SUB}",
                "sk": "SCHEDULE#schedule-1",
                "id": "schedule-1",
                "enabled": True,
            },
            {
                "pk": f"CHAT#{OLD_SUB}#bot-1",
                "sk": "TURN#1",
                "status": "CANCELLED",
                "userId": OLD_SUB,
                "pendingWork": [
                    {
                        "resourceId": "arn:aws:bedrock-agentcore:us-east-1:188757775631:runtime/old"
                    }
                ],
            },
            {"pk": f"USER#{OLD_SUB}", "sk": "BILLING", "stripeCustomerId": "cus_1"},
        ]
        planned, summary = migration.make_plan(originals, IDENTITY)
        self.assertEqual(summary["sourceItems"], 10)
        self.assertEqual(summary["plannedItems"], 4)
        self.assertEqual(
            summary["excluded"],
            {
                "device-registration": 1,
                "unfinished-oauth-authorization": 1,
                "plaid-provider-mapping": 1,
                "provider-connection": 1,
                "push-token-or-endpoint": 2,
            },
        )
        self.assertEqual(summary["botEmailTokensRemoved"], 1)
        self.assertEqual(summary["schedulesPaused"], 1)
        self.assertEqual(summary["billingRowsRequiringReconciliation"], 1)
        self.assertEqual(summary["cancelledTurnPendingWorkRemoved"], 1)
        self.assertEqual(summary["historicalTurnRowsWithSourceAccountReferences"], 0)
        bot = next(item for item in planned if item["sk"] == "BOT#bot-1")
        self.assertNotIn("emailToken", bot)
        schedule = next(item for item in planned if item["sk"] == "SCHEDULE#schedule-1")
        self.assertFalse(schedule["enabled"])
        self.assertEqual(
            schedule["schedulerName"], migration.schedule_name(NEW_SUB, "schedule-1")
        )
        turn = next(item for item in planned if item["sk"] == "TURN#1")
        self.assertNotIn("pendingWork", turn)

    def test_historical_chat_supplies_deleted_bot_ids(self) -> None:
        self.assertEqual(
            migration.bot_ids_for_user(
                [{"pk": f"CHAT#{OLD_SUB}#bot-2", "sk": "TURN#1"}], OLD_SUB
            ),
            {"bot-2"},
        )

    def test_plan_rejects_unmapped_user_chat_and_group_member(self) -> None:
        base = {"pk": f"USER#{OLD_SUB}", "sk": "BOT#bot-1"}
        for unexpected in (
            {"pk": f"USER#{NEW_SUB}", "sk": "STATE"},
            {"pk": f"CHAT#{NEW_SUB}#bot-2", "sk": "TURN#1"},
            {"pk": "GROUP#group-1", "sk": f"USER#{NEW_SUB}"},
        ):
            with (
                self.subTest(unexpected=unexpected["pk"]),
                self.assertRaises(migration.MigrationError),
            ):
                migration.make_plan([base, unexpected], IDENTITY)

    def test_destination_must_match_exact_planned_rows(self) -> None:
        planned = [{"pk": "USER#new", "sk": "STATE", "amount": Decimal("1.2")}]
        self.assertEqual(migration.verify_destination([], planned), 0)
        self.assertEqual(migration.verify_destination(planned, planned), 1)
        with self.assertRaises(migration.MigrationError):
            migration.verify_destination(
                [{"pk": "USER#new", "sk": "STATE", "amount": Decimal("1.3")}], planned
            )

    def test_canonical_digest_is_independent_of_scan_order(self) -> None:
        first = {"pk": "A", "sk": "1", "value": {"x", "y"}}
        second = {"pk": "B", "sk": "2", "value": Decimal("3.14")}
        self.assertEqual(
            migration.table_digest([first, second]),
            migration.table_digest([second, first]),
        )


if __name__ == "__main__":
    unittest.main()
