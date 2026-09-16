from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
RUNTIME_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")
RUNTIME_NAMES = {
    "agentcore": {"browser", "code_interpreter"},
    "local": {
        "bot_manager",
        "calculator",
        "current_time",
        "image_generator",
        "meme_lord",
    },
    "stan_builtin": {"web_fetch"},
    "stan_plugin": {"todos"},
    "stan_subagent": {"generalist"},
}
MAX_TAGS = 6
TOOL_RISKS = {"read", "sandbox", "interactive"}
BOT_COLORS = {"#007A3D", "#58BEAA", "#FFAA34", "#6C5CE7", "#3984F6", "#F46A27", "#E95383"}
BOT_FIELDS = {
    "id",
    "version",
    "name",
    "tagline",
    "prompt",
    "color",
    "category",
    "author",
    "tags",
    "featured",
    "skillIds",
    "toolIds",
}
REPOSITORY = "tmoreton/frogbot-skills"
GATEWAY_TARGETS = ROOT / "infrastructure" / "gateway-targets.yaml"


def fail(message: str) -> None:
    raise ValueError(message)


def validate_public_metadata(item: dict, *, actions: bool = False) -> None:
    item_id = item.get("id", "item")
    for field, maximum in (("category", 48), ("author", 80)):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            fail(f"{item_id} must include a short {field}")
    tags = item.get("tags")
    if (
        not isinstance(tags, list)
        or len(tags) > MAX_TAGS
        or any(not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 32 for tag in tags)
    ):
        fail(f"{item_id} must include at most {MAX_TAGS} short tags")
    if actions:
        values = item.get("actions")
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 8
            or any(
                not isinstance(action, str)
                or not action.strip()
                or len(action.strip()) > 80
                for action in values
            )
        ):
            fail(f"{item_id} must include 1 to 8 short actions")
    if "featured" in item and not isinstance(item["featured"], bool):
        fail(f"{item_id} featured must be true or false")
    if "listed" in item and not isinstance(item["listed"], bool):
        fail(f"{item_id} listed must be true or false")


def main() -> int:
    catalog = json.loads((ROOT / "catalog.json").read_text())
    if catalog.get("schemaVersion") != 3:
        fail("catalog schemaVersion must be 3")
    if catalog.get("repository") != REPOSITORY:
        fail(f"catalog repository must be {REPOSITORY}")
    release = str(catalog.get("release", ""))
    if not re.fullmatch(r"skills-v[1-9][0-9]*", release):
        fail("catalog release must look like skills-v6")
    gateway_release = re.search(
        r"(?m)^  Release:\n(?:    .*\n)*?    Default: (\S+)$",
        GATEWAY_TARGETS.read_text(),
    )
    if gateway_release is None or gateway_release.group(1) != release:
        fail("gateway target release default must match catalog release")

    tools = catalog.get("tools")
    skills = catalog.get("skills")
    bots = catalog.get("bots")
    if not isinstance(tools, list) or not isinstance(skills, list) or not isinstance(bots, list):
        fail("catalog tools, skills, and bots must be arrays")

    tool_ids = {tool.get("id") for tool in tools}
    if (
        None in tool_ids
        or len(tool_ids) != len(tools)
        or any(not isinstance(tool_id, str) or not TOOL_ID_PATTERN.fullmatch(tool_id) for tool_id in tool_ids)
    ):
        fail("tool IDs must be present and unique")

    for tool in tools:
        validate_public_metadata(tool, actions=True)
        for field, maximum in (("name", 80), ("description", 240), ("provider", 80)):
            value = tool.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                fail(f"{tool.get('id')} must include a short {field}")
        if not isinstance(tool.get("enabled"), bool):
            fail(f"{tool.get('id')} enabled must be true or false")
        if tool.get("risk") not in TOOL_RISKS:
            fail(f"{tool.get('id')} must declare a supported risk")
        runtime = tool.get("runtime")
        if not isinstance(runtime, dict):
            fail(f"{tool.get('id')} must define a runtime binding")
        kind = runtime.get("kind")
        if kind == "gateway":
            operations = runtime.get("operations")
            if (
                not isinstance(operations, list)
                or not 1 <= len(operations) <= 8
                or len(set(operations)) != len(operations)
                or any(not isinstance(operation, str) or not RUNTIME_NAME_PATTERN.fullmatch(operation) for operation in operations)
            ):
                fail(f"{tool.get('id')} has invalid gateway operations")
        elif kind in RUNTIME_NAMES:
            if runtime.get("name") not in RUNTIME_NAMES[kind]:
                fail(f"{tool.get('id')} has an unsupported {kind} binding")
        else:
            fail(f"{tool.get('id')} has an unsupported runtime binding")
        schema_path = tool.get("schemaPath")
        credential = tool.get("credential")
        if credential and not schema_path:
            fail(f"{tool.get('id')} must name its reviewed OpenAPI schema")
        if schema_path:
            if not isinstance(schema_path, str) or not re.fullmatch(
                r"tools/[a-z0-9-]+/openapi\.yaml", schema_path
            ) or not (ROOT / schema_path).is_file():
                fail(f"{tool.get('id')} schemaPath is invalid")

    skill_ids: set[str] = set()
    for skill in skills:
        skill_id = skill.get("id")
        if not isinstance(skill_id, str) or not ID_PATTERN.fullmatch(skill_id):
            fail(f"invalid skill ID: {skill_id!r}")
        if skill_id in skill_ids:
            fail(f"duplicate skill ID: {skill_id}")
        skill_ids.add(skill_id)
        validate_public_metadata(skill)
        for field, maximum in (("name", 80), ("description", 240)):
            value = skill.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                fail(f"{skill_id} must include a short {field}")
        version = skill.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            fail(f"{skill_id} version must be a positive integer")

        expected_path = f"skills/{skill_id}/SKILL.md"
        if skill.get("path") != expected_path:
            fail(f"{skill_id} path must be {expected_path}")
        path = ROOT / expected_path
        if not path.is_file() or path.name != "SKILL.md":
            fail(f"missing SKILL.md for {skill_id}")
        content = path.read_text()
        if not content.startswith("---\n") or f"\nname: {skill_id}\n" not in content:
            fail(f"invalid frontmatter for {skill_id}")
        if "\nallowed-tools:" in content:
            fail(f"{skill_id} must declare required tools only in catalog.json")

        eval_path = path.parent / "evals.json"
        if not eval_path.is_file():
            fail(f"missing evals.json for {skill_id}")
        try:
            evals = json.loads(eval_path.read_text())
        except json.JSONDecodeError as exc:
            fail(f"invalid evals.json for {skill_id}: {exc.msg}")
        if not isinstance(evals, dict):
            fail(f"{skill_id} evals.json must be an object")
        for field in ("shouldTrigger", "shouldNotTrigger", "expectations"):
            values = evals.get(field)
            if (
                not isinstance(values, list)
                or len(values) < 3
                or len(values) != len(set(values))
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value.strip()) > 500
                    for value in values
                )
            ):
                fail(f"{skill_id} {field} must contain at least 3 unique short strings")

        skill_root = path.parent
        for candidate in skill_root.rglob("*"):
            if any(part in {"scripts", "bin"} for part in candidate.relative_to(skill_root).parts):
                fail(f"executable skill content is not allowed: {candidate}")
            if candidate.is_file() and candidate.suffix.lower() not in {".md", ".txt", ".json"}:
                fail(f"unsupported skill file type: {candidate}")

        required = skill.get("requiredToolIds", [])
        if not isinstance(required, list) or len(required) != len(set(required)):
            fail(f"{skill_id} requiredToolIds must be a unique list")
        unknown = set(required) - tool_ids
        if unknown:
            fail(f"{skill_id} references unknown tools: {sorted(unknown)}")

    packaged_skill_ids = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    orphaned = packaged_skill_ids - skill_ids
    if orphaned:
        fail(f"skill packages missing from catalog.json: {sorted(orphaned)}")

    packaged_tool_schemas = {
        str(path.relative_to(ROOT)) for path in (ROOT / "tools").glob("*/openapi.yaml")
    }
    listed_tool_schemas = {
        tool["schemaPath"] for tool in tools if isinstance(tool.get("schemaPath"), str)
    }
    orphaned_schemas = packaged_tool_schemas - listed_tool_schemas
    if orphaned_schemas:
        fail(f"tool schemas missing from catalog.json: {sorted(orphaned_schemas)}")

    bot_ids: set[str] = set()
    for bot in bots:
        bot_id = bot.get("id")
        if not isinstance(bot_id, str) or not ID_PATTERN.fullmatch(bot_id):
            fail(f"invalid bot ID: {bot_id!r}")
        if bot_id in bot_ids:
            fail(f"duplicate bot ID: {bot_id}")
        bot_ids.add(bot_id)
        unsupported_fields = set(bot) - BOT_FIELDS
        if unsupported_fields:
            fail(
                f"{bot_id} has unsupported bot fields: "
                f"{sorted(unsupported_fields)}"
            )
        validate_public_metadata(bot)
        for field, maximum in (("name", 48), ("tagline", 120), ("prompt", 12_000)):
            value = bot.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
                fail(f"{bot_id} must include a valid {field}")
        version = bot.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            fail(f"{bot_id} version must be a positive integer")
        if bot.get("color") not in BOT_COLORS:
            fail(f"{bot_id} must use a supported bot color")
        selected_skills = bot.get("skillIds")
        if (
            not isinstance(selected_skills, list)
            or len(selected_skills) > 12
            or any(not isinstance(item, str) for item in selected_skills)
            or len(selected_skills) != len(set(selected_skills))
            or set(selected_skills) - skill_ids
        ):
            fail(f"{bot_id} skillIds must reference up to 12 known skills")
        selected_tools = bot.get("toolIds", [])
        if (
            not isinstance(selected_tools, list)
            or len(selected_tools) > 12
            or any(not isinstance(item, str) for item in selected_tools)
            or len(selected_tools) != len(set(selected_tools))
            or set(selected_tools) - tool_ids
        ):
            fail(f"{bot_id} toolIds must reference up to 12 known tools")

        eval_path = ROOT / "bots" / bot_id / "evals.json"
        if not eval_path.is_file():
            fail(f"missing bots/{bot_id}/evals.json")
        try:
            scenarios = json.loads(eval_path.read_text()).get("scenarios")
        except (json.JSONDecodeError, AttributeError) as exc:
            fail(f"invalid evals.json for {bot_id}: {exc}")
        if not isinstance(scenarios, list) or len(scenarios) < 3:
            fail(f"{bot_id} evals must include at least 3 scenarios")
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                fail(f"{bot_id} eval scenario must be an object")
            prompt = scenario.get("prompt")
            expectations = scenario.get("expectations")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1_000:
                fail(f"{bot_id} eval prompt must be short text")
            if (
                not isinstance(expectations, list)
                or len(expectations) < 2
                or len(expectations) != len(set(expectations))
                or any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in expectations)
            ):
                fail(f"{bot_id} eval expectations must include at least 2 unique strings")

    packaged_bot_ids = {path.parent.name for path in (ROOT / "bots").glob("*/evals.json")}
    orphaned_bots = packaged_bot_ids - bot_ids
    if orphaned_bots:
        fail(f"bot evals missing from catalog.json: {sorted(orphaned_bots)}")

    print(f"Validated {len(skills)} skills, {len(tools)} tools, and {len(bots)} bots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
