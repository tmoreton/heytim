import Foundation

public enum LocalDeciderIdentity {
  public static let modelID = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
  public static let revision = "216d1ccb46a9e9b036eb9187b248db98480f77d4"
}

public struct WebhookSource: Codable, Identifiable, Sendable {
  public var id: String
  public var name: String
  public var kind: String
  public var url: String
  public var allowedBotIds: [String]
  public var fallbackBotId: String?
  public var routingMode: String
  public var enabled: Bool
  public var createdAt: String
  public var updatedAt: String?
  public var credentialVersion: Int?
  public var textPath: String?
}

public struct WebhookSourceDraft: Codable, Sendable {
  public var name = "Pebble Index"
  public var kind = "pebble"
  public var allowedBotIds: [String] = []
  public var fallbackBotId: String?
  public var routingMode = "local"
  public var enabled = true
  public var textPath: String?
  public init() {}
  public init(source: WebhookSource) {
    name = source.name
    kind = source.kind
    allowedBotIds = source.allowedBotIds
    fallbackBotId = source.fallbackBotId
    routingMode = source.routingMode
    enabled = source.enabled
    textPath = source.textPath
  }
}

public struct WebhookCredential: Codable, Sendable {
  public var source: WebhookSource
  public var credential: String
  public var signingSecret: String
}

public struct WebhookRoutingDecision: Codable, Sendable {
  public var botId: String?
  public var reasoningEffort: String?
  public var confidence: Double?
  public var modelId: String?
  public var modelRevision: String?
}

public struct WebhookEvent: Codable, Identifiable, Sendable {
  public var id: String
  public var sourceId: String
  public var sourceName: String
  public var text: String
  public var status: String
  public var createdAt: String
  public var botId: String?
  public var turnId: String?
  public var routingDecision: WebhookRoutingDecision?
  public var reviewReason: String?
}

public struct RoutingBot: Codable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var toolIds: [String]
  public var skillIds: [String]
  public var reasoningEffort: String?
}

public struct LocalRoutingRequest: Codable, Identifiable, Sendable {
  public var id: String
  public var text: String
  public var bots: [RoutingBot]
  public var requestDigest: String
  public var leaseToken: String
  public var expiresAt: String
  public var modelId: String
  public var modelRevision: String
}

public struct LocalDeciderResult: Codable, Sendable {
  public var modelId: String
  public var modelRevision: String
  public var botId: String?
  public var reasoningEffort: String
  public var confidence: Double
  public var probabilities: [String: Double]
  public var reasoningConfidence: Double?
  public var reasoningDeferred: Bool?
  public var suggestedReasoningEffort: String?
  public var needsReview: Bool?
  public var reason: String?

  public func validated(for request: LocalRoutingRequest) throws -> LocalDeciderResult {
    let candidateIDs = Set(request.bots.map(\.id) + ["clarify"])
    let maximum = probabilities.values.max() ?? 0
    let count = Double(candidateIDs.count)
    let concentration = (count * maximum - 1) / max(1, count - 1)
    guard modelId == request.modelId, modelRevision == request.modelRevision,
      ["low", "high", "max"].contains(reasoningEffort),
      confidence.isFinite, (0...1).contains(confidence),
      reasoningConfidence.map({ $0.isFinite && (0...1).contains($0) }) ?? true,
      suggestedReasoningEffort.map({ ["low", "high", "max"].contains($0) }) ?? true,
      probabilities.values.allSatisfy({ $0.isFinite && (0...1).contains($0) }),
      Set(probabilities.keys) == candidateIDs,
      abs(probabilities.values.reduce(0, +) - 1) <= 0.0001 * count,
      abs(confidence - concentration) <= 0.0003,
      botId == nil || probabilities[botId!] == maximum,
      botId == nil || request.bots.contains(where: { $0.id == botId })
    else { throw APIError.configuration("The local router returned an invalid decision.") }
    if let botId, reasoningDeferred == true {
      let preferred = request.bots.first(where: { $0.id == botId })?.reasoningEffort ?? "high"
      guard reasoningEffort == preferred else {
        throw APIError.configuration("An uncertain reasoning choice must keep the bot’s saved preference.")
      }
    }
    if botId != nil, let reasoningConfidence, let reasoningDeferred {
      guard reasoningDeferred == (reasoningConfidence < 0.5) else {
        throw APIError.configuration("The local router returned inconsistent reasoning confidence.")
      }
    }
    return self
  }
}

public struct LocalDeciderHealth: Codable, Sendable {
  public var modelId: String
  public var modelRevision: String
  public var ready: Bool
  public var modelInstalled: Bool?
  public var device: String?
}
