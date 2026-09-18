from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "apps" / "website" / "dist"


class CatalogTests(unittest.TestCase):
    def test_catalog_points_at_current_repository(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        self.assertEqual(catalog["repository"], "tmoreton/heytim-bots")

    def test_gateway_targets_default_to_the_catalog_release(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        template = (ROOT / "infrastructure" / "gateway-targets.yaml").read_text()
        release_default = re.search(
            r"(?m)^  Release:\n(?:    .*\n)*?    Default: (\S+)$",
            template,
        )

        self.assertIsNotNone(release_default)
        self.assertEqual(release_default.group(1), catalog["release"])

    def test_gateway_role_can_only_read_declared_provider_credentials(self) -> None:
        template = (ROOT / "infrastructure" / "gateway-targets.yaml").read_text()

        self.assertIn("!Ref XCredentialSecretArn", template)
        self.assertIn("!Ref YouTubeCredentialSecretArn", template)
        self.assertIn(
            "apikeycredentialprovider/${XCredentialProviderName}", template
        )
        self.assertIn(
            "apikeycredentialprovider/${YouTubeCredentialProviderName}", template
        )
        self.assertIn(
            "workload-identity/${GatewayIdentifier}", template
        )
        self.assertIn("token-vault/default'", template)
        self.assertNotIn("GatewayName:", template)
        self.assertIn("releases/${Release}/x/openapi.yaml", template)
        self.assertIn("releases/${Release}/youtube/openapi.yaml", template)
        self.assertNotIn("releases/${Release}/*", template)
        self.assertNotIn("apikeycredentialprovider/*", template)
        self.assertNotIn("token-vault/*", template)
        self.assertNotIn("workload-identity-directory/*", template)
        self.assertNotIn("secret:bedrock-agentcore-identity!*'", template)
        self.assertNotIn("bedrock-agentcore:GetApiKeyCredential\n", template)
        self.assertNotIn("bedrock-agentcore-identity!.+$", template)
        self.assertIn("bedrock-agentcore-identity![A-Za-z0-9/_+=.@-]+$", template)
        self.assertIn("CredentialPrefix: Bearer", template)

        release_guide = " ".join((ROOT / "README.md").read_text().split())
        self.assertIn("YouTube Data API **Search Queries** daily quota", release_guide)
        self.assertIn("Raise that quota or delay publication", release_guide)

    def test_featured_skills_are_core_group_workflows(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        featured = {skill["id"] for skill in catalog["skills"] if skill.get("featured")}
        self.assertEqual(
            featured,
            {
                "group-intake",
                "trip-planner",
                "event-planner",
                "group-decision",
                "shared-budget",
            },
        )

    def test_bot_configs_keep_runtime_choices_and_credentials_out(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        allowed = {
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
        for bot in catalog["bots"]:
            self.assertLessEqual(set(bot), allowed, bot["id"])
            self.assertFalse(
                {"model", "provider", "reasoning", "mode", "token", "credential"}
                & set(bot),
                bot["id"],
            )

    def test_chief_is_a_minimal_public_bot(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        chief = next(bot for bot in catalog["bots"] if bot["id"] == "chief")
        skill_builder = next(
            skill for skill in catalog["skills"] if skill["id"] == "skill-builder"
        )

        self.assertEqual(chief["name"], "Chief")
        self.assertEqual(chief["version"], 7)
        self.assertEqual(chief["color"], "#FFBC3B")
        self.assertEqual(chief["toolIds"], ["current_time", "bot_manager"])
        self.assertIn("skill-builder", chief["skillIds"])
        self.assertEqual(skill_builder["requiredToolIds"], [])
        self.assertNotIn("systemRole", chief)
        self.assertNotIn("requiredOnSetup", chief)

    def test_implementation_helpers_are_not_listed(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        tools = {tool["id"]: tool for tool in catalog["tools"]}
        for tool_id in (
            "web",
            "calculator",
            "current_time",
            "delegate",
            "bot_manager",
            "meme_lord",
        ):
            self.assertFalse(tools[tool_id].get("listed", True), tool_id)
        self.assertFalse(tools["browser"].get("featured", False))

    def test_meme_lord_is_the_only_public_meme_capability(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        meme_tool_ids = {
            tool["id"] for tool in catalog["tools"] if "meme" in tool["id"]
        }
        visible_tools = [tool for tool in catalog["tools"] if tool.get("listed", True)]
        meme_tools = [tool for tool in visible_tools if "meme" in tool["id"]]
        meme_skills = [skill for skill in catalog["skills"] if "meme" in skill["id"]]
        meme_bots = [bot for bot in catalog["bots"] if "meme" in bot["id"]]

        self.assertEqual(meme_tool_ids, {"meme_lord"})
        self.assertEqual(meme_tools, [])
        self.assertEqual([skill["name"] for skill in meme_skills], ["Meme Lord"])
        self.assertEqual([bot["name"] for bot in meme_bots], ["Meme Lord"])

    def test_creator_bots_bundle_their_reviewed_capabilities(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        bots = {bot["id"]: bot for bot in catalog["bots"]}
        skills = {skill["id"]: skill for skill in catalog["skills"]}

        youtube = bots["youtube-studio"]
        self.assertEqual(youtube["name"], "Creator Studio")
        self.assertEqual(
            youtube["skillIds"],
            ["youtube-strategy", "youtube-thumbnail-director"],
        )
        youtube_tools = {
            tool_id
            for skill_id in youtube["skillIds"]
            for tool_id in skills[skill_id]["requiredToolIds"]
        }
        self.assertEqual(skills["youtube-thumbnail-director"]["version"], 3)
        self.assertEqual(
            set(skills["youtube-thumbnail-director"]["requiredToolIds"]),
            {"image_generator"},
        )
        self.assertEqual(
            youtube_tools,
            {"web_search", "image_generator"},
        )
        self.assertIn("Visually verify the returned image's wording", youtube["prompt"])
        self.assertIn("unverified or still-flawed result as a draft", youtube["prompt"])
        image_tool = next(
            tool for tool in catalog["tools"] if tool["id"] == "image_generator"
        )
        self.assertIn("Use requested text and recent images", image_tool["actions"])
        self.assertNotIn("Place exact text", image_tool["actions"])
        thumbnail_description = skills["youtube-thumbnail-director"]["description"]
        self.assertIn("requested text overlays", thumbnail_description)
        self.assertNotIn("exact overlays", thumbnail_description)

        thumbnail_instructions = (
            ROOT / "skills" / "youtube-thumbnail-director" / "SKILL.md"
        ).read_text()
        self.assertIn("the tool's success message alone is not proof", thumbnail_instructions)
        self.assertIn("make at most one retry", thumbnail_instructions)
        self.assertIn("label the image as a draft", thumbnail_instructions)

        trend = bots["trend-scout"]
        self.assertEqual(trend["skillIds"], ["trend-scout"])
        self.assertEqual(
            set(skills["trend-scout"]["requiredToolIds"]),
            {"web_search", "delegate"},
        )

    def test_everyday_bots_use_least_privilege_capability_bundles(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text())
        bots = {bot["id"]: bot for bot in catalog["bots"]}
        skills = {skill["id"]: skill for skill in catalog["skills"]}
        tools = {tool["id"]: tool for tool in catalog["tools"]}
        expected_tools = {
            "morning-brief": {"web", "web_search", "current_time", "task_list"},
            "social-writer": {"web", "web_search", "current_time"},
            "meeting-prep": {"web", "web_search", "current_time", "task_list"},
            "career-coach": {"web", "web_search", "code_interpreter"},
        }

        for bot_id, tool_ids in expected_tools.items():
            self.assertEqual(bots[bot_id]["skillIds"], [bot_id])
            self.assertEqual(set(skills[bot_id]["requiredToolIds"]), tool_ids)
            self.assertFalse(
                {"browser", "image_generator", "bot_manager"} & tool_ids,
                bot_id,
            )

            self.assertTrue(
                all(tools[tool_id]["risk"] != "interactive" for tool_id in tool_ids),
                bot_id,
            )

        self.assertFalse(tools["x_search"]["enabled"])
        self.assertFalse(tools["youtube_search"]["enabled"])

        self.assertTrue(bots["morning-brief"]["featured"])
        self.assertTrue(bots["social-writer"]["featured"])
        self.assertTrue(bots["meeting-prep"]["featured"])
        self.assertFalse(bots["career-coach"]["featured"])

    def test_build_publishes_every_skill_document(self) -> None:
        source_skills = sorted(
            path.relative_to(ROOT) for path in (ROOT / "skills").glob("*/SKILL.md")
        )
        published_skills = sorted(
            path.relative_to(OUTPUT) for path in (OUTPUT / "skills").glob("*/SKILL.md")
        )
        self.assertEqual(published_skills, source_skills)

    def test_build_publishes_every_bot_evaluation(self) -> None:
        source_evals = sorted(
            path.relative_to(ROOT) for path in (ROOT / "bots").glob("*/evals.json")
        )
        published_evals = sorted(
            path.relative_to(OUTPUT) for path in (OUTPUT / "bots").glob("*/evals.json")
        )
        self.assertEqual(published_evals, source_evals)

    def test_build_publishes_every_tool_schema(self) -> None:
        source_schemas = sorted(
            path.relative_to(ROOT) for path in (ROOT / "tools").glob("*/openapi.yaml")
        )
        published_schemas = sorted(
            path.relative_to(OUTPUT) for path in (OUTPUT / "tools").glob("*/openapi.yaml")
        )
        self.assertEqual(published_schemas, source_schemas)


if __name__ == "__main__":
    unittest.main()
