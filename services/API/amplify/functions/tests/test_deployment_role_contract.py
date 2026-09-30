from __future__ import annotations

import unittest
from pathlib import Path


class DeploymentRoleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        infrastructure = Path(__file__).parents[2] / "infrastructure"
        cls.deployment_role = (infrastructure / "deployment-role.ts").read_text(
            encoding="utf-8"
        )
        cls.settings = (infrastructure / "app-settings.ts").read_text(
            encoding="utf-8"
        )

    def test_production_deploy_role_scopes_company_credentials(self) -> None:
        self.assertNotIn("bedrock-agentcore:*", self.deployment_role)
        self.assertIn("bedrock-agentcore:GetTokenVault", self.deployment_role)
        self.assertIn(
            "actions: ['bedrock-agentcore:SetTokenVaultCMK'],\n    resources: ['*'],",
            self.deployment_role,
        )
        self.assertIn("actions: ['kms:CreateKey', 'kms:TagResource']", self.deployment_role)
        self.assertIn(
            "'aws:RequestTag/agentcore:project': 'HeyTim'", self.deployment_role
        )
        self.assertIn("'aws:TagKeys': ['agentcore:project']", self.deployment_role)
        self.assertIn(
            "'aws:ResourceTag/agentcore:project': 'HeyTim'", self.deployment_role
        )
        self.assertIn(
            "resources: [legacyTokenVaultKmsKeyArn]", self.deployment_role
        )
        self.assertIn(
            "optionalKmsKeyArn(\n  'HEYTIM_LEGACY_TOKEN_VAULT_KMS_KEY_ARN'",
            self.settings,
        )
        self.assertIn(
            "`bedrock-agentcore-identity.${stack.region}.amazonaws.com`",
            self.deployment_role,
        )
        self.assertIn("'kms:GenerateDataKeyWithoutPlaintext'", self.deployment_role)
        self.assertIn(
            "kms:EncryptionContext:aws-crypto-ec:aws:bedrock-agentcore-identity:token-vault-arn",
            self.deployment_role,
        )
        self.assertIn(
            "bedrock-agentcore:CreateApiKeyCredentialProvider", self.deployment_role
        )
        self.assertIn(
            "bedrock-agentcore:UpdateApiKeyCredentialProvider", self.deployment_role
        )
        for provider in (
            "HeyTim_OpenRouter",
            "HeyTimXApi",
            "HeyTimYouTubeApi",
        ):
            self.assertIn(provider, self.deployment_role)
        for action in (
            "secretsmanager:CreateSecret",
            "secretsmanager:GetSecretValue",
            "secretsmanager:PutSecretValue",
        ):
            self.assertIn(action, self.deployment_role)
        self.assertIn(
            "bedrock-agentcore-identity!default/apikey/${name}-*",
            self.deployment_role,
        )
        self.assertNotIn("secretsmanager:DeleteSecret", self.deployment_role)
        self.assertIn(
            "'aws:ResourceTag/agentcore:project-name': 'HeyTim'",
            self.deployment_role,
        )
        self.assertIn("actions: ['iam:PassRole']", self.deployment_role)
        self.assertIn(
            "AgentCore-HeyTim-product-ApplicationOnlineEval*",
            self.deployment_role,
        )
        self.assertIn(
            "'iam:PassedToService': 'bedrock-agentcore.amazonaws.com'",
            self.deployment_role,
        )
        self.assertIn("nativePushFeedbackRoleArn", self.deployment_role)
        self.assertIn(
            "'iam:PassedToService': 'sns.amazonaws.com'",
            self.deployment_role,
        )


if __name__ == "__main__":
    unittest.main()
