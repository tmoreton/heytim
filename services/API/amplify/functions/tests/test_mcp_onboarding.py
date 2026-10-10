from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock, patch

import test_catalog as fixtures
from shared.action_grants import effective_allowed_interactive_tool_ids
from shared.catalog_rules import CatalogError
from shared.mcp_discovery import (
    MCPDiscovery,
    PublicHTTPSConnection,
    discover_mcp_server,
    tool_digest,
)

TOOL = {"name": "read_state", "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}


class MCPDiscoveryTests(unittest.TestCase):
    def discovery(self):
        with patch("shared.mcp_discovery._validate_mcp_endpoint", return_value="https://example.com/mcp"):
            return MCPDiscovery("https://example.com/mcp", "test-token")

    def response(self, payload, status=200, content_type="application/json"):
        response = Mock()
        response.status = status
        response.read1 = io.BytesIO(json.dumps(payload).encode()).read1
        response.getheader.side_effect = lambda key, default=None: (
            content_type if key == "Content-Type" else default)
        return response

    def test_initialize_and_list_only_never_calls_business_tools(self):
        discovery = self.discovery()
        discovery.post = Mock(side_effect=[
            {"protocolVersion": "2025-11-25", "serverInfo": {"name": "Example", "version": "1"}},
            {}, {"tools": [TOOL]},
        ])
        result = discovery.discover()
        self.assertEqual(result["tools"][0]["digest"], tool_digest(TOOL))
        self.assertEqual([call.args[0] for call in discovery.post.call_args_list],
                         ["initialize", "notifications/initialized", "tools/list"])

    def test_repeated_cursor_and_duplicate_tools_are_rejected(self):
        for pages in [
            [{"tools": [], "nextCursor": "same"}] * 2,
            [{"tools": [TOOL, TOOL]}],
            [{"tools": [TOOL] * 101}],
        ]:
            discovery = self.discovery()
            discovery.post = Mock(side_effect=[{"protocolVersion": "2025-11-25"}, {}, *pages])
            with self.assertRaises(CatalogError):
                discovery.discover()

    def test_auth_redirect_html_and_mismatched_id_errors_are_sanitized(self):
        for response in [
            self.response({"secret": "private"}, status=401),
            self.response({}, status=302),
            self.response({}, content_type="text/html"),
            self.response({"jsonrpc": "2.0", "id": 3, "result": {}}),
        ]:
            connection = Mock()
            connection.getresponse.return_value = response
            with patch("shared.mcp_discovery.PublicHTTPSConnection", return_value=connection), \
                    self.assertRaises(CatalogError) as error:
                self.discovery().post("initialize", {}, 1)
            self.assertNotIn("private", str(error.exception))
            connection.close.assert_called_once()

    def test_sse_handles_notifications_before_matching_result(self):
        response = self.response({}, content_type="text/event-stream")
        response.read1 = io.BytesIO(
            b'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        ).read1
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("shared.mcp_discovery.PublicHTTPSConnection", return_value=connection):
            self.assertEqual(self.discovery().post("tools/list", {}, 1), {"tools": []})

    def test_pinned_connection_rejects_private_second_resolution(self):
        connection = PublicHTTPSConnection("example.com")
        with patch("shared.mcp_discovery.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("127.0.0.1", 443))
        ]), patch("shared.mcp_discovery.socket.create_connection") as connect:
            with self.assertRaises(CatalogError):
                connection.connect()
            connect.assert_not_called()

    def test_pinned_connection_preserves_original_tls_hostname(self):
        context = Mock()
        connection = PublicHTTPSConnection("example.com", context=context)
        with patch("shared.mcp_discovery.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]), patch("shared.mcp_discovery.socket.create_connection") as connect:
            connection.connect()
            self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
            self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "example.com")

    def test_failed_probe_releases_its_temporary_protocol_session(self):
        discovery = self.discovery()
        discovery.session = "session-123"
        connection = Mock()
        # Cleanup failure must preserve the original discovery error.
        connection.getresponse.side_effect = OSError("server closed")
        with patch("shared.mcp_discovery.MCPDiscovery", return_value=discovery), \
                patch.object(discovery, "discover", side_effect=CatalogError("invalid tools")), \
                patch("shared.mcp_discovery.PublicHTTPSConnection", return_value=connection), \
                self.assertRaisesRegex(CatalogError, "invalid tools"):
            discover_mcp_server("https://example.com/mcp", "test-token")
        self.assertEqual(connection.request.call_args.args, ("DELETE", "/mcp"))
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Mcp-Session-Id"], "session-123")
        connection.close.assert_called_once()
        self.assertIsNone(discovery.session)


class MCPConnectionReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CatalogServiceTests()
        self.fixture.setUp()
        self.catalog = self.fixture.catalog

    def save(self, approved):
        discovery = {"serverName": "Test", "tools": [{"name": "read_state", "digest": tool_digest(TOOL)}]}
        with patch("shared.mcp_servers._validate_mcp_endpoint", return_value="https://example.com/mcp"), \
                patch("shared.mcp_servers.discover_mcp_server", return_value=discovery):
            return self.catalog.save_mcp_server_connection(
                "owner", "Test", "https://example.com/mcp", "t" * 48, approved_tools=approved)

    def test_review_survives_resolution_without_exposing_credentials(self):
        allowed = {"read_state": tool_digest(TOOL)}
        saved = self.save(allowed)
        self.assertEqual(saved["connectionStatus"], "tested")
        self.assertNotIn("t" * 48, repr(saved))
        resolved = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])
        self.assertEqual(resolved[0]["runtime"]["approvedTools"], allowed)
        self.assertTrue(resolved[0]["runtime"]["requireActionApproval"])
        self.assertEqual(self.catalog.resolve_tools_for_runtime("another-user", [saved["id"]]), [])

    def test_changed_schema_cannot_be_saved_with_stale_review(self):
        with self.assertRaisesRegex(CatalogError, "changed"):
            self.save({"read_state": "f" * 64})
        self.assertFalse(self.fixture.secrets.values)

    def test_automatic_bot_still_requires_explicit_custom_connection_grant(self):
        saved = self.save({"read_state": tool_digest(TOOL)})
        bot = {"toolIds": [saved["id"]], "actionApprovalMode": "automatic", "alwaysAllowedToolIds": []}
        self.assertEqual(effective_allowed_interactive_tool_ids(bot, self.catalog, "owner"), [])
        bot["alwaysAllowedToolIds"] = [saved["id"]]
        self.assertEqual(effective_allowed_interactive_tool_ids(bot, self.catalog, "owner"), [saved["id"]])

    def test_anonymous_connection_uses_no_secrets_manager_record_and_can_reconnect(self):
        discovery = {"serverName": "Public", "tools": [{"name": "read_state", "digest": tool_digest(TOOL)}]}
        with patch("shared.mcp_servers._validate_mcp_endpoint", return_value="https://example.com/mcp"), \
                patch("shared.mcp_servers.discover_mcp_server", return_value=discovery):
            first = self.catalog.save_mcp_server_connection(
                "owner", "Public", "https://example.com/mcp", None, auth_type="none",
                approved_tools={"read_state": tool_digest(TOOL)})
            second = self.catalog.save_mcp_server_connection(
                "owner", "Public renamed", "https://example.com/mcp", None, auth_type="none",
                approved_tools={"read_state": tool_digest(TOOL)})
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(self.fixture.secrets.values)
        resolved = self.catalog.resolve_tools_for_runtime("owner", [first["id"]])
        self.assertEqual(resolved[0]["runtime"]["authType"], "none")
        self.assertNotIn("secretArn", resolved[0]["runtime"])
        self.assertNotIn("credentialDeletionWindowDays", self.catalog.delete_connection("owner", first["id"]))

    def test_anonymous_reconnect_retries_after_concurrent_permission_update(self):
        discovery = {"serverName": "Public", "tools": [{"name": "read_state", "digest": tool_digest(TOOL)}]}
        expected_markers = []
        real_put = self.catalog._put_connection_while_account_active

        def concurrent_put(owner, item, **kwargs):
            expected_markers.append(kwargs["expected_secret_arn"])
            if len(expected_markers) == 1:
                current = self.catalog._get_connection(owner, item["id"])
                self.fixture.table.put_item(Item={**current, "secretArn": "anonymous:" + "f" * 32})
            return real_put(owner, item, **kwargs)

        with patch("shared.mcp_servers._validate_mcp_endpoint", return_value="https://example.com/mcp"), \
                patch("shared.mcp_servers.discover_mcp_server", return_value=discovery):
            arguments = ("owner", "Public", "https://example.com/mcp", None)
            options = {"auth_type": "none", "approved_tools": {"read_state": tool_digest(TOOL)}}
            first = self.catalog.save_mcp_server_connection(*arguments, **options)
            original = self.catalog._get_connection("owner", first["id"])["secretArn"]
            with patch.object(self.catalog, "_put_connection_while_account_active", side_effect=concurrent_put):
                self.catalog.save_mcp_server_connection(*arguments, **options)
        self.assertEqual(expected_markers, [original, "anonymous:" + "f" * 32])
        current = self.catalog._get_connection("owner", first["id"])["secretArn"]
        self.assertNotIn(current, expected_markers)
        self.assertFalse(self.fixture.secrets.values)
