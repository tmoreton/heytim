from __future__ import annotations

import unittest
from unittest.mock import patch


class BrowserSdkTests(unittest.TestCase):
    def test_aws_shapes_signing_and_bounds_with_real_sdk(self):
        try:
            import boto3
            from botocore.credentials import Credentials
            from botocore.validate import validate_parameters
        except ImportError:
            self.skipTest("Run with services/runtime/.venv/bin/python for real SDK contract checks")
        from urllib.parse import parse_qs, urlsplit

        from shared.browser_session_aws import live_view_url
        from shared.browser_sessions import managed_session_name
        client = boto3.client("bedrock-agentcore", region_name="us-east-1",
                              aws_access_key_id="TEST", aws_secret_access_key="TEST")
        request = {"browserIdentifier": "aws.browser.v1", "sessionTimeoutSeconds": 3600,
                   "name": managed_session_name("user-1", "bot-1"), "clientToken": "a" * 36,
                   "profileConfiguration": {"profileIdentifier": "frogbot_test-0123456789"}}
        validate_parameters(request, client.meta.service_model.operation_model("StartBrowserSession").input_shape)
        validate_parameters({"browserIdentifier": "aws.browser.v1", "sessionId": "session1",
                             "streamUpdate": {"automationStreamUpdate": {"streamStatus": "DISABLED"}}},
                            client.meta.service_model.operation_model("UpdateBrowserStream").input_shape)
        validate_parameters({"browserIdentifier": "aws.browser.v1", "sessionId": "session1",
                             "profileIdentifier": "frogbot_test-0123456789", "clientToken": "a" * 36},
                            client.meta.service_model.operation_model("SaveBrowserSessionProfile").input_shape)
        control = boto3.client("bedrock-agentcore-control", region_name="us-east-1",
                               aws_access_key_id="TEST", aws_secret_access_key="TEST")
        validate_parameters({"name": "frogbot_test", "tags": {"frogbot:managed-by": "FrogBot"},
                             "clientToken": "a" * 36},
                            control.meta.service_model.operation_model("CreateBrowserProfile").input_shape)
        with patch.object(boto3, "Session") as session:
            session.return_value.get_credentials.return_value = Credentials("TEST", "TEST", "TESTTOKEN")
            url = live_view_url(client, "session1")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["X-Amz-Expires"], ["300"])
        self.assertEqual(query["X-Amz-SignedHeaders"], ["host"])
        self.assertEqual(query["X-Amz-Security-Token"], ["TESTTOKEN"])
        self.assertEqual(urlsplit(url).path, "/browser-streams/aws.browser.v1/sessions/session1/live-view")
        self.assertIn("/us-east-1/bedrock-agentcore/aws4_request", query["X-Amz-Credential"][0])
