from __future__ import annotations

import re


def _runtime():
    from . import provider_connections

    return provider_connections


def validated_provider_binding(tool_id: str, runtime: dict) -> dict:
    provider = runtime.get("provider")
    secret_arn = runtime.get("secretArn")
    client_secret_arn = runtime.get("oauthClientSecretArn")
    scopes = runtime.get("scopes")
    expected_scopes = _runtime().PROVIDER_SCOPES.get(provider)
    expected_oauth_provider = "google" if provider == "youtube" else provider
    expected_client_pattern = _runtime().PROVIDER_CLIENT_SECRET_PATTERNS.get(provider)
    if (
        expected_scopes is None
        or runtime.get("authType") != "oauth"
        or runtime.get("oauthProvider") != expected_oauth_provider
        or not isinstance(secret_arn, str)
        or not _runtime().CONNECTION_SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or not isinstance(client_secret_arn, str)
        or not expected_client_pattern.fullmatch(client_secret_arn)
        or not isinstance(scopes, list)
        or len(scopes) != len(set(scopes))
        or set(scopes) != expected_scopes
    ):
        raise ValueError(f"OAuth provider connection is invalid: {tool_id}")
    site_id = runtime.get("siteId")
    project_keys = runtime.get("projectKeys")
    channel_access = runtime.get("channelAccess")
    resource_ids = runtime.get("resourceIds")
    account_label = runtime.get("accountLabel")
    if account_label is not None and (
        not isinstance(account_label, str)
        or not account_label.strip()
        or len(account_label) > 160
    ):
        raise ValueError(f"OAuth account label is invalid: {tool_id}")
    if provider == "jira" and (
        not isinstance(site_id, str)
        or not _runtime().JIRA_SITE_ID_PATTERN.fullmatch(site_id)
    ):
        raise ValueError(f"Jira site identity is invalid: {tool_id}")
    if provider == "jira" and project_keys is not None and (
        not isinstance(project_keys, list)
        or not 1 <= len(project_keys) <= 100
        or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", key)
            for key in project_keys
        )
        or len(project_keys) != len(set(project_keys))
    ):
        raise ValueError(f"Jira project access is invalid: {tool_id}")
    if provider == "microsoft_teams" and channel_access is not None and (
        not isinstance(channel_access, list)
        or not 1 <= len(channel_access) <= 100
        or any(
            not isinstance(value, str)
            or not re.fullmatch(
                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/[A-Za-z0-9:_@.\-]{5,200}",
                value,
            )
            for value in channel_access
        )
        or len(channel_access) != len(set(channel_access))
    ):
        raise ValueError(f"Teams channel access is invalid: {tool_id}")
    patterns = {
        "slack": r"[A-Z0-9]{2,32}",
        "notion": r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
    }
    if resource_ids is not None and (
        provider not in patterns
        or not isinstance(resource_ids, list)
        or not 1 <= len(resource_ids) <= 100
        or any(
            not isinstance(value, str)
            or not re.fullmatch(patterns[provider], value)
            for value in resource_ids
        )
        or len(resource_ids) != len(set(resource_ids))
    ):
        raise ValueError(f"Provider resource access is invalid: {tool_id}")
    return {
        "id": tool_id,
        "kind": "provider_api",
        "provider": provider,
        "authType": "oauth",
        "oauthProvider": expected_oauth_provider,
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
        **({"accountLabel": account_label.strip()} if account_label is not None else {}),
        **({"siteId": site_id} if provider == "jira" else {}),
        **(
            {"projectKeys": project_keys}
            if provider == "jira" and project_keys is not None else {}
        ),
        **(
            {"channelAccess": channel_access}
            if provider == "microsoft_teams" and channel_access is not None else {}
        ),
        **({"resourceIds": resource_ids} if resource_ids is not None else {}),
    }


