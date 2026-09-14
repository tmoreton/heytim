"""Install an account workflow without changing grants, IAM, or tool approval."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import boto3
from bot_workflow_support import (
    Application,
    _keyed,
    one_named,
    same_fields,
    skill_payload,
    validate_pack,
)
from botocore.exceptions import ClientError

LEARNED_PROFILE_MARKER = "\n\n## Learned voice profile\n\n"
TERMINAL_MESSAGE_STATUSES = {"complete", "error", "cancelled"}


def _base_skill_is_current(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    current_instructions = str(current.get("instructions", ""))
    desired_instructions = str(desired["instructions"])
    instructions_match = current_instructions == desired_instructions or (
        current_instructions.startswith(desired_instructions + LEARNED_PROFILE_MARKER)
    )
    return instructions_match and same_fields(
        current,
        desired,
        ("name", "description", "requiredToolIds", "visibility"),
    )


def _owned_skill(skills: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in skills
        if str(item.get("name", "")).casefold() == name.casefold()
        and item.get("source") == "user"
        and item.get("relationship") == "owner"
    ]
    if len(matches) > 1:
        raise ValueError(
            f"More than one owned skill is named {name!r}; resolve the duplicate first"
        )
    return matches[0] if matches else None


def provision_skills(
    app: Application,
    definitions: list[dict[str, Any]],
    available: list[dict[str, Any]],
    *,
    apply: bool,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    installed: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    for definition in definitions:
        existing = _owned_skill(available, definition["name"])
        payload = skill_payload(definition)
        action = "create"
        if existing:
            current = app.request("GET", "/skills/{skillId}", skillId=existing["id"])
            action = (
                "unchanged" if _base_skill_is_current(current, payload) else "update"
            )
            if apply and action == "update":
                current = app.request(
                    "PUT", "/skills/{skillId}", payload, skillId=existing["id"]
                )
            installed[definition["key"]] = current
        elif apply:
            installed[definition["key"]] = app.request("POST", "/skills", payload)
        else:
            installed[definition["key"]] = {
                "id": f"new:{definition['key']}",
                "version": 1,
                **payload,
            }
        changes.append(
            {
                "key": definition["key"],
                "name": definition["name"],
                "id": installed[definition["key"]]["id"],
                "action": action,
            }
        )
    return installed, changes


def _connections_by_provider(app: Application) -> dict[str, dict[str, Any]]:
    connections = app.request("GET", "/connections").get("connections", [])
    if not isinstance(connections, list):
        raise TypeError("Application returned invalid connection data")
    result: dict[str, dict[str, Any]] = {}
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        provider = connection.get("provider")
        if not isinstance(provider, str):
            continue
        if provider in result:
            raise ValueError(f"More than one {provider} connection is active")
        if connection.get("connectionStatus") == "connected":
            result[provider] = connection
    return result


def _bot_payload(
    definition: dict[str, Any],
    skills: dict[str, dict[str, Any]],
    skill_definitions: dict[str, dict[str, Any]],
    connections: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    skill_keys = definition.get("skillKeys", [])
    providers = definition.get("connectionProviders", [])
    if not isinstance(skill_keys, list) or not all(
        isinstance(value, str) for value in skill_keys
    ):
        raise ValueError(f"Bot {definition['key']} has invalid skillKeys")
    if not isinstance(providers, list) or not all(
        isinstance(value, str) for value in providers
    ):
        raise ValueError(f"Bot {definition['key']} has invalid connectionProviders")
    missing = [provider for provider in providers if provider not in connections]
    if missing:
        raise ValueError(
            "Connect these providers before installing "
            f"{definition['name']}: {', '.join(missing)}"
        )
    required_tools = [
        tool_id
        for key in skill_keys
        for tool_id in skill_definitions[key].get("requiredToolIds", [])
    ]
    tool_ids = list(
        dict.fromkeys(
            [
                *definition.get("toolIds", []),
                *required_tools,
                *(connections[provider]["id"] for provider in providers),
            ]
        )
    )
    return {
        "name": definition["name"],
        "tagline": definition.get("tagline", ""),
        "prompt": definition["prompt"],
        "color": definition.get("color", "#58BEAA"),
        "skillIds": [skills[key]["id"] for key in skill_keys],
        "toolIds": tool_ids,
    }


def provision_bots(
    app: Application,
    definitions: list[dict[str, Any]],
    existing_bots: list[dict[str, Any]],
    skills: dict[str, dict[str, Any]],
    skill_definitions: dict[str, dict[str, Any]],
    connections: dict[str, dict[str, Any]],
    *,
    apply: bool,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    installed: dict[str, dict[str, Any]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    for definition in definitions:
        existing = one_named(existing_bots, definition["name"])
        payload = _bot_payload(definition, skills, skill_definitions, connections)
        payloads[definition["key"]] = payload
        action = "create"
        if existing:
            action = (
                "unchanged"
                if same_fields(
                    existing,
                    payload,
                    ("name", "tagline", "prompt", "color", "skillIds", "toolIds"),
                )
                else "update"
            )
            installed_bot = (
                app.request("PUT", "/bots/{botId}", payload, botId=existing["id"])
                if apply and action == "update"
                else existing
            )
        elif apply:
            installed_bot = app.request("POST", "/bots", payload)
        else:
            installed_bot = {"id": f"new:{definition['key']}", **payload}
        installed[definition["key"]] = installed_bot
        changes.append(
            {
                "key": definition["key"],
                "name": definition["name"],
                "id": installed_bot["id"],
                "action": action,
            }
        )
    return installed, payloads, changes


def _assistant_message(
    messages: list[dict[str, Any]], turn_id: str
) -> dict[str, Any] | None:
    message_id = f"{turn_id}-assistant"
    return next(
        (
            message
            for message in messages
            if message.get("id") == message_id and message.get("role") == "assistant"
        ),
        None,
    )


def wait_for_turn(
    app: Application,
    bot_id: str,
    turn_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float = 3,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = app.request("GET", "/bots/{botId}/messages", botId=bot_id)
        messages = response.get("messages", [])
        if not isinstance(messages, list):
            raise TypeError("Application returned invalid message data")
        message = _assistant_message(messages, turn_id)
        if message and message.get("status") in TERMINAL_MESSAGE_STATUSES:
            return message
        if message and message.get("status") == "needs_input":
            raise RuntimeError("Training needs user input in the JOPbot chat")
        time.sleep(poll_seconds)
    raise TimeoutError("Training did not finish before the timeout")


def _profile_already_exists(
    app: Application, bot_id: str, completion_marker: str
) -> bool:
    response = app.request("GET", "/bots/{botId}/messages", botId=bot_id)
    messages = response.get("messages", [])
    return isinstance(messages, list) and any(
        isinstance(message, dict)
        and message.get("role") == "assistant"
        and completion_marker in str(message.get("text", ""))
        for message in messages
    )


def train_voice(
    app: Application,
    training: dict[str, Any],
    bots: dict[str, dict[str, Any]],
    bot_payloads: dict[str, dict[str, Any]],
    skills: dict[str, dict[str, Any]],
    skill_definitions: dict[str, dict[str, Any]],
    *,
    approve_once: bool,
    force: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    bot_key = training["botKey"]
    skill_key = training["skillKey"]
    bot = bots[bot_key]
    completion_marker = training.get("completionMarker", "VOICE PROFILE READY")
    if not force and _profile_already_exists(app, bot["id"], completion_marker):
        return {"status": "already_trained", "botId": bot["id"]}

    turn = app.request(
        "POST",
        "/bots/{botId}/messages",
        {"text": training["prompt"]},
        botId=bot["id"],
    )
    if turn.get("status") == "awaiting_approval":
        if not approve_once:
            return {
                "status": "awaiting_approval",
                "botId": bot["id"],
                "turnId": turn["turnId"],
            }
        app.request(
            "POST",
            "/bots/{botId}/messages/{turnId}/approve",
            {"always": False},
            botId=bot["id"],
            turnId=turn["turnId"],
        )
    message = wait_for_turn(
        app,
        bot["id"],
        turn["turnId"],
        timeout_seconds=timeout_seconds,
    )
    if message.get("status") != "complete":
        raise RuntimeError(
            f"Training finished with status {message.get('status', 'unknown')}: "
            f"{message.get('text', '')}"
        )
    profile = str(message.get("text", "")).strip()
    if completion_marker not in profile:
        raise RuntimeError(
            "Training completed without the expected voice profile marker"
        )
    profile = profile[profile.index(completion_marker) :]
    evidence_label = training.get("evidenceCountLabel")
    minimum_evidence = training.get("minimumEvidenceCount")
    if isinstance(evidence_label, str) and isinstance(minimum_evidence, int):
        evidence = re.search(
            rf"(?im)^{re.escape(evidence_label)}\s*:\s*(\d+)\s*$",
            profile,
        )
        if evidence is None or int(evidence.group(1)) < minimum_evidence:
            raise RuntimeError(
                "Training completed without enough verified source material"
            )

    schedules = app.request("GET", "/bots/{botId}/schedules", botId=bot["id"]).get(
        "schedules", []
    )
    if schedules:
        raise RuntimeError(
            "Training completed, but the bot already has a schedule. "
            "Remove the schedule before saving and repinning a new profile."
        )

    current_skill = app.request(
        "GET", "/skills/{skillId}", skillId=skills[skill_key]["id"]
    )
    base_instructions = skill_definitions[skill_key]["instructions"].rstrip()
    learned_instructions = base_instructions + LEARNED_PROFILE_MARKER + profile
    if len(learned_instructions) > 20_000:
        raise ValueError(
            "The learned voice profile exceeds the skill instruction limit"
        )
    updated_skill = app.request(
        "PUT",
        "/skills/{skillId}",
        {
            **skill_payload(skill_definitions[skill_key]),
            "instructions": learned_instructions,
        },
        skillId=current_skill["id"],
    )
    skills[skill_key] = updated_skill

    payload = bot_payloads[bot_key]
    other_skills = [
        skill_id for skill_id in payload["skillIds"] if skill_id != updated_skill["id"]
    ]
    app.request(
        "PUT",
        "/bots/{botId}",
        {**payload, "skillIds": other_skills},
        botId=bot["id"],
    )
    bots[bot_key] = app.request("PUT", "/bots/{botId}", payload, botId=bot["id"])
    return {
        "status": "complete",
        "botId": bot["id"],
        "turnId": turn["turnId"],
        "skillId": updated_skill["id"],
        "skillVersion": updated_skill["version"],
        "profile": profile,
    }


def provision_schedules(
    app: Application,
    definitions: list[dict[str, Any]],
    bots: dict[str, dict[str, Any]],
    *,
    apply: bool,
    include: bool,
    sync_enabled: bool,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for definition in definitions:
        bot = bots[definition["botKey"]]
        payload = {
            key: definition[key]
            for key in (
                "name",
                "prompt",
                "frequency",
                "time",
                "timezone",
                "enabled",
                "dayOfWeek",
                "dayOfMonth",
            )
            if key in definition
        }
        action = "not_installed"
        schedule_id = None
        if include:
            existing_schedules = app.request(
                "GET", "/bots/{botId}/schedules", botId=bot["id"]
            ).get("schedules", [])
            existing = one_named(existing_schedules, definition["name"])
            if existing and not sync_enabled:
                payload["enabled"] = existing.get(
                    "enabled", payload.get("enabled", False)
                )
            if existing:
                action = (
                    "unchanged"
                    if same_fields(
                        existing,
                        payload,
                        tuple(payload),
                    )
                    else "update"
                )
                schedule_id = existing["id"]
                if apply and action == "update":
                    saved = app.request(
                        "PUT",
                        "/bots/{botId}/schedules/{scheduleId}",
                        payload,
                        botId=bot["id"],
                        scheduleId=existing["id"],
                    )
                    schedule_id = saved["id"]
            else:
                action = "create"
                if apply:
                    saved = app.request(
                        "POST",
                        "/bots/{botId}/schedules",
                        payload,
                        botId=bot["id"],
                    )
                    schedule_id = saved["id"]
                else:
                    schedule_id = f"new:{definition['name']}"
        changes.append(
            {
                "name": definition["name"],
                "bot": bot["name"],
                "id": schedule_id,
                "action": action,
                "enabled": payload.get("enabled", False),
            }
        )
    return changes


def install(
    app: Application,
    pack: dict[str, Any],
    *,
    apply: bool,
    include_schedules: bool,
    train_now: bool,
    approve_once: bool,
    force_train: bool,
    sync_schedule_state: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    validate_pack(pack)
    state = app.request("GET", "/bootstrap")
    skill_definitions = _keyed(pack.get("skills", []), "skill")
    skills, skill_changes = provision_skills(
        app,
        pack.get("skills", []),
        state.get("skills", []),
        apply=apply,
    )
    connections = _connections_by_provider(app)
    bots, bot_payloads, bot_changes = provision_bots(
        app,
        pack.get("bots", []),
        state.get("bots", []),
        skills,
        skill_definitions,
        connections,
        apply=apply,
    )
    plan: dict[str, Any] = {
        "workflow": pack.get("name", "Bot workflow"),
        "account": app.claims["email"],
        "apply": apply,
        "skills": skill_changes,
        "bots": bot_changes,
        "connections": [
            {
                "provider": provider,
                "id": connection["id"],
                "account": connection.get("connectedAccount"),
            }
            for provider, connection in sorted(connections.items())
            if any(
                provider in definition.get("connectionProviders", [])
                for definition in pack.get("bots", [])
            )
        ],
    }
    training = pack.get("training")
    if train_now:
        if not apply:
            raise ValueError("--train-now requires --apply")
        if not training:
            raise ValueError("This workflow pack has no training definition")
        plan["training"] = train_voice(
            app,
            training,
            bots,
            bot_payloads,
            skills,
            skill_definitions,
            approve_once=approve_once,
            force=force_train,
            timeout_seconds=timeout_seconds,
        )
    elif training:
        plan["training"] = {"status": "not_run"}
    plan["schedules"] = provision_schedules(
        app,
        pack.get("schedules", []),
        bots,
        apply=apply,
        include=include_schedules,
        sync_enabled=sync_schedule_state,
    )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--user-pool-id", required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--profile")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-schedules", action="store_true")
    parser.add_argument("--sync-schedule-state", action="store_true")
    parser.add_argument("--train-now", action="store_true")
    parser.add_argument(
        "--approve-once",
        action="store_true",
        help="Approve only the training turn's interactive tools, never future turns",
    )
    parser.add_argument("--force-train", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        app = Application(
            session,
            args.function_name,
            args.user_pool_id,
            args.email,
        )
        pack = json.loads(args.pack.read_text())
        result = install(
            app,
            pack,
            apply=args.apply,
            include_schedules=args.include_schedules,
            train_now=args.train_now,
            approve_once=args.approve_once,
            force_train=args.force_train,
            sync_schedule_state=args.sync_schedule_state,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (
        ClientError,
        OSError,
        RuntimeError,
        TimeoutError,
        TypeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
