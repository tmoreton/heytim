from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request

from .support import ApiError


def _slack_connection(token: dict, runtime: dict) -> tuple[str, str, dict]:
    if token.get("ok") is not True:
        raise ApiError(400, "Slack could not complete the connection")
    user = token.get("authed_user")
    team = token.get("team")
    if not isinstance(user, dict) or not isinstance(team, dict):
        raise ApiError(400, "Slack returned an invalid connection")
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    expires_in = user.get("expires_in")
    user_id = user.get("id")
    team_id = team.get("id")
    team_name = team.get("name")
    granted = {
        scope.strip()
        for scope in str(user.get("scope", "")).split(",")
        if scope.strip()
    }
    required = set(runtime["EXTERNAL_PROVIDER_SPECS"]["slack"]["scopes"])
    if (
        granted != required
        or not all(
            isinstance(value, str) and value
            for value in (
                access_token,
                refresh_token,
                user_id,
                team_id,
                team_name,
            )
        )
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "Slack read-only access is required")
    return (
        f"{team_id}:{user_id}",
        team_name[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _microsoft_connection(
    token: dict, deadline: float, runtime: dict, provider: str = "microsoft"
) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    granted = {scope.casefold() for scope in str(token.get("scope", "")).split()}
    required = (
        {"user.read", "team.readbasic.all", "channel.readbasic.all", "channelmessage.read.all"}
        if provider == "microsoft_teams"
        else {"user.read", "mail.read", "calendars.read", "files.read.all", "sites.read.all"}
    )
    if (
        not required.issubset(granted)
        or not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "Microsoft 365 read-only access is required")
    profile = runtime["_bearer_json"](
        runtime["MICROSOFT_PROFILE_URL"], access_token, deadline, "microsoft"
    )
    account_id = profile.get("id")
    account = profile.get("mail") or profile.get("userPrincipalName")
    if not isinstance(account, str) or not account:
        account = profile.get("displayName")
    if (
        not isinstance(account_id, str)
        or not account_id
        or not isinstance(account, str)
        or not account.strip()
    ):
        raise ApiError(400, "Microsoft could not verify the account")
    return (
        account_id[:200],
        account.strip()[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _notion_connection(token: dict) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    workspace_id = token.get("workspace_id")
    workspace_name = token.get("workspace_name") or "Notion workspace"
    if (
        token.get("token_type") != "bearer"
        or not isinstance(access_token, str)
        or not access_token
        or not isinstance(workspace_id, str)
        or not workspace_id
        or not isinstance(workspace_name, str)
        or not workspace_name.strip()
    ):
        raise ApiError(400, "Notion returned an invalid connection")
    credential = {"accessToken": access_token}
    refresh_token = token.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        credential["refreshToken"] = refresh_token
    owner = token.get("owner")
    owner_user = owner.get("user") if isinstance(owner, dict) else None
    owner_id = owner_user.get("id") if isinstance(owner_user, dict) else None
    if not isinstance(owner_id, str) or not owner_id:
        owner_id = token.get("bot_id")
    account_id = (
        f"{workspace_id[:90]}:{owner_id[:90]}"
        if isinstance(owner_id, str) and owner_id
        else workspace_id[:200]
    )
    account_name = workspace_name.strip()
    if isinstance(owner_user, dict):
        person = owner_user.get("person")
        email = person.get("email") if isinstance(person, dict) else None
        if isinstance(email, str) and email.strip():
            account_name = f"{account_name} · {email.strip()}"
    return account_id, account_name[:254], credential


def _hubspot_connection(token: dict, deadline: float, runtime: dict) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "HubSpot did not return reusable access")
    client_id, client_secret, _ = runtime["_oauth_client"]("hubspot")
    request = urllib.request.Request(
        runtime["HUBSPOT_INTROSPECT_URL"],
        data=urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "token": access_token,
                "token_type_hint": "access_token",  # nosec B105 - OAuth hint
            }
        ).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    details = runtime["_request_json"](request, deadline, "hubspot")
    hub_id = details.get("hub_id")
    granted = details.get("scopes")
    if (
        details.get("active") is not True
        or type(hub_id) is not int
        or hub_id <= 0
        or not isinstance(granted, list)
        or not set(runtime["EXTERNAL_PROVIDER_SPECS"]["hubspot"]["scopes"]).issubset(granted)
    ):
        raise ApiError(400, "HubSpot read-only access is required")
    label = details.get("hub_domain") or f"HubSpot account {hub_id}"
    if not isinstance(label, str) or not label.strip():
        label = f"HubSpot account {hub_id}"
    return (
        str(hub_id),
        label.strip()[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _jira_connection(token: dict, deadline: float, runtime: dict) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "Jira did not return reusable access")
    resources = runtime["_bearer_list"](runtime["JIRA_RESOURCES_URL"], access_token, deadline, "jira")
    # A site-restricted 3LO app must return exactly one site. Never turn an
    # account-wide grant into an apparently site-scoped connection.
    if len(resources) != 1 or not isinstance(resources[0], dict):
        raise ApiError(400, "Choose one Jira site when connecting")
    site = resources[0]
    site_id = site.get("id")
    site_name = site.get("name")
    scopes = site.get("scopes")
    if (
        not isinstance(site_id, str)
        or not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
            site_id,
        )
        or not isinstance(site_name, str)
        or not site_name.strip()
        or not isinstance(scopes, list)
        or "read:jira-work" not in scopes
    ):
        raise ApiError(400, "Jira read-only site access is required")
    return (
        site_id.lower(),
        site_name.strip()[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _zoom_connection(token: dict, deadline: float, runtime: dict) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    scopes = set(str(token.get("scope", "")).split())
    required = set(runtime["EXTERNAL_PROVIDER_SPECS"]["zoom"]["scopes"])
    if (
        not required.issubset(scopes)
        or not isinstance(access_token, str) or not access_token
        or not isinstance(refresh_token, str) or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float)) or int(expires_in) <= 0
    ):
        raise ApiError(400, "Zoom read-only meeting access is required")
    profile = runtime["_bearer_json"](runtime["ZOOM_PROFILE_URL"], access_token, deadline, "zoom")
    user_id = profile.get("id")
    label = profile.get("email") or profile.get("display_name")
    if (
        not isinstance(user_id, str) or not user_id
        or not isinstance(label, str) or not label.strip()
    ):
        raise ApiError(400, "Zoom could not verify the account")
    return (
        user_id[:200], label.strip()[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


