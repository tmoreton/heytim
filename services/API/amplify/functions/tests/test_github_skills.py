from __future__ import annotations

import base64
from unittest.mock import Mock, patch

from api_test_case import ApiTestCase
from catalog_test_fakes import FakeTable
from shared.catalog import CatalogError, CatalogService

SHA = "a" * 40


class GitHubSkillsTests(ApiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.github = cls.handler.authenticated_routes.scan_github_skills.__globals__

    def test_rejects_non_github_and_ambiguous_urls(self) -> None:
        for url in (
            "http://github.com/mattpocock/skills",
            "https://github.com.evil.test/mattpocock/skills",
            "https://github.com:443/mattpocock/skills",
            "https://user@github.com/mattpocock/skills",
            "https://github.com/mattpocock/skills?next=https://evil.test",
            "https://github.com/mattpocock/skills/blob/main/README.md",
            "https://github.com/mattpocock/skills/tree/main/../private",
        ):
            with self.subTest(url=url), self.assertRaises(self.support.ApiError):
                self.github["_parse_url"](url)

    def test_scans_repository_and_returns_pinned_blob_choices(self) -> None:
        tree = {
            "truncated": False,
            "tree": [
                {"type": "blob", "path": "skills/engineering/research/SKILL.md", "sha": SHA, "size": 900},
                {"type": "blob", "path": "skills/engineering/research/script.py", "sha": SHA, "size": 500},
                {"type": "blob", "path": "SKILL.md", "sha": SHA, "size": 500},
            ],
        }
        fetch = Mock(side_effect=[{"default_branch": "main"}, tree])
        with patch.dict(self.github, {"_github_json": fetch}):
            result = self.github["scan_github_skills"]({"url": "https://github.com/mattpocock/skills"})
        self.assertEqual(result["repository"], "mattpocock/skills")
        self.assertEqual([item["name"] for item in result["skills"]], ["skills", "research"])
        self.assertEqual(result["skills"][1]["blobSha"], SHA)
        self.assertEqual(
            result["skills"][1]["sourceUrl"],
            "https://github.com/mattpocock/skills/blob/main/skills/engineering/research/SKILL.md",
        )
        self.assertIn("/git/trees/main?recursive=1", fetch.call_args_list[1].args[0])

    def test_direct_file_does_not_scan_large_repository(self) -> None:
        fetch = Mock(return_value={"type": "file", "sha": SHA, "size": 1200})
        with patch.dict(self.github, {"_github_json": fetch}):
            result = self.github["scan_github_skills"](
                {"url": "https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md"}
            )
        self.assertEqual(len(result["skills"]), 1)
        self.assertIn("/contents/skills/productivity/grilling/SKILL.md?ref=main", fetch.call_args.args[0])

    def test_preview_decodes_only_skill_text_and_flags_external_files(self) -> None:
        source = (
            "---\nname: research\ndescription: >-\n  Research a topic against\n  primary sources.\n"
            "disable-model-invocation: true\n---\nRead [guide](references/guide.md) first.\n"
        ).encode()
        blob = {
            "encoding": "base64", "sha": SHA, "size": len(source),
            "content": base64.b64encode(source).decode()[:60] + "\n" + base64.b64encode(source).decode()[60:],
        }
        with patch.dict(self.github, {"_github_json": Mock(return_value=blob)}):
            result = self.github["preview_github_skill"](
                {
                    "repository": "mattpocock/skills",
                    "reference": "main",
                    "path": "skills/engineering/research/SKILL.md",
                    "blobSha": SHA,
                }
            )
        self.assertEqual(result["description"], "Research a topic against primary sources.")
        self.assertEqual(result["instructions"], "Read [guide](references/guide.md) first.")
        self.assertEqual(len(result["warnings"]), 2)

    def test_rejects_oversized_or_mismatched_blob(self) -> None:
        value = {
            "repository": "mattpocock/skills", "reference": "main",
            "path": "research/SKILL.md", "blobSha": SHA,
        }
        with patch.dict(self.github, {"_github_json": Mock(return_value={"encoding": "base64", "sha": SHA, "size": 36_000, "content": "AA=="})}), self.assertRaises(self.support.ApiError):
            self.github["preview_github_skill"](value)
        with patch.dict(self.github, {"_github_json": Mock(return_value={"encoding": "base64", "sha": SHA, "size": 9, "content": "AA=="})}), self.assertRaises(self.support.ApiError):
            self.github["preview_github_skill"](value)

    def test_truncated_repository_requires_direct_link(self) -> None:
        fetch = Mock(side_effect=[{"default_branch": "main"}, {"tree": [], "truncated": True}])
        with patch.dict(self.github, {"_github_json": fetch}), self.assertRaisesRegex(self.support.ApiError, "direct SKILL.md"):
            self.github["scan_github_skills"]({"url": "https://github.com/mattpocock/skills"})

    def test_saved_copy_keeps_source_without_granting_tools(self) -> None:
        catalog = CatalogService(FakeTable(), refresh_on_read=False)
        source = "https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md"
        value = {
            "name": "Grilling", "description": "Stress test an idea.",
            "instructions": "Ask precise follow-up questions.",
            "requiredToolIds": [], "visibility": "private", "sourceUrl": source,
        }
        skill = catalog.save_skill("owner", value)
        self.assertEqual(catalog.get_skill("owner", skill["id"])["sourceUrl"], source)
        self.assertEqual(skill["requiredToolIds"], [])
        with self.assertRaisesRegex(CatalogError, "sourceUrl"):
            catalog.save_skill("owner", {**value, "sourceUrl": "https://evil.test/SKILL.md"})
