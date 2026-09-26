import Foundation

public indirect enum JSONValue: Codable, Hashable, Sendable {
  case object([String: JSONValue])
  case array([JSONValue])
  case string(String)
  case number(Double)
  case bool(Bool)
  case null

  public init(from decoder: Decoder) throws {
    let container = try decoder.singleValueContainer()
    if container.decodeNil() { self = .null }
    else if let value = try? container.decode(Bool.self) { self = .bool(value) }
    else if let value = try? container.decode(Double.self) { self = .number(value) }
    else if let value = try? container.decode(String.self) { self = .string(value) }
    else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
    else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
    else {
      throw DecodingError.dataCorruptedError(
        in: container, debugDescription: "Expected a JSON-compatible value.")
    }
  }

  public func encode(to encoder: Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .object(let value): try container.encode(value)
    case .array(let value): try container.encode(value)
    case .string(let value): try container.encode(value)
    case .number(let value): try container.encode(value)
    case .bool(let value): try container.encode(value)
    case .null: try container.encodeNil()
    }
  }

  public var objectValue: [String: JSONValue]? {
    guard case .object(let value) = self else { return nil }
    return value
  }

  public var stringValue: String? {
    guard case .string(let value) = self else { return nil }
    return value
  }

  public var intValue: Int? {
    guard case .number(let value) = self, value.isFinite,
      value.rounded(.towardZero) == value
    else { return nil }
    return Int(exactly: value)
  }

  public var boolValue: Bool? {
    guard case .bool(let value) = self else { return nil }
    return value
  }
}

public struct DeviceToolCapability: Codable, Hashable, Sendable {
  public var id: String
  public var operations: [String]

  public init(id: String, operations: [String]) {
    self.id = id
    self.operations = operations
  }
}

public struct DeviceBotGrant: Codable, Hashable, Sendable {
  public var botId: String
  public var toolIds: [String]

  public init(botId: String, toolIds: [String]) {
    self.botId = botId
    self.toolIds = toolIds
  }
}

public struct DeviceCapabilityRegistration: Codable, Sendable {
  public var schemaVersion = 1
  public var platform: String
  public var appVersion: String
  public var tools: [DeviceToolCapability]
  public var botGrants: [DeviceBotGrant]

  public init(
    platform: String, appVersion: String, tools: [DeviceToolCapability],
    botGrants: [DeviceBotGrant]
  ) {
    self.platform = platform
    self.appVersion = appVersion
    self.tools = tools
    self.botGrants = botGrants
  }
}

public struct DeviceCapabilityReceipt: Codable, Sendable {
  public var registered: Bool
  public var deviceId: String
  public var leaseExpiresAt: Int
}

public struct DeviceCall: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var turnId: String
  public var botId: String
  public var botName: String
  public var toolId: String
  public var operation: String
  public var arguments: [String: JSONValue]
  public var requestDigest: String
  public var expiresAt: String
}

public struct DeviceCallPage: Codable, Sendable {
  public var calls: [DeviceCall]
}

public struct DeviceCallReceipt: Codable, Sendable {
  public var accepted: Bool
  public var turnId: String
}

public enum DeviceCallOutcome: Hashable, Sendable {
  case success(JSONValue)
  case failure(String)
}
