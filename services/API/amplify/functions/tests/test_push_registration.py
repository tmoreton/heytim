from __future__ import annotations

import os
from unittest.mock import patch

from api_test_case import ApiTestCase


class PushRegistrationTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.apns_token = "ab" * 32
        self.application_arn = (
            "arn:aws:sns:us-east-1:123456789012:app/APNS_SANDBOX/FroggyBot"
        )
        self.endpoint_arn = (
            "arn:aws:sns:us-east-1:123456789012:"
            "endpoint/APNS_SANDBOX/FroggyBot/device"
        )

    def test_legacy_expo_registration_remains_compatible(self):
        result = self.sharing._register_push_token(
            "user-1", {"token": "ExpoPushToken[valid_1]"}
        )
        self.assertEqual(result, {"registered": True})
        item = next(
            item
            for item in self.data_table.items.values()
            if item.get("entity") == "PUSH_TOKEN"
        )
        self.assertEqual(item["provider"], "expo")
        self.assertEqual(item["expoPushToken"], "ExpoPushToken[valid_1]")
        self.sns.create_platform_endpoint.assert_not_called()

    def test_apns_registration_creates_and_persists_an_sns_endpoint(self):
        self.sns.create_platform_endpoint.return_value = {
            "EndpointArn": self.endpoint_arn
        }
        with patch.dict(
            os.environ, {"APNS_SANDBOX_PLATFORM_APPLICATION_ARN": self.application_arn}
        ):
            result = self.sharing._register_push_token(
                "user-1",
                {
                    "provider": "apns",
                    "token": self.apns_token.upper(),
                    "platform": "ios",
                    "environment": "sandbox",
                },
            )
        self.assertEqual(result, {"registered": True})
        self.sns.create_platform_endpoint.assert_called_once_with(
            PlatformApplicationArn=self.application_arn,
            Token=self.apns_token,
            CustomUserData=self.support._push_token_id(self.apns_token, "apns"),
        )
        self.sns.set_endpoint_attributes.assert_called_once_with(
            EndpointArn=self.endpoint_arn,
            Attributes={"Enabled": "true", "Token": self.apns_token},
        )
        item = next(
            item
            for item in self.data_table.items.values()
            if item.get("entity") == "PUSH_TOKEN"
        )
        self.assertEqual(item["provider"], "apns")
        self.assertEqual(item["platform"], "ios")
        self.assertEqual(item["environment"], "sandbox")
        self.assertEqual(item["endpointArn"], self.endpoint_arn)

    def test_apns_unregister_needs_only_provider_and_token(self):
        token_id = self.support._push_token_id(self.apns_token, "apns")
        token_key = self.support._push_token_key("user-1", token_id)
        owner_key = self.support._push_owner_key(token_id)
        self.data_table.items[(token_key["pk"], token_key["sk"])] = {
            **token_key,
            "endpointArn": self.endpoint_arn,
        }
        self.data_table.items[(owner_key["pk"], owner_key["sk"])] = {
            **owner_key,
            "userId": "user-1",
        }
        result = self.sharing._unregister_push_token(
            "user-1", {"provider": "apns", "token": self.apns_token}
        )
        self.assertEqual(result, {"registered": False})
        self.assertNotIn((token_key["pk"], token_key["sk"]), self.data_table.items)
        self.assertNotIn((owner_key["pk"], owner_key["sk"]), self.data_table.items)
        self.sns.delete_endpoint.assert_called_once_with(EndpointArn=self.endpoint_arn)

    def test_invalid_native_metadata_is_rejected_before_sns(self):
        with self.assertRaises(self.support.ApiError):
            self.sharing._register_push_token(
                "user-1",
                {
                    "provider": "apns",
                    "token": self.apns_token,
                    "platform": "android",
                    "environment": "sandbox",
                },
            )
        self.sns.create_platform_endpoint.assert_not_called()
