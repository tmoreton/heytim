from __future__ import annotations

import unittest
from pathlib import Path


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = (
            Path(__file__).parents[2] / "backend.ts"
        ).read_text(encoding="utf-8")
        cls.settings = (
            Path(__file__).parents[2] / "infrastructure" / "app-settings.ts"
        ).read_text(encoding="utf-8")
        cls.observability = (
            Path(__file__).parents[2] / "infrastructure" / "observability.ts"
        ).read_text(encoding="utf-8")
        cls.deployment_role = (
            Path(__file__).parents[2] / "infrastructure" / "deployment-role.ts"
        ).read_text(encoding="utf-8")

    def test_worker_concurrency_protects_agentcore_and_is_observed(self) -> None:
        self.assertIn("reservedConcurrentExecutions: WORKER_CONCURRENCY", self.backend)
        self.assertIn("maxConcurrency: WORKER_CONCURRENCY", self.backend)
        self.assertIn("WorkerConcurrencyAlarm", self.observability)

    def test_signed_out_clients_get_no_aws_credentials(self) -> None:
        self.assertIn("cfnIdentityPool.allowUnauthenticatedIdentities = false", self.backend)

    def test_worker_polling_is_explicitly_allowed(self) -> None:
        worker = self.backend.split("const workerFunction =", 1)[1].split("table.grantReadWriteData", 1)[0]
        self.assertIn("recursiveLoop: RecursiveLoop.ALLOW", worker)
        self.assertNotIn("FROGBOT_ALLOW_RECURSIVE_POLLS", self.backend)
        self.assertEqual(worker.count("recursiveLoop:"), 1)

    def test_access_log_5xx_responses_raise_an_alarm(self) -> None:
        self.assertIn("ApiServerErrorMetric", self.observability)
        self.assertIn("FilterPattern.stringValue('$.status', '=', '5*')", self.observability)
        self.assertIn("ApiServerErrorAlarm", self.observability)

    def test_queue_age_alarm_ignores_healthy_inflight_work(self) -> None:
        self.assertIn("expression: 'IF(visible > 0, age, 0)'", self.observability)
        self.assertIn("metric: queueBacklogAge", self.observability)

    def test_catalog_refresh_is_scheduled_off_the_api_path(self) -> None:
        self.assertIn("new Rule(stack, 'CatalogRefresh'", self.backend)
        self.assertIn("{ type: 'CATALOG_REFRESH' }", self.backend)

    def test_api_role_does_not_receive_cognito_delete_permissions(self) -> None:
        permission = (
            "workerFunction.addToRolePolicy(\n"
            "  new PolicyStatement({\n"
            "    actions: ['cognito-idp:AdminDeleteUser'"
        )
        self.assertIn(permission, self.backend)
        self.assertNotIn("for (const fn of [apiFunction, workerFunction])", self.backend)

    def test_function_assets_exclude_tests_and_local_caches(self) -> None:
        for pattern in (
            "tests/**",
            "**/__pycache__/**",
            "**/*.pyc",
            ".pytest_cache/**",
            ".ruff_cache/**",
        ):
            self.assertIn(pattern, self.settings)

    def test_worker_can_make_atomic_usage_admissions_for_runtime_users(self) -> None:
        self.assertIn("dynamodb:TransactWriteItems", self.backend)
        self.assertIn("bedrock-agentcore:InvokeAgentRuntimeForUser", self.backend)
        for setting in (
            "FROGBOT_MONTHLY_RUN_UNIT_LIMIT",
            "FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT",
            "FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT",
            "FROGBOT_USAGE_WINDOW_SECONDS",
            "FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT",
        ):
            self.assertIn(setting, self.backend)

    def test_api_can_admit_new_browser_sessions_with_the_same_limits(self) -> None:
        api = self.backend.split("const apiFunction =", 1)[1].split(
            "const workerFunction =", 1
        )[0]
        for setting in (
            "FROGBOT_MONTHLY_RUN_UNIT_LIMIT",
            "FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT",
            "FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT",
            "FROGBOT_USAGE_WINDOW_SECONDS",
            "FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT",
        ):
            self.assertIn(setting, api)
        self.assertGreaterEqual(self.backend.count("dynamodb:TransactWriteItems"), 2)

    def test_cleanup_roles_can_read_only_scoped_connection_secrets(self) -> None:
        connection_policies = self.backend.split(
            "const connectionSecretsArn =", 1
        )[1].split("jobs.grantSendMessages", 1)[0]
        api_policy = connection_policies.split(
            "apiFunction.addToRolePolicy(", 1
        )[1].split("\n);", 1)[0]
        worker_policy = connection_policies.split(
            "workerFunction.addToRolePolicy(", 1
        )[1].split("\n);", 1)[0]

        for policy in (api_policy, worker_policy):
            self.assertIn("'secretsmanager:GetSecretValue'", policy)
            self.assertIn("resources: [connectionSecretsArn]", policy)

    def test_production_deploy_role_scopes_company_credentials(self) -> None:
        self.assertNotIn("bedrock-agentcore:*", self.deployment_role)
        self.assertIn("bedrock-agentcore:GetTokenVault", self.deployment_role)
        self.assertIn("bedrock-agentcore:CreateApiKeyCredentialProvider", self.deployment_role)
        self.assertIn("bedrock-agentcore:UpdateApiKeyCredentialProvider", self.deployment_role)
        for provider in (
            "FrogBot_OpenRouter",
            "FrogBotXApi",
            "FrogBotYouTubeApi",
        ):
            self.assertIn(provider, self.deployment_role)
        self.assertIn(
            "'aws:ResourceTag/agentcore:project-name': 'FrogBot'",
            self.deployment_role,
        )
        self.assertIn("actions: ['iam:PassRole']", self.deployment_role)
        self.assertIn(
            "AgentCore-FrogBot-product-ApplicationOnlineEval*",
            self.deployment_role,
        )
        self.assertIn(
            "'iam:PassedToService': 'bedrock-agentcore.amazonaws.com'",
            self.deployment_role,
        )


if __name__ == "__main__":
    unittest.main()
