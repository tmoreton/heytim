from heytim_runtime.home_assistant_decisions import (
    assist_action_catalog,
    laya_advisory_candidate,
    single_entity_request,
)

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


def test_only_single_explicit_request_is_eligible() -> None:
    assert single_entity_request("Turn off the bedroom light", "bedroom light") == "turn_off"
    assert single_entity_request("Is the bedroom light on?", "bedroom light") == "read_state"
    for request in (
        "Do not turn off the bedroom light",
        "What if I turn off the bedroom light?",
        'My note says "turn off the bedroom light"',
        "Turn off the kitchen light",
        "Turn off the bedroom light and the kitchen light",
    ):
        assert single_entity_request(request, "bedroom light") is None


def test_laya_answer_is_advisory_and_cannot_override_grounding() -> None:
    common = {
        "request": "Turn off the bedroom light",
        "entity_alias": "bedroom light", "entity_id": "light.bedroom",
        "exposed_to_assist": True, "discovered_tools": TOOLS,
        "selected_label": "turn_off", "confidence": 0.99,
        "action_probability": 1.0, "truncated": False,
    }
    assert laya_advisory_candidate(**common) == {
        "abstractAction": "turn_off", "discoveredTool": "HassTurnOff",
        "entityId": "light.bedroom",
    }
    for changes in (
        {"request": "Do not turn off the bedroom light"},
        {"request": "Is the bedroom light on?", "selected_label": "turn_off"},
        {"exposed_to_assist": False},
        {"discovered_tools": []},
        {"confidence": 0.7},
        {"truncated": True},
    ):
        assert laya_advisory_candidate(**(common | changes)) is None
