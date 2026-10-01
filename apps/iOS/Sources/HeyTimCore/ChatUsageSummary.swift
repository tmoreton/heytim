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

public struct BillingUsageSummary: Codable, Equatable, Sendable {
  public var periodStart: String
  public var periodEnd: String
  public var totalCostUsd: String
  public var totalTokens: Int
  public var inputTokens: Int
  public var outputTokens: Int
  public var cacheReadInputTokens: Int
  public var cacheWriteInputTokens: Int
  public var reasoningTokens: Int
  public var costEstimated: Bool
  public var costIncomplete: Bool
}
