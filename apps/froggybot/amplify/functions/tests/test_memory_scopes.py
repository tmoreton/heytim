from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class MemoryScopeWorkerTests(WorkerTestCase):
    def test_memory_cleanup_job_dispatches_by_scope(self) -> None:
        delete_session = MagicMock()
        request = {
            "type": "DELETE_MEMORY_SESSION",
            "actorId": "actor-1",
            "sessionId": "session-1",
        }

        with patch.object(self.handler, "_delete_memory_session", delete_session):
            self.handler._process({"body": json.dumps(request)})

        delete_session.assert_called_once_with(request)

    def test_group_invocation_forwards_only_the_supplied_group_memory_scope(
        self,
    ) -> None:
        memory = {
            "actorId": "group-actor",
            "sessionId": "group-session",
            "eventId": "reply-1",
            "scope": "group",
            "userText": "Plan the launch.",
        }
        self.agentcore.invoke_agent_runtime.return_value = {"response": MagicMock()}
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog, "resolve_tools_for_runtime", return_value=[]
            ),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="done"),
        ):
            self.agent._invoke(
                "bot-owner",
                "bot-1",
                {
                    "name": "Research",
                    "prompt": "Research carefully.",
                    "skillVersions": {},
                    "toolIds": [],
                },
                history=[],
                session_scope="group:group-1:bot:bot-1",
                group_context={"name": "Launch"},
                memory=memory,
            )

        payload = json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )
        self.assertEqual(payload["memory"], memory)
