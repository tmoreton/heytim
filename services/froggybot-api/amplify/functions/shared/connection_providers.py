from __future__ import annotations

CONNECTION_PROVIDERS = (
    {
        "id": "gmail",
        "name": "Gmail",
        "description": "Search and summarize email, then create drafts for review.",
        "category": "Email",
        "authType": "oauth",
        "uiKind": "oauth",
        "iconText": "G",
        "permissionsSummary": "No sending, deleting, relabeling, or archiving",
        "privacyTitle": "Your Gmail account stays private",
        "privacyDescription": (
            "FroggyBot uses this connection only when a bot needs the account. "
            "It can search and read email and create drafts for review."
        ),
    },
)


def connection_providers() -> list[dict]:
    return [dict(provider) for provider in CONNECTION_PROVIDERS]


def connection_provider(provider_id: str) -> dict | None:
    return next(
        (dict(provider) for provider in CONNECTION_PROVIDERS if provider["id"] == provider_id),
        None,
    )
