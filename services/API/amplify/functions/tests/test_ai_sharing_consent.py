from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api_test_case import ApiTestCase
from shared.ai_consent import (
    ConsentRequired,
    active_grant,
    consent_status,
    fence_key,
    group_subject_ids,
    set_consent,
)
from worker_test_case import WorkerTestCase


class FakeConsentTable:
    class ConditionalCheckFailedException(Exception):
        pass

    def __init__(self) -> None:
        self.state = {"pk": "USER#owner", "sk": "STATE", "entity": "USER_STATE"}
        self.events: list[str] = []
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=self.ConditionalCheckFailedException
                )
            )
        )

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        return {"Item": dict(self.state)} if Key["pk"] == "USER#owner" else {}

    def update_item(self, *, UpdateExpression: str, ExpressionAttributeValues=None, **_kwargs) -> None:
        values = ExpressionAttributeValues or {}
        if "aiConsentMutationOwner = :owner" in UpdateExpression:
            if "aiConsentMutationOwner" in self.state:
                raise self.ConditionalCheckFailedException
            self.state["aiConsentMutationOwner"] = values[":owner"]
            self.state["aiConsentMutationExpiresAt"] = values[":expires"]
            self.events.append("lease")
        elif "aiSharingConsent = :consent" in UpdateExpression:
            self.state["aiSharingConsent"] = values[":consent"]
            self.events.append("state")
        else:
            self.state.pop("aiConsentMutationOwner", None)
            self.state.pop("aiConsentMutationExpiresAt", None)
            self.events.append("release")


class FakeConsentS3:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[str, bytes] = {}
        self.events = events

    def put_object(self, *, Key: str, Body: bytes, **_kwargs) -> None:
        self.items[Key] = Body
        self.events.append("fence")

    def get_object(self, *, Key: str, **_kwargs) -> dict:
        if Key not in self.items:
            # A missing fence must never create permission.
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.items[Key])}


class AIConsentStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeConsentTable()
        self.s3 = FakeConsentS3(self.table.events)

    def test_existing_account_defaults_to_denied_and_mutations_are_ordered(self) -> None:
        self.assertEqual(
            consent_status(self.table, self.s3, "files", "owner"),
            {"version": 1, "granted": False},
        )
        with self.assertRaises(ConsentRequired):
            active_grant(self.table, self.s3, "files", "owner")

        self.assertTrue(set_consent(self.table, self.s3, "files", "owner", True)["granted"])
        self.assertEqual(self.table.events, ["lease", "state", "fence", "release"])
        grant = active_grant(self.table, self.s3, "files", "owner")
        self.assertEqual(len(grant["actorId"]), 64)

        self.table.events.clear()
        self.assertFalse(set_consent(self.table, self.s3, "files", "owner", False)["granted"])
        self.assertEqual(self.table.events, ["lease", "fence", "state", "release"])
        with self.assertRaises(ConsentRequired):
            active_grant(self.table, self.s3, "files", "owner")

    def test_stale_fence_and_interrupted_grant_fail_closed(self) -> None:
        set_consent(self.table, self.s3, "files", "owner", True)
        self.s3.items[fence_key("owner")] = json.dumps(
            {"version": 1, "granted": False, "epoch": "revoked"}
        ).encode()
        with self.assertRaises(ConsentRequired):
            active_grant(self.table, self.s3, "files", "owner")
        self.table.state["aiConsentMutationOwner"] = "incomplete"
        with self.assertRaises(ConsentRequired):
            active_grant(self.table, self.s3, "files", "owner")

    def test_room_requires_historical_authors_and_known_bot_owners(self) -> None:
        class RoomTable:
            def __init__(self):
                self.items = [
                    {"sk": "META", "ownerId": "owner"},
                    {"entity": "GROUP_USER", "userId": "member"},
                    {"entity": "GROUP_MESSAGE", "authorType": "user", "authorId": "former"},
                    {"entity": "GROUP_MESSAGE", "authorType": "bot", "authorId": "bot-old", "botOwnerId": "bot-owner"},
                    {"entity": "GROUP_DECISION", "createdById": "decision-author"},
                ]

            def query(self, **_kwargs):
                return {"Items": self.items}

        room = RoomTable()
        self.assertEqual(
            group_subject_ids(room, "room"),
            {"owner", "member", "former", "bot-owner", "decision-author"},
        )
        room.items[2].pop("authorId")
        with self.assertRaises(ConsentRequired):
            group_subject_ids(room, "room")


class AIConsentAPIGateTests(ApiTestCase):
    def test_direct_send_denies_before_bot_or_queue_access(self) -> None:
        with (
            patch.object(
                self.direct_chat, "require_request_consent",
                side_effect=self.support.ApiError(409, "Allow AI processing"),
            ),
            patch.object(self.direct_chat, "_get_bot") as get_bot,
            self.assertRaises(self.support.ApiError),
        ):
            self.direct_chat._send_message("owner", "bot", {"text": "private"})
        get_bot.assert_not_called()
        self.sqs.send_message.assert_not_called()


class AIConsentWorkerGateTests(WorkerTestCase):
    def test_every_worker_invocation_requires_an_active_grant_before_dispatch(self) -> None:
        with patch.object(
            self.agent, "grants_for_job", side_effect=ConsentRequired("Permission required")
        ), self.assertRaises(ConsentRequired):
            self.agent._invoke(
                "owner", "bot", {"name": "Bot", "prompt": "Help"},
                history=[], event_id="turn",
            )
        self.agentcore.invoke_agent_runtime.assert_not_called()

    def test_group_context_without_verified_provenance_is_denied(self) -> None:
        with patch.object(
            self.agent, "grants_for_job", self.real_grants_for_job
        ), self.assertRaises(ConsentRequired):
            self.agent._invoke(
                "owner", "bot", {"name": "Bot", "prompt": "Help"},
                history=[], event_id="reply", group_context={"name": "Room"},
            )
        self.agentcore.invoke_agent_runtime.assert_not_called()
