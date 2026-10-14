import Foundation

private struct WebhookSourcesPage: Decodable, Sendable { var sources: [WebhookSource] }
private struct WebhookEventsPage: Decodable, Sendable { var events: [WebhookEvent] }
private struct RoutingRequestsPage: Decodable, Sendable { var requests: [LocalRoutingRequest] }
private struct SourcePage: Decodable, Sendable { var source: WebhookSource }

extension HeyTimAPI {
  public func webhookSources() async throws -> [WebhookSource] {
    let page: WebhookSourcesPage = try await request(.webhookSourceList)
    return page.sources
  }

  public func createWebhookSource(_ draft: WebhookSourceDraft) async throws -> WebhookCredential {
    try await request(.webhookSourceCreate, body: draft)
  }

  public func updateWebhookSource(_ source: WebhookSource, enabled: Bool) async throws {
    var draft = WebhookSourceDraft(source: source)
    draft.enabled = enabled
    let _: SourcePage = try await request(
      .webhookSourceUpdate, parameters: ["sourceId": source.id], body: draft)
  }

  public func deleteWebhookSource(_ id: String) async throws {
    let _: EmptyResponse = try await request(.webhookSourceDelete, parameters: ["sourceId": id])
  }

  public func rotateWebhookCredential(_ id: String) async throws -> WebhookCredential {
    try await request(.webhookSourceRotate, parameters: ["sourceId": id], body: EmptyResponse())
  }

  public func webhookEvents() async throws -> [WebhookEvent] {
    let page: WebhookEventsPage = try await request(.webhookEventList)
    return page.events
  }

  public func routeWebhookEvent(_ id: String, botId: String) async throws {
    let _: EmptyResponse = try await request(
      .webhookEventRoute, parameters: ["eventId": id], body: ["botId": botId])
  }

  public func registerLocalRouter(deviceId: String) async throws {
    struct Registration: Encodable, Sendable {
      var schemaVersion = 1
      var appVersion: String
      var modelId = LocalDeciderIdentity.modelID
      var modelRevision = LocalDeciderIdentity.revision
    }
    let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
    let _: EmptyResponse = try await request(
      .routingDevicePut, parameters: ["deviceId": deviceId], body: Registration(appVersion: version))
  }

  public func unregisterLocalRouter(deviceId: String) async throws {
    let _: EmptyResponse = try await request(.routingDeviceDelete, parameters: ["deviceId": deviceId])
  }

  public func localRoutingRequests(deviceId: String) async throws -> [LocalRoutingRequest] {
    let page: RoutingRequestsPage = try await request(.routingRequestList, parameters: ["deviceId": deviceId])
    return page.requests
  }

  public func submitRoutingResult(
    _ result: LocalDeciderResult, request routingRequest: LocalRoutingRequest, deviceId: String
  ) async throws {
    struct ResultBody: Encodable, Sendable {
      var requestDigest: String
      var leaseToken: String
      var botId: String?
      var reasoningEffort: String
      var confidence: Double
      var probabilities: [String: Double]
      var reasoningConfidence: Double?
      var reasoningDeferred: Bool?
      var suggestedReasoningEffort: String?
      var modelId: String
      var modelRevision: String
    }
    let validated = try result.validated(for: routingRequest)
    let body = ResultBody(
      requestDigest: routingRequest.requestDigest, leaseToken: routingRequest.leaseToken,
      botId: validated.needsReview == true ? nil : validated.botId,
      reasoningEffort: validated.reasoningEffort, confidence: validated.confidence,
      probabilities: validated.probabilities, reasoningConfidence: validated.reasoningConfidence,
      reasoningDeferred: validated.reasoningDeferred, suggestedReasoningEffort: validated.suggestedReasoningEffort,
      modelId: validated.modelId, modelRevision: validated.modelRevision)
    let _: EmptyResponse = try await request(
      .routingRequestResult, parameters: ["deviceId": deviceId, "requestId": routingRequest.id], body: body)
  }
}

extension AppModel {
  public func loadWebhookSources() async throws -> [WebhookSource] {
    guard let api, !demoMode else { return [] }
    return try await api.webhookSources()
  }
  public func loadWebhookEvents() async throws -> [WebhookEvent] {
    guard let api, !demoMode else { return [] }
    return try await api.webhookEvents()
  }
  public func createWebhookSource(_ draft: WebhookSourceDraft) async throws -> WebhookCredential {
    guard let api, !demoMode else { throw APIError.configuration("Sign in to create a webhook.") }
    return try await api.createWebhookSource(draft)
  }
  public func updateWebhookSource(_ source: WebhookSource, enabled: Bool) async throws {
    guard let api, !demoMode else { return }
    try await api.updateWebhookSource(source, enabled: enabled)
  }
  public func deleteWebhookSource(_ id: String) async throws {
    guard let api, !demoMode else { return }
    try await api.deleteWebhookSource(id)
  }
  public func rotateWebhookCredential(_ id: String) async throws -> WebhookCredential {
    guard let api, !demoMode else { throw APIError.configuration("Sign in to manage a webhook.") }
    return try await api.rotateWebhookCredential(id)
  }
  public func routeWebhookEvent(_ id: String, botId: String) async throws {
    guard let api, !demoMode else { return }
    try await api.routeWebhookEvent(id, botId: botId)
  }
}
