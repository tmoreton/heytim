from __future__ import annotations

import unittest
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
            patch.object(self.routes, "_list_group_messages") as group_messages,
            patch.object(self.routes, "_get_bot"),
            patch.object(self.routes, "_list_turns", return_value=[]),
        ):
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/bots/bot-1/messages",
                {"botId": "bot-1"},
                {},
            )

        self.assertEqual(response["statusCode"], 200)
        group_messages.assert_not_called()

    def test_group_messages_reach_the_group_domain(self) -> None:
        with patch.object(
            self.routes, "_list_group_messages", return_value=[]
        ) as group_messages:
            response = self.routes.route_authenticated(
                "user-1",
                "Tim",
                "GET",
                "/groups/group-1/messages",
                {"groupId": "group-1"},
                {},
            )

        self.assertEqual(response["statusCode"], 200)
        group_messages.assert_called_once_with("user-1", "group-1")

    def test_unknown_authenticated_route_returns_not_found(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self.routes.route_authenticated("user-1", "Tim", "GET", "/unknown", {}, {})

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
