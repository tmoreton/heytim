from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import boto3

from scripts.tests.memory_migration_test_support import (
    MemoryMigrationFixture,
    migration,
)


class MemoryMigrationTests(MemoryMigrationFixture, unittest.TestCase):
    def test_live_identity_check_rejects_structurally_valid_wrong_map(self):
        decisions = {
            "orphanPreservedUnmapped": [],
            "historicalSessionsPreservedUnmapped": [],
        }
        generated = {
            "actors": self.actors,
            "sessions": {"actor-old": {"session-old": "session-new"}},
            "decisions": decisions,
        }
        with patch.object(migration, "generated_identity_map", return_value=generated):
            migration.validate_live_identity_map(
                None, self.original, self.actors, self.sessions, decisions
            )
            with self.assertRaisesRegex(ValueError, "differs from verified Cognito"):
                migration.validate_live_identity_map(
                    None,
                    self.original,
                    {"actor-old": "another-actor"},
                    self.sessions,
                    decisions,
                )
            with self.assertRaisesRegex(ValueError, "differs from verified Cognito"):
                migration.validate_live_identity_map(
                    None,
                    self.original,
                    self.actors,
                    {("actor-old", "session-old"): "another-session"},
                    decisions,
                )

    def test_apply_preserves_content_and_uses_skip_extraction(self):
        mapped = migration.apply_migration(
            self.source,
            self.destination,
            "source-memory",
            "dest-memory",
            self.original,
            self.actors,
            self.sessions,
            self.strategies,
            decisions={
                "historicalSessionsPreservedUnmapped": [
                    {
                        "actorId": "actor-old",
                        "sessionId": "session-old",
                        "events": 1,
                        "summaries": 1,
                    }
                ]
            },
        )
        self.assertEqual(len(mapped["events"]), 1)
        self.assertEqual(len(mapped["records"]), 2)
        self.assertEqual(mapped["exceptionRetrievalsVerified"], 1)
        self.assertEqual(self.destination.event_calls[0]["extractionMode"], "SKIP")
        self.assertEqual(self.destination.event_calls[0]["eventTimestamp"], self.when)
        self.assertEqual(self.destination.event_calls[0]["actorId"], "actor-new")
        self.assertEqual(self.destination.event_calls[0]["sessionId"], "session-new")
        self.assertEqual(
            {
                tuple(r["namespaces"])
                for r in self.destination.record_calls[0]["records"]
            },
            {("/facts/actor-new/",), ("/summaries/actor-new/session-new/",)},
        )
        self.assertEqual(
            {r["timestamp"] for r in self.destination.record_calls[0]["records"]},
            {self.when},
        )
        self.assertEqual(
            migration.deterministic_token("event", "dest-memory", ["event-1"]),
            self.destination.event_calls[0]["clientToken"],
        )

    def test_destination_must_be_empty_before_writes(self):
        self.destination.events.append(dict(self.source.events[0]))
        with self.assertRaisesRegex(ValueError, "not empty"):
            migration.apply_migration(
                self.source,
                self.destination,
                "source-memory",
                "dest-memory",
                self.original,
                self.actors,
                self.sessions,
                self.strategies,
            )
        self.assertEqual(self.destination.event_calls, [])

    def test_service_generated_record_metadata_is_not_submitted_or_compared(self):
        record = self.source.records[0]
        record["metadata"].update(
            {
                "x-amz-agentcore-memory-createdAt": {"dateTimeValue": self.when},
                "x-amz-agentcore-memory-updatedAt": {"dateTimeValue": self.when},
                "x-amz-agentcore-memory-recordType": {"stringValue": "FACT"},
            }
        )
        original = migration.inventory(
            self.source, "source-memory", ["facts-old", "summaries-old"]
        )
        snapshot = migration.source_snapshot_digest(original)
        migration.apply_migration(
            self.source,
            self.destination,
            "source-memory",
            "dest-memory",
            original,
            self.actors,
            self.sessions,
            self.strategies,
        )
        copied = next(
            item
            for call in self.destination.record_calls
            for item in call["records"]
            if item["memoryStrategyId"] == "facts-new"
        )
        self.assertEqual(
            copied["metadata"], {"heytimSource": {"stringValue": "manual"}}
        )
        record["metadata"]["x-amz-agentcore-memory-updatedAt"] = {
            "dateTimeValue": datetime(2026, 9, 16, tzinfo=UTC)
        }
        self.assertNotEqual(
            migration.source_snapshot_digest(
                migration.inventory(
                    self.source, "source-memory", ["facts-old", "summaries-old"]
                )
            ),
            snapshot,
        )

    def test_resume_reconciles_partial_destination_without_duplicate_writes(self):
        source_event = self.source.events[0]
        self.destination.events.append(
            {
                **migration.expected_event(
                    source_event, self.actors, self.sessions, {}
                ),
                "eventId": "already-created-event",
            }
        )
        source_record = self.source.records[0]
        self.destination.records.append(
            {
                **migration.expected_record(
                    source_record, self.actors, self.sessions, self.strategies
                ),
                "memoryRecordId": "already-created-record",
            }
        )
        manifest = {"eventIds": {}, "recordIds": {}}
        snapshots = []
        mapped = migration.apply_migration(
            self.source,
            self.destination,
            "source-memory",
            "dest-memory",
            self.original,
            self.actors,
            self.sessions,
            self.strategies,
            manifest=manifest,
            resume=True,
            progress=lambda events, records: snapshots.append(
                (dict(events), dict(records))
            ),
        )
        self.assertEqual(self.destination.event_calls, [])
        self.assertEqual(len(self.destination.record_calls), 1)
        self.assertEqual(len(self.destination.record_calls[0]["records"]), 1)
        self.assertEqual(mapped["events"]["event-1"], "already-created-event")
        self.assertEqual(mapped["records"]["record-1"], "already-created-record")
        self.assertTrue(snapshots)

    def test_resume_refuses_unrelated_destination_event(self):
        self.destination.events.append(
            {
                **self.source.events[0],
                "eventId": "unrelated-event",
            }
        )
        with self.assertRaisesRegex(ValueError, "unexpected actor or session"):
            migration.apply_migration(
                self.source,
                self.destination,
                "source-memory",
                "dest-memory",
                self.original,
                self.actors,
                self.sessions,
                self.strategies,
                manifest={"eventIds": {}, "recordIds": {}},
                resume=True,
            )
        self.assertEqual(self.destination.event_calls, [])

    def test_branch_root_is_ordered_before_earlier_child_timestamp(self):
        root = {
            "eventId": "root",
            "eventTimestamp": self.when,
            "actorId": "actor-old",
            "sessionId": "session-old",
            "payload": [
                {"conversational": {"role": "USER", "content": {"text": "root"}}}
            ],
            "branch": {"name": "main"},
        }
        child = {
            **root,
            "eventId": "child",
            "eventTimestamp": datetime(2026, 9, 14, tzinfo=UTC),
            "branch": {"name": "fork", "rootEventId": "root"},
        }
        self.assertEqual(
            [event["eventId"] for event in migration.ordered_events([child, root])],
            ["root", "child"],
        )
        self.assertEqual(
            migration.expected_event(
                child, self.actors, self.sessions, {"root": "destination-root"}
            )["branch"]["rootEventId"],
            "destination-root",
        )

    def test_source_payloads_validate_against_destination_sdk_model(self):
        session = boto3.Session(
            aws_access_key_id="placeholder",
            aws_secret_access_key="placeholder",
            region_name="us-east-1",
        )
        destination = session.client("bedrock-agentcore")
        migration.validate_payload_shapes(
            destination,
            "DestMemory-abcdefghij",
            self.original,
            self.strategies,
        )

    def test_derive_identity_map_from_cognito_and_dynamodb_keys(self):
        old_subject = "old-sub"
        new_subject = "new-sub"
        bot_id = "bot-1"
        group_id = "group-1"
        old_actor = migration.hashed_identity(f"user:{old_subject}")
        new_actor = migration.hashed_identity(f"user:{new_subject}")
        old_session = migration.hashed_identity(f"{old_subject}:{bot_id}")
        new_session = migration.hashed_identity(f"{new_subject}:{bot_id}")
        group_actor = migration.hashed_identity(f"group:{group_id}")
        group_session = migration.hashed_identity(f"group-session:{group_id}")
        data = {
            "actors": {old_actor, group_actor},
            "sessions": {(old_actor, old_session), (group_actor, group_session)},
        }
        keys = [
            {"pk": f"USER#{old_subject}", "sk": f"BOT#{bot_id}"},
            {"pk": f"CHAT#{old_subject}#{bot_id}", "sk": "TURN#1"},
            {"pk": f"GROUP#{group_id}", "sk": "META"},
        ]
        result = migration.derive_identity_map(
            {"verified@example.test": old_subject},
            {"verified@example.test": new_subject},
            keys,
            data,
        )
        self.assertEqual(
            result["actors"],
            {
                old_actor: new_actor,
                group_actor: group_actor,
            },
        )
        self.assertEqual(
            result["sessions"],
            {
                old_actor: {old_session: new_session},
                group_actor: {group_session: group_session},
            },
        )
        self.assertEqual(
            result["decisions"],
            {
                "orphanPreservedUnmapped": [],
                "historicalSessionsPreservedUnmapped": [],
            },
        )
        self.assertNotIn("verified@example.test", json.dumps(result))
        self.assertNotIn(old_subject, json.dumps(result))
        with self.assertRaisesRegex(ValueError, "Historical session count"):
            migration.derive_identity_map(
                {"verified@example.test": old_subject},
                {"verified@example.test": new_subject},
                keys[:1],
                {
                    "actors": {old_actor},
                    "sessions": {
                        (old_actor, migration.hashed_identity("old-sub:missing"))
                    },
                    "events": [],
                    "records": [],
                },
            )

    def test_cognito_match_requires_verified_unique_email(self):
        class UsersPaginator:
            def paginate(self, **_kwargs):
                yield {
                    "Users": [
                        {
                            "UserStatus": "CONFIRMED",
                            "Attributes": [
                                {"Name": "email", "Value": "person@example.test"},
                                {"Name": "email_verified", "Value": "true"},
                                {"Name": "sub", "Value": "source-sub"},
                            ],
                        }
                    ]
                }

        class Cognito:
            def describe_user_pool(self, **kwargs):
                return {
                    "UserPool": {
                        "Arn": f"arn:aws:cognito-idp:us-east-1:123456789012:userpool/{kwargs['UserPoolId']}"
                    }
                }

            def get_paginator(self, operation):
                self.operation = operation
                return UsersPaginator()

        users = migration.verified_cognito_users(
            Cognito(), "us-east-1_pool", "123456789012", "us-east-1"
        )
        self.assertEqual(users, {"person@example.test": "source-sub"})

    def test_reviewed_orphan_and_historical_sessions_are_preserved_by_identity(self):
        old_actor = migration.hashed_identity("user:old-sub")
        known_session = migration.hashed_identity("old-sub:bot-1")
        historical = [
            migration.hashed_identity("historic-1"),
            migration.hashed_identity("historic-2"),
        ]
        orphan_actor = migration.hashed_identity("orphan-user")
        orphan_session = migration.hashed_identity("orphan-session")
        entries = (
            [(old_actor, known_session)]
            + [(old_actor, session) for session in historical]
            + [(orphan_actor, orphan_session)]
        )
        events = [
            {
                "actorId": actor,
                "sessionId": session,
                "metadata": {"heytimScope": {"stringValue": "personal"}},
            }
            for actor, session in entries
        ]
        records = [
            {"namespaces": [f"/summaries/{actor}/{session}/"]}
            for actor, session in entries
        ]
        data = {
            "actors": {old_actor, orphan_actor},
            "sessions": set(entries),
            "events": events,
            "records": records,
        }
        raw = migration.derive_identity_map(
            {"person@example.test": "old-sub"},
            {"person@example.test": "new-sub"},
            [{"pk": "USER#old-sub", "sk": "BOT#bot-1"}],
            data,
            expected_orphans=1,
            expected_historical_sessions=2,
        )
        self.assertEqual(raw["actors"][orphan_actor], orphan_actor)
        self.assertEqual(raw["sessions"][orphan_actor][orphan_session], orphan_session)
        self.assertEqual(len(raw["decisions"]["orphanPreservedUnmapped"]), 1)
        self.assertEqual(
            len(raw["decisions"]["historicalSessionsPreservedUnmapped"]), 2
        )
        data["records"].append({"namespaces": [f"/facts/{orphan_actor}/"]})
        with self.assertRaisesRegex(ValueError, "Orphan memory shape"):
            migration.validate_identity_map(raw, data)

    def test_identity_map_is_exhaustive_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "actors": self.actors,
                        "sessions": {"actor-old": {"session-old": "session-new"}},
                        "decisions": {
                            "orphanPreservedUnmapped": [],
                            "historicalSessionsPreservedUnmapped": [],
                        },
                    }
                )
            )
            path.chmod(0o600)
            self.assertEqual(
                migration.read_identity_map(path, self.original),
                (
                    self.actors,
                    self.sessions,
                    {
                        "orphanPreservedUnmapped": [],
                        "historicalSessionsPreservedUnmapped": [],
                    },
                ),
            )
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "mode 0600"):
                migration.read_identity_map(path, self.original)

    def test_missing_identity_or_namespace_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.json"
            path.write_text(
                json.dumps(
                    {
                        "actors": {},
                        "sessions": {},
                        "decisions": {
                            "orphanPreservedUnmapped": [],
                            "historicalSessionsPreservedUnmapped": [],
                        },
                    }
                )
            )
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "cover every source actor"):
                migration.read_identity_map(path, self.original)
        with self.assertRaisesRegex(ValueError, "unmapped session"):
            migration.mapped_namespace(
                "/summaries/actor-old/session-old/", self.actors, {}
            )

    def test_strategy_mapping_requires_matching_types_names_templates(self):
        source = {
            "strategies": [
                {
                    "strategyId": "old",
                    "name": "Facts",
                    "type": "SEMANTIC",
                    "status": "ACTIVE",
                    "namespaceTemplates": ["/facts/{actorId}/"],
                }
            ]
        }
        target = {
            "strategies": [
                {
                    "strategyId": "new",
                    "name": "Facts",
                    "type": "SEMANTIC",
                    "status": "ACTIVE",
                    "namespaceTemplates": ["/facts/{actorId}/"],
                }
            ]
        }
        self.assertEqual(migration.strategy_map(source, target), {"old": "new"})
        target["strategies"][0]["namespaceTemplates"] = ["/other/{actorId}/"]
        with self.assertRaisesRegex(ValueError, "namespace templates differ"):
            migration.strategy_map(source, target)

    def test_manifest_contains_no_customer_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            migration.write_manifest(
                path,
                {
                    "eventIds": {"event-1": "new-event-1"},
                    "recordIds": {"record-1": "new-record-1"},
                    "sha256": migration.source_snapshot_digest(self.original),
                },
            )
            text = path.read_text()
            self.assertNotIn("private conversation", text)
            self.assertNotIn("private fact", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            migration.replace_manifest(path, {"eventIds": {"event-1": "new-event-2"}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                migration.read_manifest(path)["eventIds"]["event-1"], "new-event-2"
            )
            with self.assertRaises(FileExistsError):
                migration.write_manifest(path, {})


if __name__ == "__main__":
    unittest.main()
