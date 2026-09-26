"""Generated from packages/heytim-contract/src/platform-contract.json. Do not edit directly."""
from __future__ import annotations

DEVICE_CONTRACT_VERSION = 1
MAX_DEVICE_OPERATIONS = 8
DEVICE_OPERATION_PLATFORMS = {
    "mac_computer_observe": "macos",
    "mac_computer_act_on_element": "macos",
    "mac_computer_type_into_element": "macos",
    "mac_computer_wait_for_state": "macos",
    "mac_computer_scroll": "macos",
    "apple_health_activity_summary": "ios",
    "apple_health_workouts": "ios",
    "apple_health_running_totals": "ios",
    "apple_health_steps": "ios",
}
DEVICE_TOOL_IDS = frozenset(["mac_computer", "apple_health"])
DEVICE_TOOL_OPERATIONS = {
    "mac_computer": frozenset(["mac_computer_observe", "mac_computer_act_on_element", "mac_computer_type_into_element", "mac_computer_wait_for_state", "mac_computer_scroll"]),
    "apple_health": frozenset(["apple_health_activity_summary", "apple_health_workouts", "apple_health_running_totals", "apple_health_steps"]),
}
DEVICE_TOOL_INTERACTIVE_OPERATIONS = {
    "mac_computer": frozenset(["mac_computer_act_on_element", "mac_computer_type_into_element", "mac_computer_scroll"]),
    "apple_health": frozenset([]),
}
