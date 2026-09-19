from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

CATALOG_URL = "https://heytim.ai/catalog.json"
TRUSTED_REPOSITORY = "tmoreton/heytim"


def _json_from_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "HeyTim-Evals/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        value = json.loads(response.read(1_000_001).decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object from {url}")
    return value


def _text_from_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"accept": "text/plain", "user-agent": "HeyTim-Evals/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        return response.read(100_001).decode("utf-8")


def _json_from_path(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError(f"Catalog is too large: {path}")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def _text_from_path(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > 100_000:
        raise ValueError(f"Skill document is too large: {path}")
    return raw.decode("utf-8")


def _skill_instructions(document: str) -> str:
    if not document.startswith("---\n"):
        raise ValueError("Skill document must start with YAML frontmatter")
    boundary = document.find("\n---\n", 4)
    if boundary < 0:
        raise ValueError("Skill document frontmatter is incomplete")
    instructions = document[boundary + 5 :].strip()
    if not instructions:
        raise ValueError("Skill instructions are empty")
    return instructions


def load_catalog_snapshot(
    catalog_path: Path | None = None,
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog_root: Path | None = None
    if catalog_path is None:
        catalog = _json_from_url(CATALOG_URL)
    else:
        resolved_catalog = catalog_path.expanduser().resolve()
        catalog = _json_from_path(resolved_catalog)
        catalog_root = resolved_catalog.parent
    if catalog.get("schemaVersion") != 3:
        raise ValueError("Unsupported capability catalog schema")
    if catalog.get("repository") != TRUSTED_REPOSITORY:
        raise ValueError("Capability catalog repository is not trusted")
    release = catalog.get("release")
    if not isinstance(release, str) or not re.fullmatch(r"skills-v[0-9]+", release):
        raise ValueError("Capability catalog release is missing")

    raw_skills = catalog.get("skills")
    raw_bots = catalog.get("bots")
    if not isinstance(raw_skills, list) or not isinstance(raw_bots, list):
        raise TypeError("Capability catalog collections are invalid")

    skills: dict[str, dict[str, Any]] = {}
    for raw in raw_skills:
        if not isinstance(raw, dict):
            raise TypeError("Capability catalog contains an invalid skill")
        skill_id = raw.get("id")
        path = raw.get("path")
        if (
            not isinstance(skill_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", skill_id)
            or not isinstance(path, str)
            or not re.fullmatch(r"skills/[a-z0-9][a-z0-9-]{0,63}/SKILL\.md", path)
        ):
            raise TypeError("Capability catalog skill metadata is invalid")
        if skill_id in skills:
            raise ValueError(f"Duplicate capability catalog skill: {skill_id}")
        document = (
            _text_from_url(f"https://heytim.ai/{path}")
            if catalog_root is None
            else _text_from_path(catalog_root / path)
        )
        skills[skill_id] = {
            "id": skill_id,
            "version": raw.get("version", 1),
            "name": raw.get("name", skill_id),
            "description": raw.get("description", "Reviewed HeyTim skill"),
            "instructions": _skill_instructions(document),
            "requiredToolIds": raw.get("requiredToolIds", []),
        }
    bots: dict[str, dict[str, Any]] = {}
    for raw in raw_bots:
        if not isinstance(raw, dict):
            raise TypeError("Capability catalog contains an invalid bot")
        bot_id = raw.get("id")
        if not isinstance(bot_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,63}", bot_id
        ):
            raise TypeError("Capability catalog bot metadata is invalid")
        if bot_id in bots:
            raise ValueError(f"Duplicate capability catalog bot: {bot_id}")
        bots[bot_id] = raw
    return release, skills, bots
