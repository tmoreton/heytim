import Foundation

public struct ChatUsageSummary: Codable, Hashable, Sendable {
  public var modelIds: [String]
  public var callCount: Int
  public var inputTokens: Int
  public var outputTokens: Int
  public var cacheReadInputTokens: Int
  public var cacheReportAvailable: Bool
  public var costUsd: String
  public var costBasis: String
  public var costIncomplete: Bool
  public var reasoningEffort: String?
}
