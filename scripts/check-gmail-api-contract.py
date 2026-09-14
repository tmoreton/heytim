"""Fail when Google's generally available Gmail REST contract stops matching FrogBot."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

DISCOVERY_URL = "https://gmail.googleapis.com/$discovery/rest?version=v1"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
REQUIRED_METHODS = {
    ("threads", "list"): ("GET", READ_SCOPE),
    ("threads", "get"): ("GET", READ_SCOPE),
    ("messages", "get"): ("GET", READ_SCOPE),
    ("labels", "list"): ("GET", READ_SCOPE),
    ("drafts", "list"): ("GET", COMPOSE_SCOPE),
    ("drafts", "get"): ("GET", COMPOSE_SCOPE),
    ("drafts", "create"): ("POST", COMPOSE_SCOPE),
}


def _discovery() -> dict[str, Any]:
    request = urllib.request.Request(
        DISCOVERY_URL,
        headers={"accept": "application/json", "user-agent": "FroggyBot-contract/1.0"},
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed Google discovery host.
            request, timeout=20
        ) as response:
            value = json.loads(response.read(10_000_001).decode("utf-8"))
    except (OSError, UnicodeError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gmail discovery document could not be read") from exc
    if not isinstance(value, dict):
        raise TypeError("Gmail discovery document is invalid")
    return value


def validate(document: dict[str, Any]) -> list[str]:
    problems = []
    users = document.get("resources", {}).get("users", {})
    resources = users.get("resources", {}) if isinstance(users, dict) else {}
    for (resource_name, method_name), (http_method, scope) in REQUIRED_METHODS.items():
        resource = resources.get(resource_name, {})
        methods = resource.get("methods", {}) if isinstance(resource, dict) else {}
        method = methods.get(method_name) if isinstance(methods, dict) else None
        label = f"users.{resource_name}.{method_name}"
        if not isinstance(method, dict):
            problems.append(f"missing method: {label}")
            continue
        if method.get("httpMethod") != http_method:
            problems.append(f"{label} no longer uses {http_method}")
        scopes = method.get("scopes", [])
        if not isinstance(scopes, list) or scope not in scopes:
            problems.append(f"{label} no longer accepts the required OAuth scope")
    return problems


def main() -> int:
    try:
        problems = validate(_discovery())
    except (RuntimeError, TypeError) as exc:
        print(f"Gmail API contract check failed: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("Gmail API contract check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Gmail API contract is compatible with FrogBot's seven read/draft tools.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
