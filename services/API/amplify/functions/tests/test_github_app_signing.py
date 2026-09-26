from __future__ import annotations

import unittest

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from shared.github_app import github_app_jwt


class GitHubAppSigningTests(unittest.TestCase):
    def test_jwt_uses_audited_rs256_implementation(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

        token = github_app_jwt("12345", pem, now=2_000)

        self.assertEqual(jwt.get_unverified_header(token), {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(
            jwt.decode(
                token,
                private_key.public_key(),
                algorithms=["RS256"],
                options={"verify_exp": False, "verify_iat": False},
            ),
            {"iat": 1_940, "exp": 2_540, "iss": "12345"},
        )

    def test_rejects_non_rsa_and_short_rsa_keys(self) -> None:
        for value in ("not-a-key", ""):
            with self.assertRaisesRegex(ValueError, "private key is invalid"):
                github_app_jwt("12345", value, now=2_000)


if __name__ == "__main__":
    unittest.main()
