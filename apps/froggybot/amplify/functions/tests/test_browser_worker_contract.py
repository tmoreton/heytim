from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class BrowserWorkerContractTests(WorkerTestCase):
    def test_resume_instructions_preserve_latest_request_scope(self):
        from shared.browser_sessions import RESUME_PROMPT

        self.assertIn("most recent user request", RESUME_PROMPT)
        self.assertIn("read-only", RESUME_PROMPT)
        self.assertIn("do not revive older tasks", RESUME_PROMPT)
        self.assertIn("not new authorization", RESUME_PROMPT)

    def test_private_browser_is_attached_only_to_direct_browser_tools(self):
        managed = {
            "browserIdentifier": "aws.browser.v1",
            "sessionId": "01234567890123456789012345",
            "sessionName": "private-bot-session",
        }
        browser_tool = {"runtime": {"kind": "agentcore", "name": "browser"}}
        bot = {"name": "Engineer", "prompt": "Help", "skillVersions": {}}
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(self.agent.catalog, "resolve_tools_for_runtime", return_value=[browser_tool]),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
            patch("shared.browser_sessions.runtime_browser_session", return_value=managed) as browser,
        ):
            self.agent._invoke("owner", "bot", bot, history=[], event_id="turn")
            browser.assert_called_once_with(self.agent.table, self.agent.agentcore, "owner", "bot")
            payload = json.loads(self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"])
            self.assertEqual(payload["browser"]["sessionId"], managed["sessionId"])
            self.assertEqual(payload["browser"]["actorId"], payload["memory"]["actorId"])
            self.assertEqual(payload["browser"]["botId"], "bot")
            self.assertNotIn("profileId", payload["browser"])
            self.assertNotIn("liveViewUrl", payload["browser"])

            browser.reset_mock()
            self.agent._invoke("owner", "bot", bot, history=[], event_id="turn", group_context={"id": "work"})
            browser.assert_not_called()
            payload = json.loads(self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"])
            self.assertNotIn("browser", payload)

            self.agent.catalog.resolve_tools_for_runtime.return_value = []
            self.agent._invoke("owner", "bot", bot, history=[], event_id="turn")
            browser.assert_not_called()
            payload = json.loads(self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"])
            self.assertNotIn("browser", payload)

    def test_browser_handoff_failure_prevents_runtime_dispatch(self):
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(self.agent.catalog, "resolve_tools_for_runtime", return_value=[
                {"runtime": {"kind": "agentcore", "name": "browser"}},
            ]),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch("shared.browser_sessions.runtime_browser_session", side_effect=ValueError("Human control")),
        ):
            with self.assertRaisesRegex(ValueError, "Human control"):
                self.agent._invoke("owner", "bot", {"name": "Bot", "prompt": "Help", "skillVersions": {}},
                                   history=[], event_id="turn")
            self.agentcore.invoke_agent_runtime.assert_not_called()

    def test_browser_iam_does_not_grant_profile_enumeration_or_user_aws_credentials(self):
        infrastructure = Path(__file__).parents[2] / "infrastructure" / "browser-access.ts"
        policy = infrastructure.read_text()
        self.assertIn("account: 'aws'", policy)
        self.assertIn("resourceName: 'aws.browser.v1'", policy)
        self.assertIn("aws:RequestTag/frogbot:managed-by", policy)
        self.assertIn("aws:ResourceTag/frogbot:managed-by", policy)
        self.assertNotIn("ListBrowserProfiles", policy)
        self.assertNotIn("authenticatedUserIamRole", policy)
        self.assertNotIn("ConnectBrowserAutomationStream", policy)
