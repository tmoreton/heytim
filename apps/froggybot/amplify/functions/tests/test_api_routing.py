from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import test_api_safety


class ApiRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "handler"):
            base.setUpClass()
        cls.handler = base.handler
        cls.support = base.support
        cls.routes = base.handler.authenticated_routes

    def test_bot_messages_do_not_match_group_routes(self) -> None:
        with (
            patch.object(self.routes, "_list_group_message_page") as group_messages,
            patch.object(self.routes, "_get_bot"),
            patch.object(self.routes, "_list_turn_page", return_value=([], None)),
        ):
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/bots/bot-1/messages",
                {"botId": "bot-1"},
                {},
                route_key="GET /bots/{botId}/messages",
            )

        self.assertEqual(response["statusCode"], 200)
        group_messages.assert_not_called()

    def test_group_messages_reach_the_group_domain(self) -> None:
        with patch.object(
            self.routes, "_list_group_message_page", return_value=([], None)
        ) as group_messages:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/groups/group-1/messages",
                {"groupId": "group-1"},
                {},
                route_key="GET /groups/{groupId}/messages",
            )

        self.assertEqual(response["statusCode"], 200)
        group_messages.assert_called_once_with("user-1", "group-1", None)

    def test_message_cursor_is_forwarded_to_the_scoped_query(self) -> None:
        with patch.object(
            self.routes, "_list_group_message_page", return_value=([], "next")
        ) as group_messages:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/groups/group-1/messages",
                {"groupId": "group-1"},
                {"queryStringParameters": {"cursor": "opaque"}},
                route_key="GET /groups/{groupId}/messages",
            )

        self.assertIn('"nextToken":"next"', response["body"])
        group_messages.assert_called_once_with("user-1", "group-1", "opaque")

    def test_message_cursor_is_opaque_and_partition_scoped(self) -> None:
        token = self.support._encode_page_cursor(
            {"pk": "ignored", "sk": "TURN#2026-09-11#turn-1"}
        )
        self.assertEqual(
            self.support._decode_page_cursor(token, "TURN#user#bot", "TURN#"),
            {"pk": "TURN#user#bot", "sk": "TURN#2026-09-11#turn-1"},
        )
        with self.assertRaises(self.support.ApiError):
            self.support._decode_page_cursor(token, "GROUP#one", "MESSAGE#")

    def test_group_memory_reaches_the_scoped_memory_domain(self) -> None:
        snapshot = {"records": [], "rawConversationRetentionDays": 30}
        with patch.object(
            self.routes, "_list_group_memories", return_value=snapshot
        ) as memories:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/groups/group-1/memory",
                {"groupId": "group-1"},
                {},
                route_key="GET /groups/{groupId}/memory",
            )

        self.assertEqual(response["statusCode"], 200)
        memories.assert_called_once_with("user-1", "group-1")

    def test_group_decision_reaches_the_room_outcome_domain(self) -> None:
        saved = {"id": "decision-1"}
        with patch.object(
            self.routes, "_save_group_decision", return_value=saved
        ) as save:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "POST",
                "/groups/group-1/decisions",
                {"groupId": "group-1"},
                {"body": '{"messageId":"message-1"}'},
                route_key="POST /groups/{groupId}/decisions",
            )

        self.assertEqual(response["statusCode"], 201)
        save.assert_called_once_with(
            "user-1", "Tim", "group-1", {"messageId": "message-1"}
        )

    def test_schedule_runs_reach_the_run_inbox(self) -> None:
        with patch.object(
            self.routes, "_list_schedule_runs", return_value=[]
        ) as runs:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/bots/bot-1/runs",
                {"botId": "bot-1"},
                {},
                route_key="GET /bots/{botId}/runs",
            )

        self.assertEqual(response["statusCode"], 200)
        runs.assert_called_once_with("user-1", "bot-1")

    def test_bot_documents_reach_the_authenticated_bot_library(self) -> None:
        with (
            patch.object(self.routes, "_get_bot") as get_bot,
            patch.object(
                self.routes, "_list_bot_documents", return_value=[]
            ) as list_documents,
        ):
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/bots/bot-1/documents",
                {"botId": "bot-1"},
                {},
                route_key="GET /bots/{botId}/documents",
            )

        self.assertEqual(response["statusCode"], 200)
        get_bot.assert_called_once_with("user-1", "bot-1")
        list_documents.assert_called_once_with("user-1", "bot-1")

    def test_bot_template_install_reaches_the_bot_domain(self) -> None:
        installed = {"id": "installed-bot", "templateId": "decision-coach"}
        with patch.object(
            self.routes, "_install_bot_template", return_value=installed
        ) as install:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "POST",
                "/bot-templates/decision-coach/install",
                {"templateId": "decision-coach"},
                {},
                route_key="POST /bot-templates/{templateId}/install",
            )

        self.assertEqual(response["statusCode"], 201)
        install.assert_called_once_with("user-1", "decision-coach")

    def test_unknown_authenticated_route_returns_not_found(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/unknown",
                {},
                {},
                route_key="GET /unknown",
            )

        self.assertEqual(error.exception.status_code, 404)

    def test_public_catalog_keeps_its_short_cache_policy(self) -> None:
        with patch.object(
            self.handler.catalog, "public_catalog", return_value={"skills": []}
        ):
            response = self.handler._public_route({}, "GET", "/public/catalog", {})

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            response["headers"]["cache-control"],
            "public, max-age=60, stale-while-revalidate=300",
        )

    def test_python_dispatch_matches_the_infrastructure_route_manifest(self) -> None:
        source = (
            Path(__file__).parents[2] / "infrastructure" / "api-routes.ts"
        ).read_text(encoding="utf-8")
        infrastructure_keys = {
            f"{method} {path}"
            for method, path in re.findall(
                r"\[HttpMethod\.([A-Z]+), '([^']+)'\]", source
            )
        }

        self.assertEqual(
            self.routes.AUTHENTICATED_ROUTE_KEYS,
            infrastructure_keys,
        )
