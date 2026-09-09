from __future__ import annotations

import unittest
from pathlib import Path


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = (
            Path(__file__).parents[2] / "backend.ts"
        ).read_text(encoding="utf-8")
        cls.observability = (
            Path(__file__).parents[2] / "infrastructure" / "observability.ts"
        ).read_text(encoding="utf-8")

    def test_worker_concurrency_protects_agentcore_and_is_observed(self) -> None:
        self.assertIn("reservedConcurrentExecutions: WORKER_CONCURRENCY", self.backend)
        self.assertIn("maxConcurrency: WORKER_CONCURRENCY", self.backend)
        self.assertIn("WorkerConcurrencyAlarm", self.observability)

    def test_signed_out_clients_get_no_aws_credentials(self) -> None:
        self.assertIn("cfnIdentityPool.allowUnauthenticatedIdentities = false", self.backend)

    def test_worker_polling_override_requires_explicit_deployment_opt_in(self) -> None:
        worker = self.backend.split("const workerFunction =", 1)[1].split("table.grantReadWriteData", 1)[0]
        self.assertIn("process.env.FROGBOT_ALLOW_RECURSIVE_POLLS === 'true'", worker)
        self.assertIn("? RecursiveLoop.ALLOW", worker)
        self.assertIn(": RecursiveLoop.TERMINATE", worker)
        self.assertEqual(self.backend.count("recursiveLoop:"), 1)

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
            self.assertIn(pattern, self.backend)


if __name__ == "__main__":
    unittest.main()
