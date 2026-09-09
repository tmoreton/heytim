from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from frogbot_runtime.artifacts import artifact_prefix_from_payload
from frogbot_runtime.memory import memory_context_from_payload
from frogbot_runtime.request import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_MESSAGE_CHARS,
    messages_from_payload,
)
from group_context import (
    GROUP_CONTEXT_SCHEMA_VERSION,
    MAX_BOTS,
    MAX_DECISION_CHARS,
    MAX_DECISIONS,
    MAX_MEMORY_CHARS,
    MAX_PEOPLE,
    MAX_ROUND_REPLIES,
    ROUND_ROLES,
    collaboration_instructions,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GROUP_PRODUCER = (
    REPOSITORY_ROOT / "apps/froggybot/amplify/functions/shared/group_chat.py"
)
ATTACHMENT_PRODUCER = (
    REPOSITORY_ROOT / "apps/froggybot/amplify/functions/api/support.py"
)
GROUP_SCHEMA = (
    Path(__file__).resolve().parents[1] / "contracts/group-context.v1.schema.json"
)


def _load_group_producer():
    spec = importlib.util.spec_from_file_location(
        "group_contract_producer", GROUP_PRODUCER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_assignments(path: Path) -> dict:
    assignments = {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            assignments[target.id] = ast.literal_eval(node.value)
        except TypeError, ValueError:
            continue
    return assignments


def test_group_consumer_limits_and_roles_match_amplify_producer() -> None:
    producer = _load_group_producer()
    schema = json.loads(GROUP_SCHEMA.read_text(encoding="utf-8"))

    assert MAX_PEOPLE == producer.MAX_GROUP_CONTEXT_PEOPLE
    assert MAX_BOTS == producer.MAX_GROUP_BOTS
    assert MAX_ROUND_REPLIES == producer.MAX_GROUP_ROUND_REPLIES
    assert MAX_MEMORY_CHARS == producer.MAX_GROUP_MEMORY_CHARS
    assert MAX_DECISIONS == producer.MAX_GROUP_DECISIONS
    assert MAX_DECISION_CHARS == producer.MAX_GROUP_DECISION_CHARS
    assert ROUND_ROLES == producer.ROUND_ROLES

    payload = producer.group_runtime_context(
        {"name": "Launch room", "memory": "Launch Friday."},
        [
            {"entity": "GROUP_USER", "name": "Taylor", "role": "owner"},
            {
                "entity": "GROUP_BOT",
                "botId": "chief",
                "name": "Chief",
                "tagline": "Coordinates.",
            },
        ],
        "chief",
        1,
        1,
    )
    assert collaboration_instructions(payload)
    Draft202012Validator(schema).validate(
        {"schemaVersion": GROUP_CONTEXT_SCHEMA_VERSION, **payload}
    )


def test_versioned_group_fixture_is_accepted_by_runtime() -> None:
    schema = json.loads(GROUP_SCHEMA.read_text(encoding="utf-8"))
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/group-context.v1.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)
    assert fixture["schemaVersion"] == GROUP_CONTEXT_SCHEMA_VERSION
    assert collaboration_instructions(fixture)


def test_worker_group_memory_identity_can_write_only_its_group_artifacts() -> None:
    path = REPOSITORY_ROOT / "apps/froggybot/amplify/functions/shared/memory_identity.py"
    spec = importlib.util.spec_from_file_location("memory_identity_producer", path)
    assert spec and spec.loader
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    group_id = "12345678-1234-1234-1234-123456789012"
    reply_id = "22345678-1234-1234-1234-123456789012"
    prefix = f"groups/{group_id}/artifacts/{reply_id}"
    payload = {
        "group": {},
        "artifacts": {"prefix": prefix},
        "memory": {
            "actorId": producer.group_memory_actor_id(group_id),
            "sessionId": producer.group_memory_session_id(group_id),
            "eventId": reply_id,
            "scope": "group",
        },
    }
    memory = memory_context_from_payload(payload)
    assert memory is not None
    assert artifact_prefix_from_payload(payload, memory.actor_id) == prefix


def test_attachment_limits_and_formats_match_amplify_producer() -> None:
    producer = _literal_assignments(ATTACHMENT_PRODUCER)
    format_specs = producer["ATTACHMENT_FORMATS"]
    document_formats = {
        spec[1] for spec in format_specs.values() if spec[0] == "document"
    }
    image_formats = {spec[1] for spec in format_specs.values() if spec[0] == "image"}

    assert MAX_ATTACHMENTS == producer["MAX_ATTACHMENTS_PER_MESSAGE"]
    assert MAX_ATTACHMENT_BYTES == producer["DOCUMENT_MAX_BYTES"]
    assert producer["IMAGE_MAX_BYTES"] <= MAX_ATTACHMENT_BYTES
    assert DOCUMENT_FORMATS == document_formats
    assert IMAGE_FORMATS == image_formats


def test_large_group_transcript_remains_accepted_without_losing_contributions():
    producer = _load_group_producer()
    assert producer.MAX_HISTORY_BLOCK_CHARS == MAX_MESSAGE_CHARS
    items = [
        {"sk": str(index), "status": "COMPLETE", "text": f"contribution-{index}:" + "a" * 15_000,
         "authorType": "bot", "authorId": str(index), "authorName": f"Bot {index}"}
        for index in range(4)
    ]
    history = producer.group_history_from_items(items, "synthesizer")
    validated = messages_from_payload({"messages": history})
    text = "".join(block["text"] for message in validated for block in message["content"])
    for index in range(4):
        assert f"contribution-{index}:" + "a" * 15_000 in text
