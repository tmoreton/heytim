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
