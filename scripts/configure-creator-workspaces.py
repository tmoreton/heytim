"""Install a reviewed creator pack through HeyTim's existing application handlers.

This operator utility requires IAM permission to invoke the application's API Lambda.
It resolves the exact Cognito email first; it never changes authentication or IAM.
Public definitions come from the monorepo's HeyTim catalog. Connections and
approval grants are preserved, never copied from a template or another account.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.config import Config


class Application:
    def __init__(self, session, function_name: str, pool_id: str, email: str):
        config = Config(connect_timeout=5, read_timeout=60, retries={"mode": "standard", "total_max_attempts": 2})
        self.client = session.client("lambda", config=config)
        self.function_name = function_name
        cognito = session.client("cognito-idp", config=config)
        if any(character in email for character in ('"', '\\')):
            raise ValueError("Email is invalid")
        users = [user for page in cognito.get_paginator("list_users").paginate(
            UserPoolId=pool_id, Filter=f'email = "{email}"'
        ) for user in page.get("Users", [])]
        if len(users) != 1 or users[0].get("UserStatus") != "CONFIRMED" or not users[0].get("Enabled"):
            raise ValueError("Expected one enabled, confirmed account matching the exact email")
        user = users[0]
        attributes = {item["Name"]: item["Value"] for item in user["Attributes"]}
        self.claims = {"sub": attributes["sub"], "email": attributes["email"], "cognito:username": user["Username"]}

    def request(self, method: str, route: str, body: dict | None = None, **params):
        path = route
        for key, value in params.items():
            path = path.replace("{" + key + "}", value)
        result = self.client.invoke(FunctionName=self.function_name, Payload=json.dumps({
            "version": "2.0", "rawPath": path, "pathParameters": params,
            "requestContext": {"http": {"method": method}, "routeKey": f"{method} {route}", "authorizer": {"jwt": {"claims": self.claims}}},
            "body": json.dumps(body or {}),
        }).encode())
        response = json.loads(result["Payload"].read())
        if result.get("FunctionError"):
            raise RuntimeError("Application invocation failed; inspect the API logs")
        payload = json.loads(response.get("body", "{}"))
        if response.get("statusCode", 500) >= 400:
            raise RuntimeError(f"{method} {route}: {payload.get('message', 'Application request failed')}")
        return payload


def one_named(items: list[dict], name: str) -> dict | None:
    matches = [item for item in items if item.get("name", "").casefold() == name.casefold()]
    if len(matches) > 1:
        raise ValueError(f"More than one item is named {name!r}; resolve the duplicate before installing")
    return matches[0] if matches else None


def install(app: Application, pack: dict, catalog: dict, *, apply: bool, schedules: bool, run_now: bool) -> dict:
    if pack.get("schemaVersion") != 1 or catalog.get("schemaVersion") != 3:
        raise ValueError("Unsupported pack or catalog version")
    templates = {item["id"]: item for item in catalog["bots"]}
    state = app.request("GET", "/bootstrap")
    chiefs = [bot for bot in state["bots"] if bot.get("systemRole") == "chief"]
    if len(chiefs) != 1:
        raise ValueError("Complete account setup with exactly one Chief before installing")
    installed = {"chief": chiefs[0]}
    plan = {"account": app.claims["email"], "apply": apply, "bots": [], "groups": []}
    for template_id in pack["templateIds"]:
        template = templates[template_id]
        existing = one_named(state["bots"], template["name"])
        tools = list(dict.fromkeys([*(existing or {}).get("toolIds", []), *template.get("toolIds", [])]))
        draft = {
            "name": template["name"], "tagline": template["tagline"],
            "prompt": template["prompt"] + "\n\nDirect-chat defaults (group context takes precedence): " + pack.get("directContext", ""),
            "color": (existing or {}).get("color", template["color"]),
            "skillIds": list(dict.fromkeys([*(existing or {}).get("skillIds", []), *template.get("skillIds", [])])),
            "toolIds": tools,
        }
        # Do not write approval fields: only an actual in-app approval grants access.
        if apply:
            bot = app.request("PUT", "/bots/{botId}", draft, botId=existing["id"]) if existing else app.request("POST", "/bots", draft)
        else:
            bot = existing or {"id": f"new:{template_id}", **draft}
        installed[template_id] = bot
        plan["bots"].append({"name": bot["name"], "id": bot["id"], "action": "update" if existing else "create"})
    for workspace in pack["groups"]:
        existing = one_named(state.get("groups", []), workspace["name"])
        if existing and not existing.get("isOwner"):
            raise ValueError("Only the group owner can install a workspace")
        members = [installed[template_id]["id"] for template_id in workspace["botTemplateIds"]]
        # Preserve extra bots already intentionally added by the owner.
        members = list(dict.fromkeys([*(item["id"] for item in (existing or {}).get("bots", [])), *members]))
        memory = workspace["memory"]
        previous_memory = (existing or {}).get("memory", "")
        marker = "\n\n--- Creator workspace ---\n"
        if previous_memory and previous_memory != memory:
            prefix = previous_memory.split(marker)[0] if marker in previous_memory else previous_memory
            if prefix != memory:
                memory = prefix + marker + memory
        if len(memory) > 4000:
            raise ValueError("Group context exceeds 4000 characters; shorten the existing notebook first")
        draft = {"name": workspace["name"], "memory": memory, "botIds": members}
        if apply:
            group = app.request("PUT", "/groups/{groupId}", draft, groupId=existing["id"]) if existing else app.request("POST", "/groups", draft)
        else:
            group = existing or {"id": f"new:{workspace['name']}", **draft}
        summary = {"name": group["name"], "id": group["id"], "schedule": "not installed"}
        if schedules and apply:
            tasks = app.request("GET", "/groups/{groupId}/schedules", groupId=group["id"])["schedules"]
            task = one_named(tasks, workspace["schedule"]["name"])
            saved = app.request("PUT", "/groups/{groupId}/schedules/{scheduleId}", workspace["schedule"], groupId=group["id"], scheduleId=task["id"]) if task else app.request("POST", "/groups/{groupId}/schedules", workspace["schedule"], groupId=group["id"])
            summary["schedule"] = {key: saved[key] for key in ("id", "time", "timezone", "enabled")}
        elif schedules:
            summary["schedule"] = workspace["schedule"]
        if run_now and apply:
            summary["trial"] = app.request("POST", "/groups/{groupId}/messages", {"text": workspace["schedule"]["prompt"], "replyBotId": "all"}, groupId=group["id"])
        plan["groups"].append(summary)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--user-pool-id", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=Path("examples/creator-workspaces.json"))
    parser.add_argument("--profile")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-schedules", action="store_true", help="Requires deployed group-schedule API and worker")
    parser.add_argument("--run-now", action="store_true", help="Run a research trial in both groups using the existing group API")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    app = Application(session, args.function_name, args.user_pool_id, args.email)
    result = install(app, json.loads(args.pack.read_text()), json.loads(args.catalog.read_text()), apply=args.apply, schedules=args.include_schedules, run_now=args.run_now)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
