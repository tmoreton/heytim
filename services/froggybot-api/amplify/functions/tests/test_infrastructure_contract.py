from __future__ import annotations

import unittest
from pathlib import Path


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = (Path(__file__).parents[2] / "backend.ts").read_text(
            encoding="utf-8"
        )
        cls.settings = (
            Path(__file__).parents[2] / "infrastructure" / "app-settings.ts"
        ).read_text(encoding="utf-8")
        cls.observability = (
            Path(__file__).parents[2] / "infrastructure" / "observability.ts"
        ).read_text(encoding="utf-8")
        cls.native_push = (
            Path(__file__).parents[2] / "infrastructure" / "native-push.ts"
        ).read_text(encoding="utf-8")
        cls.memory_access = (
            Path(__file__).parents[2] / "infrastructure" / "memory-access.ts"
        ).read_text(encoding="utf-8")
        cls.production_readiness = (
            Path(__file__).parents[2] / "infrastructure" / "production-readiness.ts"
        ).read_text(encoding="utf-8")
        cls.deployment_role = (
            Path(__file__).parents[2] / "infrastructure" / "deployment-role.ts"
        ).read_text(encoding="utf-8")
        cls.provider_connections = (
            Path(__file__).parents[2] / "infrastructure" / "provider-connections.ts"
        ).read_text(encoding="utf-8")
        cls.autofix = (
            Path(__file__).parents[2] / "infrastructure" / "autofix.ts"
        ).read_text(encoding="utf-8")
        cls.production_workflow = (
            Path(__file__).parents[5] / ".github" / "workflows" / "aws-production.yml"
        ).read_text(encoding="utf-8")
        cls.autofix_workflow = (
            Path(__file__).parents[5] / ".github" / "workflows" / "autofix.yml"
        ).read_text(encoding="utf-8")
        cls.production_verifier = (
            Path(__file__).parents[5] / "scripts" / "verify-production-deployment.sh"
        ).read_text(encoding="utf-8")

    def test_worker_concurrency_protects_agentcore_and_is_observed(self) -> None:
        self.assertIn("reservedConcurrentExecutions: WORKER_CONCURRENCY", self.backend)
        self.assertIn("maxConcurrency: WORKER_CONCURRENCY", self.backend)
        self.assertIn("WorkerConcurrencyAlarm", self.observability)

    def test_signed_out_clients_get_no_aws_credentials(self) -> None:
        self.assertIn(
            "cfnIdentityPool.allowUnauthenticatedIdentities = false", self.backend
        )

    def test_worker_polling_is_explicitly_allowed(self) -> None:
        worker = self.backend.split("const workerFunction =", 1)[1].split(
            "table.grantReadWriteData", 1
        )[0]
        self.assertIn("recursiveLoop: RecursiveLoop.ALLOW", worker)
        self.assertNotIn("FROGBOT_ALLOW_RECURSIVE_POLLS", self.backend)
        self.assertEqual(worker.count("recursiveLoop:"), 1)

    def test_access_log_5xx_responses_raise_an_alarm(self) -> None:
        self.assertIn("ApiServerErrorMetric", self.observability)
        self.assertIn(
            "FilterPattern.stringValue('$.status', '=', '5*')", self.observability
        )
        self.assertIn("ApiServerErrorAlarm", self.observability)

    def test_production_has_a_public_availability_probe(self) -> None:
        self.assertIn("addPublicAvailabilityProbe", self.backend)
        self.assertIn("PublicAvailabilityProbe", self.production_readiness)
        self.assertIn("/public/catalog", self.production_readiness)
        self.assertIn("PublicAvailabilityAlarm", self.observability)
        self.assertIn("TreatMissingData.BREACHING", self.observability)

    def test_production_errors_dispatch_through_a_bounded_github_app_path(self) -> None:
        self.assertIn("addProductionAutofix", self.backend)
        self.assertIn("enabled: deploymentEnvironment === 'production'", self.backend)
        self.assertIn("AgentRuntimeAutofixSubscription", self.autofix)
        self.assertIn("WorkerAutofixSubscription", self.autofix)
        self.assertEqual(self.autofix.count("FROGBOT_TERMINAL_ERROR"), 2)
        self.assertIn("AUTOFIX_COOLDOWN_HOURS: '6'", self.autofix)
        self.assertIn("AUTOFIX_DAILY_LIMIT: '3'", self.autofix)
        self.assertIn("actions: ['secretsmanager:GetSecretValue']", self.autofix)
        self.assertNotIn("secretsmanager:*", self.autofix)
        self.assertIn("autofixDispatcherArn", self.backend)

    def test_autofix_separates_model_tests_and_repository_write_access(self) -> None:
        generate = self.autofix_workflow.split("  generate:", 1)[1].split(
            "  verify-server:", 1
        )[0]
        verification = self.autofix_workflow.split("  verify-server:", 1)[1].split(
            "  publish:", 1
        )[0]
        publish = self.autofix_workflow.split("  publish:", 1)[1]
        self.assertIn("OPENROUTER_API_KEY", generate)
        self.assertIn("contents: read", generate)
        self.assertNotIn("OPENROUTER_API_KEY", verification)
        self.assertGreaterEqual(verification.count("persist-credentials: false"), 4)
        self.assertIn("contents: write", publish)
        self.assertNotIn("OPENROUTER_API_KEY", publish)
        self.assertIn(
            "needs: [generate, verify-server, verify-application, verify-apple, analyze]",
            publish,
        )
        self.assertIn("autoMergeEligible", publish)

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
        self.assertNotIn(
            "for (const fn of [apiFunction, workerFunction])", self.backend
        )

    def test_function_assets_exclude_tests_and_local_caches(self) -> None:
        for pattern in (
            "tests/**",
            "**/__pycache__/**",
            "**/*.pyc",
            ".pytest_cache/**",
            ".ruff_cache/**",
        ):
            self.assertIn(pattern, self.settings)

    def test_production_cannot_deploy_without_native_push(self) -> None:
        self.assertIn(
            "deploymentEnvironment === 'production' && !apnsApplicationArn",
            self.settings,
        )
        self.assertIn("FROGBOT_APNS_APPLICATION_ARN", self.production_workflow)
        self.assertIn(
            "NOTION_OAUTH_SECRET_ARN APNS_APPLICATION_ARN", self.production_workflow
        )

    def test_production_data_is_isolated_and_protected(self) -> None:
        self.assertIn("frogbot-production-user-files", self.backend)
        self.assertIn("alias/frogbot-production-user-files", self.backend)
        self.assertGreaterEqual(self.backend.count("deletionProtection:"), 2)
        self.assertIn("auditTrail.addS3EventSelector", self.backend)
        self.assertIn("ReadWriteType.ALL", self.backend)
        self.assertIn("nativePushFeedbackRoleArn", self.backend)

    def test_github_deployment_trust_uses_immutable_repository_ids(self) -> None:
        self.assertIn(
            "repo:tmoreton@5090418/frogbot@1356546597:environment:production",
            self.deployment_role,
        )
        self.assertNotIn(
            "repo:tmoreton/frogbot:environment:production", self.deployment_role
        )

    def test_production_release_provisions_and_verifies_meme_templates(self) -> None:
        self.assertIn("Ensure production meme template catalog", self.production_workflow)
        self.assertIn("scripts/sync_meme_templates.py", self.production_workflow)
        self.assertIn("/meme-templates/*", self.deployment_role)
        self.assertIn("'s3:GetObject', 's3:PutObject'", self.deployment_role)
        self.assertIn("alias/frogbot-production-user-files", self.deployment_role)
        self.assertIn(".templates[].key", self.production_verifier)
        self.assertIn("aws s3api head-object", self.production_verifier)

    def test_production_release_supports_a_local_xcode_upload(self) -> None:
        self.assertIn("release_scope:", self.production_workflow)
        self.assertIn("- backend-only", self.production_workflow)
        self.assertIn(
            "if: ${{ inputs.release_scope == 'full' }}", self.production_workflow
        )
        self.assertIn(
            'if [[ "$RELEASE_SCOPE" == full ]]; then', self.production_workflow
        )

    def test_production_release_uses_locked_agentcore_cdk_dependencies(self) -> None:
        self.assertIn(
            "agentcore config disableDependencyManagement true",
            self.production_workflow,
        )
        self.assertIn("npm ci --prefix agentcore/cdk", self.production_workflow)

    def test_production_release_stages_and_removes_agentcore_credentials(self) -> None:
        self.assertIn("umask 077", self.production_workflow)
        self.assertIn("> agentcore/.env.local", self.production_workflow)
        self.assertIn(
            "trap 'rm -f agentcore/.env.local' EXIT", self.production_workflow
        )

    def test_production_settings_fail_closed(self) -> None:
        self.assertIn(
            "requiredInProduction && deploymentEnvironment === 'production'",
            self.settings,
        )
        self.assertIn(
            "'FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT', 100, 3, 1_000_000, true",
            self.settings,
        )
        self.assertIn(
            "FROGBOT_MONTHLY_BUDGET_USD must be set before deploying production",
            self.settings,
        )

    def test_sandbox_uses_the_existing_named_native_push_applications(self) -> None:
        self.assertIn("resolveNativePushApplicationArns", self.backend)
        self.assertIn("resource: `app/${platform}`", self.native_push)
        self.assertIn("resourceName: 'FroggyBot'", self.native_push)
        self.assertIn("arnFormat: ArnFormat.SLASH_RESOURCE_NAME", self.native_push)
        self.assertIn("applicationArn || namedApplicationArn('APNS')", self.native_push)
        self.assertIn(
            "sandboxApplicationArn || namedApplicationArn('APNS_SANDBOX')",
            self.native_push,
        )

    def test_managed_connection_provider_secrets_are_scoped(self) -> None:
        for name in (
            "FROGBOT_GOOGLE_OAUTH_SECRET_ARN",
            "FROGBOT_GITHUB_APP_SECRET_ARN",
            "FROGBOT_X_OAUTH_SECRET_ARN",
            "FROGBOT_SLACK_OAUTH_SECRET_ARN",
            "FROGBOT_NOTION_OAUTH_SECRET_ARN",
        ):
            self.assertIn(name, self.settings)
            self.assertIn(name, self.production_workflow)
        self.assertIn("FROGBOT_MICROSOFT_OAUTH_SECRET_ARN", self.settings)
        self.assertNotIn("FROGBOT_MICROSOFT_OAUTH_SECRET_ARN", self.production_workflow)
        self.assertIn("addProviderConnectionAccess(apiFunction", self.backend)
        self.assertIn("DISABLED_CONNECTION_PROVIDER_IDS", self.provider_connections)
        self.assertIn("GITHUB_OAUTH_REDIRECT_URI", self.provider_connections)
        self.assertIn("/public/oauth/github/callback", self.provider_connections)
        self.assertIn(
            "resources: configuredSecrets",
            self.provider_connections,
        )

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

    def test_memory_clients_can_use_the_configured_encryption_key(self) -> None:
        self.assertIn(
            "memoryKmsKeyArn = requiredSetting('FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN')",
            self.settings,
        )
        self.assertIn("addMemoryAccess({", self.backend)
        self.assertIn("policyName: 'FrogBotMemoryKeyAccess'", self.memory_access)
        self.assertIn(
            "memoryKeyAccess.attachToRole(apiFunction.role!)", self.memory_access
        )
        self.assertIn(
            "memoryKeyAccess.attachToRole(workerFunction.role!)", self.memory_access
        )
        for action in (
            "kms:Decrypt",
            "kms:DescribeKey",
            "kms:Encrypt",
            "kms:GenerateDataKey",
        ):
            self.assertIn(action, self.memory_access)
        self.assertIn("resources: [memoryKmsKeyArn]", self.memory_access)
        self.assertIn(
            "FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN: ${{ vars.FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN }}",
            self.production_workflow,
        )

    def test_cleanup_roles_can_read_only_scoped_connection_secrets(self) -> None:
        connection_policies = self.backend.split("const connectionSecretsArn =", 1)[
            1
        ].split("jobs.grantSendMessages", 1)[0]
        api_policy = connection_policies.split("apiFunction.addToRolePolicy(", 1)[
            1
        ].split("\n);", 1)[0]
        worker_policy = connection_policies.split("workerFunction.addToRolePolicy(", 1)[
            1
        ].split("\n);", 1)[0]

        for policy in (api_policy, worker_policy):
            self.assertIn("'secretsmanager:GetSecretValue'", policy)
            self.assertIn("resources: [connectionSecretsArn]", policy)

    def test_production_deploy_role_scopes_company_credentials(self) -> None:
        self.assertNotIn("bedrock-agentcore:*", self.deployment_role)
        self.assertIn("bedrock-agentcore:GetTokenVault", self.deployment_role)
        self.assertIn(
            "bedrock-agentcore:CreateApiKeyCredentialProvider", self.deployment_role
        )
        self.assertIn(
            "bedrock-agentcore:UpdateApiKeyCredentialProvider", self.deployment_role
        )
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
        self.assertIn("nativePushFeedbackRoleArn", self.deployment_role)
        self.assertIn(
            "'iam:PassedToService': 'sns.amazonaws.com'",
            self.deployment_role,
        )


if __name__ == "__main__":
    unittest.main()
