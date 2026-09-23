from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from heytim_runtime import home_assistant_fast_path as fast

SNAPSHOT = (
    "Live Context: An overview of the areas and the devices in this smart home:\n"
    "- names: Bedroom light\n"
    "  domain: light\n"
    "  state: off\n"
    "  areas: Bedroom\n"
    "- names: Kitchen light\n"
    "  domain: light\n"
    "  state: on\n"
    "  areas: Kitchen\n"
)
TOOLS = [
    SimpleNamespace(
        name=f"assist__homeassistant__{name}",
        inputSchema={"type": "object", "properties": {"name": {"type": "string"}}},
    )
    for name in ("HassTurnOn", "HassTurnOff", "GetLiveContext")
]
HINT = {
    "selectedLabel": "turn_on",
    "confidence": 0.96,
    "actionProbability": 0.98,
    "truncated": False,
}
PAYLOAD = {
    "homeAssistantHint": HINT,
    "bot": {"tools": [{"id": "ha_1", "risk": "interactive"}]},
    "memory": {"eventId": "4bd58126-177a-4de4-b1d0-5e05a45bd4b2"},
}
BINDING = {
    "id": "ha_1",
    "kind": "mcp",
    "authType": "home_assistant_token",
    "endpoint": "https://example.com/api/mcp/assist",
    "secretArn": "private",
}


def test_advisory_and_entity_match_are_strict() -> None:
    assert fast._hint_label(HINT) == "turn_on"
    assert fast._hint_label(HINT | {"confidence": 0.5}) is None
    assert fast._hint_label(HINT | {"truncated": True}) is None
    assert (
        fast._hint_label(HINT | {"selectedLabel": "read_state", "confidence": 0.24})
        == "read_state"
    )
    assert fast._matching_entity(SNAPSHOT, "Turn on the bedroom light", "turn_on") == {
        "name": "Bedroom light",
        "domain": "light",
        "state": "off",
    }
    assert fast._matching_entity(
        SNAPSHOT.replace("state: off", "state: 'off'"),
        "Turn on the bedroom light", "turn_on",
    ) == {"name": "Bedroom light", "domain": "light", "state": "off"}
    assert (
        fast._matching_entity(SNAPSHOT, "Do not turn on the bedroom light", "turn_on")
        is None
    )
    assert (
        fast._matching_entity(SNAPSHOT, "Turn on the bedroom light", "turn_off") is None
    )
    assert (
        fast._matching_entity(
            SNAPSHOT + SNAPSHOT, "Turn on the bedroom light", "turn_on"
        )
        is None
    )
    assert fast._action_tool(TOOLS, "turn_on") == "assist__homeassistant__HassTurnOn"
    unsafe = SimpleNamespace(
        name="assist__homeassistant__HassTurnOn",
        inputSchema={"type": "object", "properties": {"name": {"type": "integer"}}},
    )
    assert fast._action_tool([unsafe], "turn_on") is None


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.snapshot = SNAPSHOT

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def initialize(self):
        return None

    async def list_tools(self, cursor=None):
        return SimpleNamespace(tools=TOOLS, nextCursor=None)

    async def list_resources(self):
        return SimpleNamespace(resources=[SimpleNamespace(uri=fast.SNAPSHOT_URI)])

    async def read_resource(self, _uri):
        return SimpleNamespace(contents=[SimpleNamespace(text=self.snapshot)])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        self.snapshot = self.snapshot.replace("  state: 'off'", "  state: 'on'", 1)
        self.snapshot = self.snapshot.replace("  state: off", "  state: on", 1)
        return SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(text='{"success":true,"result":"Done"}')],
        )


def _install_fake_connection(
    monkeypatch: pytest.MonkeyPatch, session: FakeSession
) -> None:
    monkeypatch.setattr(fast, "tool_bindings", lambda _bot: [BINDING])
    monkeypatch.setattr(fast, "_home_assistant_access_token", lambda _binding: "secret")
    monkeypatch.setattr(fast, "ClientSession", lambda *_args: session)

    @asynccontextmanager
    async def fake_stream(*_args):
        yield (None, None)

    monkeypatch.setattr(fast, "_secure_streamable_http", fake_stream)


@pytest.mark.parametrize("quoted_state", [False, True])
def test_change_requires_exact_approval_and_then_confirms(
    monkeypatch: pytest.MonkeyPatch, quoted_state: bool,
) -> None:
    asyncio.run(_change_requires_exact_approval_and_then_confirms(monkeypatch, quoted_state))


async def _change_requires_exact_approval_and_then_confirms(
    monkeypatch: pytest.MonkeyPatch, quoted_state: bool,
) -> None:
    session = FakeSession()
    if quoted_state:
        session.snapshot = SNAPSHOT.replace("state: off", "state: 'off'")
    _install_fake_connection(monkeypatch, session)
    request = "Turn on the bedroom light"
    first = await fast.maybe_route_home_assistant(PAYLOAD, request)
    assert first is not None and "pendingApproval" in first
    assert session.calls == []
    proposal = first["pendingApproval"]
    assert proposal["toolName"] == "assist__homeassistant__HassTurnOn"
    assert proposal["input"] == {"name": "Bedroom light"}
    wrong = PAYLOAD | {
        "actionApproval": {
            "id": proposal["id"],
            "digest": "wrong",
            "toolUseId": proposal["toolUseId"],
        }
    }
    assert "terminalError" in (await fast.maybe_route_home_assistant(wrong, request))
    assert session.calls == []
    approved = PAYLOAD | {
        "actionApproval": {key: proposal[key] for key in ("id", "digest", "toolUseId")}
    }
    assert await fast.maybe_route_home_assistant(approved, request) == {
        "text": "Bedroom light is on, confirmed by Home Assistant."
    }
    assert session.calls == [
        ("assist__homeassistant__HassTurnOn", {"name": "Bedroom light"})
    ]


def test_wrong_model_action_falls_back_without_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_wrong_model_action_falls_back_without_call(monkeypatch))


async def _wrong_model_action_falls_back_without_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    _install_fake_connection(monkeypatch, session)
    assert (
        await fast.maybe_route_home_assistant(PAYLOAD, "Turn off the bedroom light")
        is None
    )
    assert session.calls == []
    no_grant = PAYLOAD | {"bot": {"tools": [{"id": "ha_1", "risk": "read"}]}}
    assert (
        await fast.maybe_route_home_assistant(no_grant, "Turn on the bedroom light")
        is None
    )
    assert session.calls == []


def test_status_question_uses_snapshot_without_action_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_status_question_uses_snapshot_without_action_call(monkeypatch))


async def _status_question_uses_snapshot_without_action_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    _install_fake_connection(monkeypatch, session)
    hint = HINT | {"selectedLabel": "read_state", "confidence": 0.24}
    result = await fast.maybe_route_home_assistant(
        PAYLOAD | {"homeAssistantHint": hint}, "Is the bedroom light on?"
    )
    assert result == {"text": "Home Assistant shows Bedroom light is off."}
    assert session.calls == []
