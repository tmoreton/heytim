"""Route reviewed static credential identifiers to encrypted Standard parameters.

Existing connection records and protected deployment setting names remain valid.
Dynamic user credentials continue to use Secrets Manager unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

_LOCATIONS = json.loads(Path(__file__).with_name("static_credential_locations.json").read_text())
_PARAMETERS = {row["sourceArn"]: row["parameterArn"] for row in _LOCATIONS}


class StaticCredentialClient:
    def __init__(self, secrets: Any, parameters: Any = None):
        self._secrets = secrets
        self._parameters = parameters

    def __getattr__(self, name: str) -> Any:
        return getattr(self._secrets, name)

    def get_secret_value(self, *, SecretId: str, **options: Any) -> dict:
        target = _PARAMETERS.get(SecretId)
        if target is None:
            account = os.environ.get("HEYTIM_CREDENTIAL_ACCOUNT_ID", "")
            matches = [row["parameterArn"] for row in _LOCATIONS
                       if row["sourceName"] == SecretId and row["parameterArn"].split(":")[4] == account]
            target = matches[0] if len(set(matches)) == 1 else None
        if target is None:
            return self._secrets.get_secret_value(SecretId=SecretId, **options)
        if options.get("VersionId") or options.get("VersionStage", "AWSCURRENT") != "AWSCURRENT":
            raise ValueError("Historical static credentials require the migration recovery copy")
        if set(options) - {"VersionStage"}:
            raise ValueError("Unsupported static credential read options")
        if self._parameters is None:
            self._parameters = boto3.client(
                "ssm", region_name=target.split(":")[3],
                config=Config(retries={"mode": "adaptive", "total_max_attempts": 4},
                              connect_timeout=2, read_timeout=3),
            )
        response = self._parameters.get_parameter(Name=target, WithDecryption=True)
        raw = response["Parameter"]["Value"]
        if not isinstance(raw, str):
            raise ValueError("Credential parameter has no string value")
        return {"ARN": SecretId, "SecretString": raw, "VersionStages": ["AWSCURRENT"]}


def credential_client(secrets: Any) -> StaticCredentialClient:
    return StaticCredentialClient(secrets)
