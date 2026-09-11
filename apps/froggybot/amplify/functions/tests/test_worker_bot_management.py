from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class WorkerBotManagementTests(WorkerTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.apply_bot_mutations = staticmethod(cls.direct_job.apply_bot_mutations)
        cls.bot_mutation_globals = cls.direct_job.apply_bot_mutations.__globals__

    def test_direct_chief_invocation_receives_bot_manager_context(self) -> None:
        bot = {
            "id": "chief",
            "name": "Chief",
            "prompt": "Coordinate.",
            "systemRole": "chief",
            "skillVersions": {},
            "toolIds": ["current_time"],
        }
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog,
                "resolve_tools_for_runtime",
                return_value=[
                    {
                        "id": "bot_manager",
                        "risk": "sandbox",
                        "runtime": {"kind": "local", "name": "bot_manager"},
                    }
                ],
            ) as resolve_tools,
            patch.object(
                self.agent.catalog,
                "list_bot_templates",
                return_value=[{"id": "meme-maker", "name": "Meme Maker"}],
            ),
            patch.object(
                self.agent.catalog,
                "list_tools",
                return_value=[{"id": "meme_lord", "name": "Meme Lord"}],
            ),
            patch.object(
                self.agent.catalog,
                "list_skills",
                return_value=[{"id": "meme-maker", "name": "Meme Maker"}],
            ),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
        ):
            self.agent._invoke(
                "user-1",
                "chief",
                bot,
                history=[],
                event_id="turn-1",
                allow_bot_management=True,
            )

        self.assertIn("bot_manager", resolve_tools.call_args.args[1])
        payload = json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )
        self.assertEqual(payload["bot"]["systemRole"], "chief")
        self.assertEqual(
            payload["botManagement"]["templates"][0]["id"], "meme-maker"
        )

    def test_scheduled_chief_invocation_does_not_receive_bot_manager(self) -> None:
        bot = {
            "name": "Chief",
            "prompt": "Coordinate.",
            "systemRole": "chief",
            "skillVersions": {},
            "toolIds": ["current_time"],
        }
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog, "resolve_tools_for_runtime", return_value=[]
            ) as resolve_tools,
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
        ):
            self.agent._invoke(
                "user-1", "chief", bot, history=[], event_id="turn-1"
            )

        self.assertNotIn("bot_manager", resolve_tools.call_args.args[1])
        payload = json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )
        self.assertNotIn("botManagement", payload)

    def test_chief_stays_available_during_catalog_rollout(self) -> None:
        bot = {
            "name": "Chief",
            "prompt": "Coordinate.",
            "systemRole": "chief",
            "skillVersions": {},
            "toolIds": ["current_time", "bot_manager"],
        }

        def resolve(_user_id, tool_ids):
            if tool_ids == ["bot_manager"]:
                raise self.agent.CatalogError("Unknown tools: bot_manager")
            return []

        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog,
                "resolve_tools_for_runtime",
                side_effect=resolve,
            ) as resolve_tools,
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
        ):
            result = self.agent._invoke(
                "user-1",
                "chief",
                bot,
                history=[],
                event_id="turn-1",
                allow_bot_management=True,
            )

        self.assertEqual(result.text, "Done")
        self.assertEqual(resolve_tools.call_args_list[-1].args[1], ["current_time"])
        payload = json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )
        self.assertNotIn("botManagement", payload)

    def test_direct_job_applies_a_clean_bot_mutation_before_completion(self) -> None:
        turn = {
            "pk": "CHAT#user-1#chief",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "status": "PENDING",
            "createdAt": "now",
        }
        bot = {
            "id": "chief",
            "name": "Chief",
            "systemRole": "chief",
            "toolIds": [],
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#chief")] = bot
        mutation = {
            "mutationId": str(uuid.uuid4()),
            "action": "install_template",
            "value": {"templateId": "meme-maker"},
        }
        result = self.agent.AgentInvocationResult(
            text="Meme Maker was added.", bot_mutations=[mutation]
        )
        with (
            patch.object(self.direct_job, "_account_is_active", return_value=True),
            patch.object(
                self.direct_job.catalog, "unapproved_tools", return_value=[]
            ),
            patch.object(self.direct_job, "_claim_work", return_value="lease-1"),
            patch.object(self.direct_job, "_invoke", return_value=result),
            patch.object(self.direct_job, "record_invocation_usage"),
            patch.object(self.direct_job, "apply_bot_mutations") as apply,
            patch.object(
                self.direct_job, "_collect_generated_artifacts", return_value=[]
            ),
            patch.object(
                self.direct_job, "_finish_work", return_value="finished-at"
            ),
            patch.object(self.direct_job, "_update_schedule_result"),
            patch.object(self.direct_job, "_queue_reply_notification"),
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "chief", "turnKey": turn["sk"]},
            )

        apply.assert_called_once_with("user-1", bot, turn, [mutation])

    def test_create_mutation_uses_a_replay_safe_bot_id(self) -> None:
        mutation_id = str(uuid.uuid4())
        value = {
            "name": "Meme Maker",
            "tagline": "Makes memes.",
            "prompt": "Caption supplied images.",
            "color": "#E95383",
            "toolIds": ["meme_lord"],
            "skillIds": ["meme-maker"],
        }
        api = SimpleNamespace(
            _bot_values=MagicMock(return_value={"validated": True}),
            _put_bot=MagicMock(),
        )

        def save(_user_id, _values, bot_id):
            self.table.items[("USER#user-1", f"BOT#{bot_id}")] = {
                "id": bot_id,
                "name": value["name"],
            }

        api._put_bot.side_effect = save
        raw = [
            {
                "mutationId": mutation_id,
                "action": "create",
                "value": value,
            }
        ]
        with patch.dict(self.bot_mutation_globals, {"_bot_api": lambda: api}):
            self.apply_bot_mutations(
                "user-1", {"systemRole": "chief"}, {}, raw
            )
            self.apply_bot_mutations(
                "user-1", {"systemRole": "chief"}, {}, raw
            )

        api._put_bot.assert_called_once()
        self.assertEqual(api._put_bot.call_args.kwargs["bot_id"], f"ai-{mutation_id}")

    def test_mutation_rejects_non_chief_and_scheduled_runs(self) -> None:
        raw = [
            {
                "mutationId": str(uuid.uuid4()),
                "action": "install_template",
                "value": {"templateId": "meme-maker"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "direct Chief"):
            self.apply_bot_mutations(
                "user-1", {"systemRole": "specialist"}, {}, raw
            )
        with self.assertRaisesRegex(ValueError, "direct Chief"):
            self.apply_bot_mutations(
                "user-1", {"systemRole": "chief"}, {"source": "schedule"}, raw
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
