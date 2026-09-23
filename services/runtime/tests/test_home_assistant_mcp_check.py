from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from scripts import check_home_assistant_mcp as health


def test_assist_endpoint_accepts_only_instance_or_assist_path(monkeypatch) -> None:
    monkeypatch.setattr(health, "_validated_endpoint", lambda value: value)
    assert health.assist_endpoint("https://home.example.com") == (
        "https://home.example.com/api/mcp/assist"
    )
    assert health.assist_endpoint("https://home.example.com/api/mcp/") == (
        "https://home.example.com/api/mcp/assist"
    )
    with pytest.raises(ValueError):
        health.assist_endpoint("https://home.example.com/api/states")
    with pytest.raises(ValueError):
        health.assist_endpoint("https://home.example.com?token=secret")


def test_assist_capabilities_require_exact_discovered_tool_names() -> None:
    assert health.assist_capabilities({
        "assist__HassGetState", "HassTurnOn", "NotHassTurnOff",
    }) == {
        "read current state": True,
        "turn on": True,
        "turn off": False,
    }


def test_health_check_discovers_tools_without_calling_any(
    monkeypatch, capsys
) -> None:
    calls: list[str] = []

    @asynccontextmanager
    async def fake_transport(endpoint, headers):
        assert endpoint == "https://home.example.com/api/mcp/assist"
        assert headers == {"Authorization": "Bearer private-token"}
        calls.append("connect")
        yield (object(), object())

    class FakeSession:
        def __init__(self, *_streams):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            calls.append("initialize")

        async def list_tools(self, cursor=None):
            assert cursor is None
            calls.append("list_tools")
            return SimpleNamespace(
                tools=[SimpleNamespace(
                    name="assist__HassTurnOff",
                    inputSchema={"type": "object", "properties": {}},
                )], nextCursor=None
            )

        async def list_resources(self):
            calls.append("list_resources")
            return SimpleNamespace(resources=[
                SimpleNamespace(uri="homeassistant://assist/context-snapshot")
            ])

    monkeypatch.setattr(health, "_secure_streamable_http", fake_transport)
    monkeypatch.setattr(health, "ClientSession", FakeSession)

    asyncio.run(health.check("https://home.example.com/api/mcp/assist", "private-token"))

    assert calls == ["connect", "initialize", "list_tools", "list_resources"]
    output = capsys.readouterr().out
    assert "handshake succeeded" in output
    assert "turn off: available" in output
    assert "read current state: not exposed" in output
    assert "Schema-bearing action candidates: turn_off" in output
    assert "Context snapshot: available" in output
    assert "private-token" not in output
