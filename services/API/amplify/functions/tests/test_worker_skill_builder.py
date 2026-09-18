from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class WorkerSkillBuilderTests(WorkerTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.apply_bot_mutations = staticmethod(cls.direct_job.apply_bot_mutations)
        cls.mutation_globals = cls.direct_job.apply_bot_mutations.__globals__

    @staticmethod
    def _mutation(*, target_bot_id: str = "research") -> list[dict]:
        return [{
            "mutationId": str(uuid.uuid4()),
            "action": "create_skill",
            "value": {
                "targetBotId": target_bot_id,
                "name": "Competitor Brief",
                "description": "Compare competitors consistently.",
                "instructions": "Use available sources and mark unknowns.",
                "requiredToolIds": ["web_search", "shell"],
            },
        }]

    def test_chief_creates_private_skill_for_selected_bot(self) -> None:
        target = {
            "id": "research",
            "name": "Research",
            "toolIds": ["web_search"],
            "skillIds": ["deep-research"],
        }
        api = SimpleNamespace(
            _get_bot=MagicMock(return_value=target), _update_bot=MagicMock()
        )
        catalog = SimpleNamespace(
            get_skill=MagicMock(
                side_effect=self.mutation_globals["CatalogError"]("Skill not found")
            ),
            list_skills=MagicMock(return_value=[]),
            save_skill=MagicMock(),
        )

        with patch.dict(
            self.mutation_globals, {"_bot_api": lambda: api, "catalog": catalog}
        ):
            self.apply_bot_mutations(
                "user-1",
                {"id": "chief", "systemRole": "chief"},
                {},
                self._mutation(),
            )

        api._get_bot.assert_called_once_with("user-1", "research")
        saved = catalog.save_skill.call_args.args[1]
        self.assertNotIn("targetBotId", saved)
        self.assertEqual(saved["requiredToolIds"], ["web_search"])
        self.assertEqual(saved["visibility"], "private")
        api._update_bot.assert_called_once()
        self.assertEqual(api._update_bot.call_args.args[:2], ("user-1", "research"))
        self.assertEqual(api._update_bot.call_args.args[2]["skillIds"][0], "deep-research")

    def test_other_bot_cannot_create_skill_for_teammate(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only Chief"):
            self.apply_bot_mutations(
                "user-1", {"id": "writer"}, {}, self._mutation()
            )

    def test_full_bot_rejects_new_skill_before_saving(self) -> None:
        target = {
            "id": "research",
            "toolIds": ["web_search"],
            "skillIds": [f"skill-{index}" for index in range(12)],
        }
        api = SimpleNamespace(
            _get_bot=MagicMock(return_value=target), _update_bot=MagicMock()
        )
        catalog = SimpleNamespace(save_skill=MagicMock())
        with (
            patch.dict(
                self.mutation_globals, {"_bot_api": lambda: api, "catalog": catalog}
            ),
            self.assertRaisesRegex(ValueError, "maximum number of skills"),
        ):
            self.apply_bot_mutations(
                "user-1",
                {"id": "chief", "systemRole": "chief"},
                {},
                self._mutation(),
            )

        catalog.save_skill.assert_not_called()
