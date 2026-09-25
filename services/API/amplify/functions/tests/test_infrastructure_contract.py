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
        cls.gateway_target_deployer = (
            Path(__file__).parents[5]
            / "scripts"
            / "deploy-external-gateway-targets.sh"
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
        self.assertNotIn("HEYTIM_ALLOW_RECURSIVE_POLLS", self.backend)
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
        self.assertEqual(self.autofix.count("HEYTIM_TERMINAL_ERROR"), 2)
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
        self.assertIn("HEYTIM_APNS_APPLICATION_ARN", self.production_workflow)
        self.assertIn(
            "NOTION_OAUTH_SECRET_ARN APNS_APPLICATION_ARN", self.production_workflow
        )

    def test_production_data_is_isolated_and_protected(self) -> None:
        self.assertIn("heytim-production-user-files", self.backend)
        self.assertIn("alias/heytim-production-user-files", self.backend)
        self.assertGreaterEqual(self.backend.count("deletionProtection:"), 2)
        self.assertIn("auditTrail.addS3EventSelector", self.backend)
        self.assertIn("ReadWriteType.ALL", self.backend)
        self.assertIn("nativePushFeedbackRoleArn", self.backend)

    def test_github_deployment_trust_uses_immutable_repository_ids(self) -> None:
        self.assertIn(
            "repo:tmoreton@5090418/heytim@1356546597:environment:production",
            self.deployment_role,
        )
        self.assertNotIn(
            "repo:tmoreton@5090418/frogbot@1356546597:environment:production",
            self.deployment_role,
        )
        self.assertNotIn(
            "repo:tmoreton@5090418/heytim-platform@1356546597:environment:production",
            self.deployment_role,
        )
        self.assertNotIn(
            "repo:tmoreton/heytim:environment:production", self.deployment_role
        )

    def test_production_release_provisions_and_verifies_meme_templates(self) -> None:
        self.assertIn("Ensure production meme template catalog", self.production_workflow)
        self.assertIn("scripts/sync_meme_templates.py", self.production_workflow)
        self.assertIn("/meme-templates/*", self.deployment_role)
        self.assertIn("'s3:GetObject', 's3:PutObject'", self.deployment_role)
        self.assertIn("alias/heytim-production-user-files", self.deployment_role)
        self.assertIn(".templates[].key", self.production_verifier)
        self.assertIn("aws s3api head-object", self.production_verifier)

    def test_production_release_deploys_and_smokes_external_research(self) -> None:
        self.assertIn(
            "Deploy external research gateway targets", self.production_workflow
        )
        self.assertIn(
            "scripts/deploy-external-gateway-targets.sh", self.production_workflow
        )
        self.assertIn(
            "scripts/smoke_external_gateway.py", self.production_workflow
        )
        self.assertIn("HeyTimXSearch", self.gateway_target_deployer)
        self.assertIn("HeyTimYouTube", self.gateway_target_deployer)
        self.assertIn("HeyTimXApi", self.gateway_target_deployer)
        self.assertIn("HeyTimYouTubeApi", self.gateway_target_deployer)
        self.assertIn("create-gateway-target", self.gateway_target_deployer)
        self.assertIn("update-gateway-target", self.gateway_target_deployer)
        self.assertIn("HeyTimExternalResearchTargets", self.gateway_target_deployer)
        self.assertIn("retry_aws", self.gateway_target_deployer)
        self.assertIn("heytim-external-research-", self.gateway_target_deployer)
        self.assertIn(
            "bedrock-agentcore-gateway-heytim-${account_id}-use1",
            self.gateway_target_deployer,
        )
        self.assertIn("HeyTimXSearch HeyTimYouTube", self.production_verifier)
        for action in (
            "bedrock-agentcore:CreateGatewayTarget",
            "bedrock-agentcore:GetGatewayTarget",
            "bedrock-agentcore:InvokeGateway",
            "bedrock-agentcore:UpdateGatewayTarget",
            "iam:PutRolePolicy",
        ):
            self.assertIn(action, self.deployment_role)
        self.assertIn("/releases/skills-v*/x/openapi.yaml", self.deployment_role)
        self.assertIn("bedrock-agentcore-gateway-heytim-", self.deployment_role)
        self.assertIn("new Bucket(stack, 'HeyTimGatewaySchemas'", self.deployment_role)
        self.assertIn("blockPublicAccess: BlockPublicAccess.BLOCK_ALL", self.deployment_role)
        self.assertIn("encryption: BucketEncryption.S3_MANAGED", self.deployment_role)
        self.assertIn("objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED", self.deployment_role)
        self.assertIn("removalPolicy: RemovalPolicy.RETAIN", self.deployment_role)
        self.assertIn("versioned: true", self.deployment_role)
        self.assertIn(
            "/releases/skills-v*/youtube/openapi.yaml", self.deployment_role
        )

    def test_production_release_supports_a_local_xcode_upload(self) -> None:
        self.assertIn("release_scope:", self.production_workflow)
        self.assertIn("- backend-only", self.production_workflow)
        self.assertIn(
            "if: ${{ github.event_name == 'release' || inputs.release_scope == 'full' }}",
            self.production_workflow,
        )
        self.assertIn(
            'if [[ "$RELEASE_SCOPE" == full ]]; then', self.production_workflow
        )

    def test_published_release_deploys_both_apple_apps_with_the_tag_version(self) -> None:
        self.assertIn("release:\n    types: [published]", self.production_workflow)
        self.assertIn('git merge-base --is-ancestor "$GITHUB_SHA" origin/main', self.production_workflow)
        self.assertIn("release_version: ${{ steps.release.outputs.version }}", self.production_workflow)
        self.assertIn(
            "RELEASE_VERSION: ${{ needs.deploy.outputs.release_version }}",
            self.production_workflow,
        )
        self.assertIn(
            "HEYTIM_MARKETING_VERSION: ${{ steps.apple-build.outputs.version }}",
            self.production_workflow,
        )
        self.assertIn("run: ./apps/iOS/scripts/testflight-ci.sh", self.production_workflow)
        self.assertIn('"$output/HeyTim-$HEYTIM_MARKETING_VERSION-macOS.dmg"', self.production_workflow)

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
            "'HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT', 100, 3, 1_000_000, true",
            self.settings,
        )
        self.assertIn(
            "HEYTIM_MONTHLY_BUDGET_USD must be set before deploying production",
            self.settings,
        )

    def test_sandbox_uses_the_existing_named_native_push_applications(self) -> None:
        self.assertIn("resolveNativePushApplicationArns", self.backend)
        self.assertIn("resource: `app/${platform}`", self.native_push)
        self.assertIn("resourceName: 'HeyTim'", self.native_push)
        self.assertIn("arnFormat: ArnFormat.SLASH_RESOURCE_NAME", self.native_push)
        self.assertIn("applicationArn || namedApplicationArn('APNS')", self.native_push)
        self.assertIn(
            "sandboxApplicationArn || namedApplicationArn('APNS_SANDBOX')",
            self.native_push,
        )

    def test_managed_connection_provider_secrets_are_scoped(self) -> None:
        for name in (
            "HEYTIM_GOOGLE_OAUTH_SECRET_ARN",
            "HEYTIM_GITHUB_APP_SECRET_ARN",
            "HEYTIM_X_OAUTH_SECRET_ARN",
            "HEYTIM_SLACK_OAUTH_SECRET_ARN",
            "HEYTIM_NOTION_OAUTH_SECRET_ARN",
        ):
            self.assertIn(name, self.settings)
            self.assertIn(name, self.production_workflow)
        self.assertIn("HEYTIM_MICROSOFT_OAUTH_SECRET_ARN", self.settings)
        for name in (
            "HEYTIM_MICROSOFT_OAUTH_SECRET_ARN",
            "HEYTIM_HUBSPOT_OAUTH_SECRET_ARN",
            "HEYTIM_JIRA_OAUTH_SECRET_ARN",
            "HEYTIM_ZOOM_OAUTH_SECRET_ARN",
        ):
            self.assertIn(name, self.settings)
            self.assertIn(name, self.production_workflow)
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
            "HEYTIM_MONTHLY_RUN_UNIT_LIMIT",
            "HEYTIM_USER_WINDOW_RUN_UNIT_LIMIT",
            "HEYTIM_GLOBAL_WINDOW_RUN_UNIT_LIMIT",
            "HEYTIM_USAGE_WINDOW_SECONDS",
            "HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT",
        ):
            self.assertIn(setting, self.backend)

    def test_api_can_admit_new_browser_sessions_with_the_same_limits(self) -> None:
        api = self.backend.split("const apiFunction =", 1)[1].split(
            "const workerFunction =", 1
        )[0]
        for setting in (
            "HEYTIM_MONTHLY_RUN_UNIT_LIMIT",
            "HEYTIM_USER_WINDOW_RUN_UNIT_LIMIT",
            "HEYTIM_GLOBAL_WINDOW_RUN_UNIT_LIMIT",
            "HEYTIM_USAGE_WINDOW_SECONDS",
            "HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT",
        ):
            self.assertIn(setting, api)
        self.assertGreaterEqual(self.backend.count("dynamodb:TransactWriteItems"), 2)

    def test_memory_clients_can_use_the_configured_encryption_key(self) -> None:
        self.assertIn(
            "memoryKmsKeyArn = requiredSetting('HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN')",
            self.settings,
        )
        self.assertIn("addMemoryAccess({", self.backend)
        self.assertIn("policyName: 'HeyTimManagedMemoryKeyAccess'", self.memory_access)
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
            "HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN: ${{ vars.HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN }}",
            self.production_workflow,
        )

    def test_release_role_can_read_generated_amplify_outputs(self) -> None:
        for action in (
            "amplify:GetApp",
            "amplify:GetBranch",
            "cloudformation:DescribeStacks",
            "cloudformation:GetTemplateSummary",
        ):
            self.assertIn(action, self.deployment_role)

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
            self.assertIn(
                "resources: [connectionSecretsArn]",
                policy,
            )
            self.assertNotIn("legacyConnectionSecretsArn", policy)

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
