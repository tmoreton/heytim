"""AWS browser transport, with no optional AgentCore SDK dependency."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote, urlsplit

SESSION_SECONDS = 3600
VIEW_SECONDS = 300
BROWSER_IDENTIFIER = "aws.browser.v1"


@lru_cache(maxsize=1)
def browser_clients():
    # Deliberately lazy: importing routes must not construct additional clients.
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=2, read_timeout=4,
                    retries={"mode": "standard", "total_max_attempts": 1})
    session = boto3.Session()
    return (session.client("bedrock-agentcore", config=config),
            session.client("bedrock-agentcore-control", config=config))


def live_view_url(agentcore, session_id: str) -> str:
    """Matches BrowserClient.generate_live_view_url's SigV4 GET signing contract.

    https://github.com/aws/bedrock-agentcore-sdk-python/blob/main/src/bedrock_agentcore/tools/browser_client.py
    This return value is a short-lived secret: never log it or persist it.
    """
    import boto3
    from botocore.auth import SigV4QueryAuth
    from botocore.awsrequest import AWSRequest

    endpoint = agentcore.meta.endpoint_url.rstrip("/")
    url = (f"{endpoint}/browser-streams/{BROWSER_IDENTIFIER}/sessions/"
           f"{quote(session_id, safe='')}/live-view")
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    request = AWSRequest(method="GET", url=url, headers={"host": urlsplit(url).hostname})
    SigV4QueryAuth(credentials, "bedrock-agentcore", agentcore.meta.region_name,
                  expires=VIEW_SECONDS).add_auth(request)
    return request.url


def session_args(record: dict) -> dict:
    return {"browserIdentifier": BROWSER_IDENTIFIER, "sessionId": record["sessionId"]}


def automation(agentcore, record: dict, enabled: bool) -> None:
    agentcore.update_browser_stream(
        **session_args(record),
        streamUpdate={"automationStreamUpdate": {
            "streamStatus": "ENABLED" if enabled else "DISABLED",
        }},
    )


def stop_session(agentcore, record: dict) -> None:
    if record.get("sessionId"):
        try:
            agentcore.stop_browser_session(**session_args(record))
        except agentcore.exceptions.ResourceNotFoundException:
            pass
