from __future__ import annotations

import json
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

    def test_github_skill_scan_uses_its_own_route(self) -> None:
        found = {"repository": "mattpocock/skills", "reference": "main", "skills": [], "moreAvailable": False}
        with patch.object(self.routes, "scan_github_skills", return_value=found) as scan:
            response = self.routes.route_authenticated(
                "user-1", "Tim", "POST", "/skills/github/scan", {},
                {"body": '{"url":"https://github.com/mattpocock/skills"}'},
                route_key="POST /skills/github/scan",
            )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), found)
        scan.assert_called_once_with({"url": "https://github.com/mattpocock/skills"})

    def test_bot_memory_routes_to_bot_scope(self) -> None:
        snapshot = {"records": [], "rawConversationRetentionDays": 30}
        with patch.object(
            self.routes, "_list_bot_memories", return_value=snapshot
        ) as list_bot_memory:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/bots/bot-1/memory",
                {"botId": "bot-1"},
                {},
                route_key="GET /bots/{botId}/memory",
            )

        self.assertEqual(json.loads(response["body"]), snapshot)
        list_bot_memory.assert_called_once_with("user-1", "bot-1")

    def test_connection_authorization_dispatches_from_the_provider_route(self) -> None:
        authorization = {"authorizationUrl": "https://accounts.example/authorize"}
        with patch.object(
            self.routes,
            "_begin_connection_authorization",
            return_value=authorization,
        ) as begin:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "POST",
                "/connections/gmail/authorization",
                {"providerId": "gmail"},
                {"body": '{"returnUrl":"heytim://app"}'},
                route_key="POST /connections/{providerId}/authorization",
            )

        self.assertEqual(json.loads(response["body"]), authorization)
        begin.assert_called_once_with(
            "user-1", "gmail", {"returnUrl": "heytim://app"}
        )

    def test_home_assistant_connect_uses_authenticated_connection_route(self) -> None:
        connected = {"id": "connection_home", "name": "Home Assistant"}
        payload = {"instanceUrl": "https://home.example.com", "accessToken": "a" * 48}
        with patch.object(
            self.routes, "_connect_home_assistant", return_value=connected
        ) as connect:
            response = self.routes.route_authenticated(
                "user-1", "Tim", "POST", "/connections/home-assistant", {},
                {"body": json.dumps(payload)},
                route_key="POST /connections/home-assistant",
            )
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"]), connected)
        connect.assert_called_once_with("user-1", payload)

    def test_mcp_server_rename_uses_authenticated_connection_route(self) -> None:
        renamed = {"id": "connection_" + "a" * 20, "name": "Office"}
        with patch.object(self.routes, "_rename_mcp_server", return_value=renamed) as rename:
            response = self.routes.route_authenticated(
                "user-1", "Tim", "PATCH", "/connections/" + renamed["id"],
                {"connectionId": renamed["id"]}, {"body": '{"name":"Office"}'},
                route_key="PATCH /connections/{connectionId}",
            )
        self.assertEqual(response["statusCode"], 200)
        rename.assert_called_once_with("user-1", renamed["id"], {"name": "Office"})

    def test_desktop_action_record_does_not_dispatch_normal_bot_send(self) -> None:
        recorded = {"recorded": True}
        with (
            patch.object(self.routes, "_record_desktop_action", return_value=recorded) as record,
            patch.object(self.routes, "_send_message") as send,
        ):
            response = self.routes.route_authenticated(
                "user-1", "Tim", "POST", "/bots/bot-1/desktop-actions",
                {"botId": "bot-1"}, {"body": '{"actionId":"one"}'},
                route_key="POST /bots/{botId}/desktop-actions",
            )
        self.assertEqual(response["statusCode"], 201)
        record.assert_called_once_with("user-1", "bot-1", {"actionId": "one"})
        send.assert_not_called()

    def test_mcp_server_connect_uses_authenticated_connection_route(self) -> None:
        connected = {"id": "connection_mcp", "name": "MCP server"}
        payload = {"name": "Planning", "url": "https://planning.example.com/mcp", "accessToken": "p" * 48}
        with patch.object(
            self.routes, "_connect_mcp_server", return_value=connected
        ) as connect:
            response = self.routes.route_authenticated(
                "user-1", "Tim", "POST", "/connections/mcp-servers", {},
                {"body": json.dumps(payload)},
                route_key="POST /connections/mcp-servers",
            )
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"]), connected)
        connect.assert_called_once_with("user-1", payload)

    def test_api_errors_expose_stable_codes(self) -> None:
        self.assertEqual(self.support.ApiError(409, "Changed").code, "conflict")
        custom = self.support.ApiError(
            409, "Changed", code="browser_state_changed"
        )
        self.assertEqual(custom.code, "browser_state_changed")

        response = self.handler.handler(
            {
                "rawPath": "/bootstrap",
                "requestContext": {
                    "routeKey": "GET /bootstrap",
                    "http": {"method": "GET"},
                },
            },
            None,
        )
        self.assertEqual(
            json.loads(response["body"])["code"], "authentication_required"
        )

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

    def test_custom_connection_write_routes_are_not_exposed(self) -> None:
        for method, path, route_key, params in (
            ("POST", "/connections", "POST /connections", {}),
            (
                "PUT",
                "/connections/legacy-1",
                "PUT /connections/{connectionId}",
                {"connectionId": "legacy-1"},
            ),
        ):
            with self.subTest(route_key=route_key):
                with self.assertRaises(self.support.ApiError) as error:
                    self.routes.route_authenticated(
                        "user-1",
                        "Tim",
                        method,
                        path,
                        params,
                        {"body": '{}'},
                        route_key=route_key,
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
        contract = json.loads(
            (Path(__file__).parents[1] / "api" / "api-contract.json").read_text()
        )
        infrastructure_keys = {
            f"{route['method']} {route['path']}"
            for route in contract["routes"]
            if route["access"] == "authenticated"
        }

        self.assertEqual(
            self.routes.AUTHENTICATED_ROUTE_KEYS,
            infrastructure_keys,
        )
