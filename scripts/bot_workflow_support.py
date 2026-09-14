"""Shared validation and deployed-API adapter for bot workflow installers."""

from __future__ import annotations

import json
import re
from typing import Any

import boto3
from botocore.config import Config


class Application:
    """Small authenticated adapter around FrogBot's deployed API Lambda."""

    def __init__(
        self,
        session: boto3.Session,
        function_name: str,
        pool_id: str,
        email: str,
    ) -> None:
        config = Config(
            connect_timeout=5,
            read_timeout=60,
            retries={"mode": "adaptive", "total_max_attempts": 3},
        )
        self.client = session.client("lambda", config=config)
        self.function_name = function_name
        cognito = session.client("cognito-idp", config=config)
        if any(character in email for character in ('"', "\\")):
            raise ValueError("Email is invalid")
        users = [
            user
            for page in cognito.get_paginator("list_users").paginate(
                UserPoolId=pool_id,
                Filter=f'email = "{email}"',
            )
            for user in page.get("Users", [])
        ]
        if (
            len(users) != 1
            or users[0].get("UserStatus") != "CONFIRMED"
            or not users[0].get("Enabled")
        ):
            raise ValueError(
                "Expected one enabled, confirmed account matching the exact email"
            )
        user = users[0]
        attributes = {
            item["Name"]: item["Value"] for item in user.get("Attributes", [])
        }
        self.claims = {
            "sub": attributes["sub"],
            "email": attributes["email"],
            "cognito:username": user["Username"],
        }

    def request(
        self,
        method: str,
        route: str,
        body: dict[str, Any] | None = None,
        **params: str,
    ) -> dict[str, Any]:
        path = route
        for key, value in params.items():
            path = path.replace("{" + key + "}", value)
        event = {
            "version": "2.0",
            "rawPath": path,
            "pathParameters": params,
            "requestContext": {
                "http": {"method": method},
                "routeKey": f"{method} {route}",
                "authorizer": {"jwt": {"claims": self.claims}},
            },
            "body": json.dumps(body or {}),
        }
        result = self.client.invoke(
            FunctionName=self.function_name,
            Payload=json.dumps(event, separators=(",", ":")).encode(),
        )
        response = json.loads(result["Payload"].read())
        if result.get("FunctionError"):
            raise RuntimeError("Application invocation failed; inspect the API logs")
        payload = json.loads(response.get("body", "{}"))
        if response.get("statusCode", 500) >= 400:
            raise RuntimeError(
                f"{method} {route}: "
                f"{payload.get('message', 'Application request failed')}"
            )
        if not isinstance(payload, dict):
            raise TypeError(f"{method} {route}: application returned invalid JSON")
        return payload


def one_named(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in items
        if str(item.get("name", "")).casefold() == name.casefold()
    ]
    if len(matches) > 1:
        raise ValueError(
            f"More than one item is named {name!r}; resolve the duplicate first"
        )
    return matches[0] if matches else None


def _required_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _keyed(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"Every {label} needs a non-empty key")
        if key in result:
            raise ValueError(f"Duplicate {label} key: {key}")
        result[key] = item
    return result


def validate_pack(pack: dict[str, Any]) -> None:
    if pack.get("schemaVersion") != 1:
        raise ValueError("Unsupported workflow pack version")
    skills = _required_list(pack.get("skills", []), "skills")
    bots = _required_list(pack.get("bots", []), "bots")
    schedules = _required_list(pack.get("schedules", []), "schedules")
    skill_defs = _keyed(skills, "skill")
    bot_defs = _keyed(bots, "bot")
    for bot in bots:
        unknown = set(bot.get("skillKeys", [])) - set(skill_defs)
        if unknown:
            raise ValueError(
                f"Bot {bot['key']} references unknown skills: "
                f"{', '.join(sorted(unknown))}"
            )
    for schedule in schedules:
        if schedule.get("botKey") not in bot_defs:
            raise ValueError("A schedule references an unknown botKey")
    training = pack.get("training")
    if training is not None:
        if not isinstance(training, dict):
            raise ValueError("training must be an object")
        if training.get("botKey") not in bot_defs:
            raise ValueError("training references an unknown botKey")
        if training.get("skillKey") not in skill_defs:
            raise ValueError("training references an unknown skillKey")
        evidence_label = training.get("evidenceCountLabel")
        minimum_evidence = training.get("minimumEvidenceCount")
        if evidence_label is not None and (
            not isinstance(evidence_label, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", evidence_label)
        ):
            raise ValueError("training evidenceCountLabel is invalid")
        if minimum_evidence is not None and (
            isinstance(minimum_evidence, bool)
            or not isinstance(minimum_evidence, int)
            or not 1 <= minimum_evidence <= 1_000
        ):
            raise ValueError("training minimumEvidenceCount is invalid")
        if (evidence_label is None) != (minimum_evidence is None):
            raise ValueError(
                "training evidenceCountLabel and minimumEvidenceCount must be paired"
            )


def same_fields(
    left: dict[str, Any], right: dict[str, Any], fields: tuple[str, ...]
) -> bool:
    return all(left.get(field) == right.get(field) for field in fields)


def skill_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": definition["name"],
        "description": definition["description"],
        "instructions": definition["instructions"],
        "requiredToolIds": definition.get("requiredToolIds", []),
        "visibility": definition.get("visibility", "private"),
    }
