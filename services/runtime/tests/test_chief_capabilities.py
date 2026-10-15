from __future__ import annotations

import json
from pathlib import Path

import pytest

from heytim_runtime.capability_contract import dynamic_skills, tool_bindings
from heytim_runtime.client_contract import MAX_SKILLS_PER_BOT

CATALOG_ROOT = Path(__file__).resolve().parents[3] / "catalog"


def test_chief_full_catalog_recipe_is_accepted_without_incompatible_delegation() -> None:
    catalog = json.loads((CATALOG_ROOT / "catalog.json").read_text())
    chief = next(bot for bot in catalog["bots"] if bot["id"] == "chief")
    tools = {tool["id"]: tool for tool in catalog["tools"]}
    skills = {skill["id"]: skill for skill in catalog["skills"]}
    bot = {**chief, "tools": [tools[tool_id] for tool_id in chief["toolIds"]], "skills": [
        {**skills[skill_id], "instructions": (CATALOG_ROOT / skills[skill_id]["path"]).read_text()}
        for skill_id in chief["skillIds"]
    ]}
    bindings = tool_bindings(bot)
    assert len(bindings) == 12
    assert all(binding["kind"] != "stan_subagent" for binding in bindings)
    assert {binding["id"] for binding in bindings if binding["kind"] == "device"} == {
        "mac_computer", "mac_terminal",
    }
    assert len(dynamic_skills(bot)) == 17


def test_skill_limit_accepts_twenty_workflows_and_rejects_twenty_one() -> None:
    assert MAX_SKILLS_PER_BOT == 20
    skills = [{
        "id": f"skill-{index}", "name": f"Skill {index}",
        "description": "A bounded workflow.", "instructions": "Complete the requested workflow.",
    } for index in range(21)]
    assert len(dynamic_skills({"skills": skills[:20]})) == 20
    with pytest.raises(ValueError, match="at most 20"):
        dynamic_skills({"skills": skills})
