from heytim_runtime.home_assistant_decisions import assist_action_catalog

TOOLS = [
    {"name": name, "inputSchema": {"type": "object", "properties": {}}}
    for name in ("HassTurnOn", "HassTurnOff", "GetLiveContext")
]


def test_catalog_uses_only_discovered_schema_bearing_tools() -> None:
    assert assist_action_catalog(TOOLS) == {
        "turn_on": "HassTurnOn",
        "turn_off": "HassTurnOff",
        "read_state": "GetLiveContext",
    }
    assert "turn_on" not in assist_action_catalog(TOOLS + [TOOLS[0]])
    assert "turn_off" not in assist_action_catalog([
        {"name": "HassTurnOff", "inputSchema": {"type": "array"}}
    ])
    assert assist_action_catalog(TOOLS + [
        {"name": "HassGetState", "inputSchema": {"type": "object", "properties": {}}}
    ])["read_state"] == "HassGetState"
