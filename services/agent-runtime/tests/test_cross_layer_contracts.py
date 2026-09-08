from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from frogbot_runtime.request import (
    DOCUMENT_FORMATS,
    IMAGE_FORMATS,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
)
from group_context import (
    GROUP_CONTEXT_SCHEMA_VERSION,
    MAX_BOTS,
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
