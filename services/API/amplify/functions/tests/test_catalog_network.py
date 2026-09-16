from __future__ import annotations

import unittest
from unittest.mock import patch

from shared import catalog_rules
from shared.catalog import CatalogError


class CatalogNetworkTests(unittest.TestCase):
    def test_private_connection_rejects_hostname_resolving_to_private_ip(self) -> None:
        with (
            patch.object(
                catalog_rules.socket,
                "getaddrinfo",
                return_value=[
                    (
                        catalog_rules.socket.AF_INET,
                        catalog_rules.socket.SOCK_STREAM,
                        6,
                        "",
                        ("127.0.0.1", 443),
                    )
                ],
            ),
            self.assertRaisesRegex(CatalogError, "resolve only to public"),
        ):
            catalog_rules._validate_mcp_endpoint("https://public.example/mcp")


if __name__ == "__main__":
    unittest.main()
