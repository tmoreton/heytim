// Generated from packages/heytim-contract/src/platform-contract.json. Do not edit directly.
import Foundation

public enum GeneratedAppConstraints {
  public static let botNameMaxLength = 48
  public static let botTaglineMaxLength = 120
  public static let botPromptMaxLength = 12000
  public static let groupNameMaxLength = 64
  public static let groupMemoryMaxLength = 4000
  public static let messageMaxLength = 8000
  public static let scheduleNameMaxLength = 64
  public static let schedulePromptMaxLength = 8000
  public static let scheduleDayOfMonthMin = 1
  public static let scheduleDayOfMonthMax = 28
  public static let skillNameMaxLength = 80
  public static let skillDescriptionMaxLength = 240
  public static let skillInstructionsMaxLength = 20000
  public static let memoryMaxLength = 16000
  public static let maxAttachmentsPerMessage = 5
  public static let maxToolsPerBot = 12
  public static let imageMaxBytes = 3750000
  public static let documentMaxBytes = 4500000
  public static let maxPhotoDimension = 1920
}

public enum GeneratedDeviceCapabilities {
  public static let version = 1
  public static let maxOperationsPerDevice = 8
  public static let operationsByTool: [String: [String]] = [
    "mac_computer": ["mac_computer_observe", "mac_computer_act_on_element", "mac_computer_type_into_element", "mac_computer_wait_for_state", "mac_computer_scroll"],
    "apple_health": ["apple_health_activity_summary", "apple_health_workouts", "apple_health_running_totals", "apple_health_steps"],
  ]
  public static let interactiveOperationsByTool: [String: [String]] = [
    "mac_computer": ["mac_computer_act_on_element", "mac_computer_type_into_element", "mac_computer_scroll"],
    "apple_health": [],
  ]
}
