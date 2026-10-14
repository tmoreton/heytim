import Foundation
import XCTest
@testable import HeyTimApple

@MainActor final class WebhookTests: XCTestCase {
  override func tearDown() {
    WebhookURLProtocol.handler = nil
    super.tearDown()
  }

  func testCreateSourceUsesAuthenticatedContractAndDecodesOneTimeCredentials() async throws {
    WebhookURLProtocol.handler = { request in
      XCTAssertEqual(request.url?.path, "/webhook-sources")
      XCTAssertEqual(request.httpMethod, "POST")
      XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fixture-token")
      let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Any]
      XCTAssertEqual(body["allowedBotIds"] as? [String], ["travel"])
      XCTAssertNil(body["userId"])
      return (201, Data(Self.credential.utf8))
    }
    var draft = WebhookSourceDraft()
    draft.allowedBotIds = ["travel"]
    let created = try await api().createWebhookSource(draft)
    XCTAssertEqual(created.source.id, "source-1")
    XCTAssertEqual(created.source.kind, "pebble")
    XCTAssertEqual(created.credential, "one-time-token")
    XCTAssertEqual(created.signingSecret, "one-time-signing-secret")
  }

  func testRoutingClaimsCarryLeaseAndOnlyValidatedDecisionIsSubmitted() async throws {
    var resultSeen = false
    WebhookURLProtocol.handler = { request in
      if request.httpMethod == "GET" {
        XCTAssertEqual(request.url?.path, "/devices/mac-1/routing-requests")
        return (200, try JSONEncoder().encode(RequestPage(requests: [Self.routingRequest])))
      }
      XCTAssertEqual(request.url?.path, "/devices/mac-1/routing-requests/event-1/result")
      let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Any]
      XCTAssertEqual(body["requestDigest"] as? String, "digest-1")
      XCTAssertEqual(body["leaseToken"] as? String, "lease-1")
      XCTAssertEqual(body["botId"] as? String, "travel")
      XCTAssertEqual(body["reasoningEffort"] as? String, "high")
      resultSeen = true
      return (200, Data("{\"accepted\":true}".utf8))
    }
    let client = api()
    let claims = try await client.localRoutingRequests(deviceId: "mac-1")
    XCTAssertEqual(claims.count, 1)
    try await client.submitRoutingResult(Self.result, request: claims[0], deviceId: "mac-1")
    XCTAssertTrue(resultSeen)
  }

  func testSourceToggleDoesNotResubmitStaleConfiguration() async throws {
    let source = try JSONDecoder().decode(WebhookCredential.self, from: Data(Self.credential.utf8)).source
    WebhookURLProtocol.handler = { request in
      XCTAssertEqual(request.httpMethod, "PUT")
      XCTAssertEqual(request.url?.path, "/webhook-sources/source-1")
      let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Bool]
      XCTAssertEqual(body, ["enabled": false])
      return (200, Data(Self.credential.utf8))
    }
    try await api().updateWebhookSource(source, enabled: false)
  }

  func testEditingSourcePreservesEndpointAndCredentialsAndEncodesNullableClears() async throws {
    var source = try JSONDecoder().decode(WebhookCredential.self, from: Data(Self.credential.utf8)).source
    source.fallbackBotId = "travel"
    source.textPath = "event.message.text"
    source.credentialVersion = 3
    for fallback in ["travel", nil] as [String?] {
      var expected = source
      expected.name = "Edited Pebble"
      expected.fallbackBotId = fallback
      expected.textPath = nil
      WebhookURLProtocol.handler = { request in
        XCTAssertEqual(request.httpMethod, "PUT")
        XCTAssertEqual(request.url?.path, "/webhook-sources/source-1")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fixture-token")
        let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Any]
        XCTAssertEqual(body["name"] as? String, expected.name)
        XCTAssertEqual(body["allowedBotIds"] as? [String], source.allowedBotIds)
        if let fallback { XCTAssertEqual(body["fallbackBotId"] as? String, fallback) }
        else { XCTAssertTrue(body["fallbackBotId"] is NSNull) }
        XCTAssertTrue(body["textPath"] is NSNull)
        for key in ["id", "url", "userId", "credential", "signingSecret", "credentialVersion", "enabled"] {
          XCTAssertNil(body[key])
        }
        return (200, try JSONEncoder().encode(["source": expected]))
      }
      var draft = WebhookSourceDraft(source: source)
      draft.name = expected.name
      draft.fallbackBotId = fallback
      draft.textPath = nil
      let updated = try await api().updateWebhookSource(source, draft: draft)
      XCTAssertEqual(updated.id, source.id)
      XCTAssertEqual(updated.url, source.url)
      XCTAssertEqual(updated.credentialVersion, source.credentialVersion)
      XCTAssertEqual(updated.fallbackBotId, fallback)
      XCTAssertNil(updated.textPath)
    }
  }

  func testFallbackEventDecodesItsMethodWithoutInventingModelConfidence() throws {
    let data = Data("""
      {"id":"event-1","sourceId":"source-1","sourceName":"Pebble","text":"Help","status":"queued","createdAt":"2026-10-14T14:00:00Z","botId":"travel","routingDecision":{"method":"local_fallback","botId":"travel","reasoningEffort":"high","localDecision":{"botId":null}}}
      """.utf8)
    let event = try JSONDecoder().decode(WebhookEvent.self, from: data)
    XCTAssertEqual(event.routingDecision?.method, "local_fallback")
    XCTAssertNil(event.routingDecision?.confidence)
  }

  func testAbstentionDoesNotSubmitAnAutomaticDestination() async throws {
    WebhookURLProtocol.handler = { request in
      let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Any]
      XCTAssertNil(body["botId"])
      return (200, Data("{}".utf8))
    }
    var result = Self.result
    result.needsReview = true
    try await api().submitRoutingResult(result, request: Self.routingRequest, deviceId: "mac-1")
  }

  func testUnknownBotWrongModelAndNonfiniteConfidenceFailBeforeNetwork() async throws {
    WebhookURLProtocol.handler = { _ in XCTFail("Invalid results must stay on the Mac"); return (500, Data()) }
    var invalid = Self.result
    invalid.botId = "not-permitted"
    XCTAssertThrowsError(try invalid.validated(for: Self.routingRequest))
    invalid = Self.result
    invalid.modelRevision = "different-checkpoint"
    XCTAssertThrowsError(try invalid.validated(for: Self.routingRequest))
    invalid = Self.result
    invalid.confidence = .nan
    XCTAssertThrowsError(try invalid.validated(for: Self.routingRequest))
    invalid = Self.result
    invalid.reasoningEffort = "medium"
    do {
      try await api().submitRoutingResult(invalid, request: Self.routingRequest, deviceId: "mac-1")
      XCTFail("Unsupported reasoning should fail")
    } catch { XCTAssertTrue(error is APIError) }
  }

  func testIncomingEventsDecodeWithoutAlreadySelectedBot() async throws {
    WebhookURLProtocol.handler = { request in
      XCTAssertEqual(request.url?.path, "/webhook-events")
      return (200, Data("""
        {"events":[{"id":"event-1","sourceId":"source-1","sourceName":"Pebble Index","text":"Help plan my weekend","status":"awaiting_routing","createdAt":"2026-10-14T14:00:00Z"}]}
        """.utf8))
    }
    let events = try await api().webhookEvents()
    XCTAssertEqual(events[0].status, "awaiting_routing")
    XCTAssertNil(events[0].botId)
  }

  func testReasoningDeferralPreservesPreferenceAndRejectsInconsistentGate() throws {
    var deferred = Self.result
    deferred.reasoningConfidence = 0.3
    deferred.reasoningDeferred = true
    deferred.suggestedReasoningEffort = "low"
    deferred.reasoningEffort = "max"
    XCTAssertNoThrow(try deferred.validated(for: Self.routingRequest))
    deferred.reasoningEffort = "low"
    XCTAssertThrowsError(try deferred.validated(for: Self.routingRequest))
    deferred = Self.result
    deferred.reasoningConfidence = 0.4
    XCTAssertThrowsError(try deferred.validated(for: Self.routingRequest))
  }

  func testPartialReasoningMetadataFailsValidationWhileLegacyAbsenceIsSupported() throws {
    for missingField in 0..<3 {
      var result = Self.result
      if missingField == 0 { result.reasoningConfidence = nil }
      if missingField == 1 { result.reasoningDeferred = nil }
      if missingField == 2 { result.suggestedReasoningEffort = nil }
      XCTAssertThrowsError(try result.validated(for: Self.routingRequest))
    }
    var legacy = Self.result
    legacy.reasoningConfidence = nil
    legacy.reasoningDeferred = nil
    legacy.suggestedReasoningEffort = nil
    XCTAssertNoThrow(try legacy.validated(for: Self.routingRequest))
  }

  func testReasoningJustBelowPointSixKeepsSavedPreferenceAndRejectsAutomaticOverride() throws {
    var result = Self.result
    result.reasoningConfidence = 0.5999
    result.reasoningDeferred = true
    result.suggestedReasoningEffort = "low"
    result.reasoningEffort = "max"
    XCTAssertNoThrow(try result.validated(for: Self.routingRequest))
    result.reasoningEffort = "low"
    XCTAssertThrowsError(try result.validated(for: Self.routingRequest))
    result.reasoningDeferred = false
    XCTAssertThrowsError(try result.validated(for: Self.routingRequest))
  }

  func testReasoningAtPointSixAllowsSuggestedEffortAndRejectsDeferral() throws {
    var result = Self.result
    result.reasoningConfidence = 0.6
    result.reasoningDeferred = false
    result.suggestedReasoningEffort = "low"
    result.reasoningEffort = "low"
    XCTAssertNoThrow(try result.validated(for: Self.routingRequest))
    result.reasoningEffort = "max"
    result.reasoningDeferred = true
    XCTAssertThrowsError(try result.validated(for: Self.routingRequest))
  }

  #if os(macOS)
  func testHelperFailureSubmitsCompleteClarifyMetadataAndCleansUpRegistration() async throws {
    let submitted = expectation(description: "Helper failure submitted for review or owner-selected fallback")
    let unregistered = expectation(description: "Fixture router cleanup finished")
    let requestPage = try JSONEncoder().encode(RequestPage(requests: [Self.routingRequest]))
    var claimed = false
    WebhookURLProtocol.handler = { request in
      if request.httpMethod == "DELETE" {
        unregistered.fulfill()
      } else if request.url?.path.hasSuffix("/routing-requests") == true {
        let body = claimed ? Data("{\"requests\":[]}".utf8) : requestPage
        claimed = true
        return (200, body)
      } else if request.url?.path.hasSuffix("/result") == true {
        let body = try JSONSerialization.jsonObject(with: Self.body(request)) as! [String: Any]
        XCTAssertNil(body["botId"])
        XCTAssertEqual(body["reasoningEffort"] as? String, "high")
        XCTAssertEqual(body["reasoningConfidence"] as? Double, 0)
        XCTAssertEqual(body["reasoningDeferred"] as? Bool, true)
        XCTAssertEqual(body["suggestedReasoningEffort"] as? String, "high")
        XCTAssertEqual(body["probabilities"] as? [String: Double], ["travel": 0, "clarify": 1])
        XCTAssertEqual(body["requestDigest"] as? String, "digest-1")
        XCTAssertEqual(body["leaseToken"] as? String, "lease-1")
        submitted.fulfill()
      }
      return (200, Data("{}".utf8))
    }
    let suite = "WebhookTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    defaults.set(true, forKey: "heytim.local-routing.enabled")
    let helper = SetupFixtureDecider()
    await helper.prepare { _ in }
    let router = LocalRoutingCoordinator(defaults: defaults, helper: helper)
    router.connect(api: api())
    await fulfillment(of: [submitted], timeout: 5)
    router.disconnect()
    await fulfillment(of: [unregistered], timeout: 5)
  }

  func testEnabledRouterStartsPollingAfterFirstModelSetup() async throws {
    let registered = expectation(description: "Router registered after model installation")
    let unregistered = expectation(description: "Fixture router cleanup finished")
    WebhookURLProtocol.handler = { request in
      if request.httpMethod == "PUT" && request.url?.path.hasSuffix("/routing") == true { registered.fulfill() }
      if request.httpMethod == "DELETE" { unregistered.fulfill() }
      return (200, Data((request.url?.path.hasSuffix("/routing-requests") == true ? "{\"requests\":[]}" : "{}").utf8))
    }
    let suite = "WebhookTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    defaults.set(true, forKey: "heytim.local-routing.enabled")
    let router = LocalRoutingCoordinator(defaults: defaults, helper: SetupFixtureDecider())
    router.connect(api: api())
    await router.checkModel()
    router.prepareModel()
    await fulfillment(of: [registered], timeout: 5)
    XCTAssertTrue(router.modelInstalled)
    XCTAssertFalse(router.isPreparing)
    router.disconnect()
    await fulfillment(of: [unregistered], timeout: 5)
  }

  func testBundledDeciderUsesRealModelThroughSwiftTransport() async throws {
    let helper = LocalDeciderProcess()
    do {
      let health = try await helper.health()
      guard health.modelInstalled == true else {
        throw XCTSkip("Install the pinned routing model to run real Swift transport inference.")
      }
      XCTAssertEqual(health.modelRevision, LocalDeciderIdentity.revision)
      var request = Self.routingRequest
      request.text = "Plan a three-day vacation itinerary in Boston with a toddler, stroller-friendly routes and museums."
      let result = try await helper.decide(request)
      XCTAssertEqual(result.botId, "travel")
      XCTAssertEqual(result.reasoningEffort, "high")
      await helper.stop()
    } catch {
      await helper.stop()
      throw error
    }
  }
  #endif

  private func api() -> HeyTimAPI {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [WebhookURLProtocol.self]
    return HeyTimAPI(baseURL: URL(string: "https://example.invalid")!, session: URLSession(configuration: configuration)) {
      "fixture-token"
    }
  }

  nonisolated private static func body(_ request: URLRequest) throws -> Data {
    if let body = request.httpBody { return body }
    guard let stream = request.httpBodyStream else { return Data() }
    stream.open()
    defer { stream.close() }
    var result = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
      let count = stream.read(&buffer, maxLength: buffer.count)
      if count <= 0 { break }
      result.append(buffer, count: count)
    }
    return result
  }

  nonisolated private static var routingRequest: LocalRoutingRequest {
    LocalRoutingRequest(
      id: "event-1", text: "Compare travel options for next weekend.",
      bots: [RoutingBot(id: "travel", name: "Travel", description: "Plans trips.", toolIds: [], skillIds: [], reasoningEffort: "max")],
      requestDigest: "digest-1", leaseToken: "lease-1", expiresAt: "2099-01-01T00:00:00Z",
      modelId: LocalDeciderIdentity.modelID, modelRevision: LocalDeciderIdentity.revision)
  }
  nonisolated private static var result: LocalDeciderResult {
    LocalDeciderResult(
      modelId: LocalDeciderIdentity.modelID, modelRevision: LocalDeciderIdentity.revision,
      botId: "travel", reasoningEffort: "high", confidence: 0.96,
      probabilities: ["travel": 0.98, "clarify": 0.02],
      reasoningConfidence: 0.95, reasoningDeferred: false, suggestedReasoningEffort: "high")
  }
  private struct RequestPage: Encodable { var requests: [LocalRoutingRequest] }
  nonisolated private static let credential = """
    {"source":{"id":"source-1","name":"Pebble Index","kind":"pebble","url":"https://example.invalid/public/webhooks/incoming/source-1","allowedBotIds":["travel"],"routingMode":"local","enabled":true,"createdAt":"2026-10-14T14:00:00Z"},"credential":"one-time-token","signingSecret":"one-time-signing-secret"}
    """
}

#if os(macOS)
private actor SetupFixtureDecider: LocalDeciderServing {
  private var installed = false
  func health() -> LocalDeciderHealth {
    LocalDeciderHealth(modelId: LocalDeciderIdentity.modelID, modelRevision: LocalDeciderIdentity.revision,
                       ready: installed, modelInstalled: installed, device: "fixture")
  }
  func prepare(progress: @escaping @Sendable (String) -> Void) { installed = true }
  func stop() {}
  func decide(_ request: LocalRoutingRequest) throws -> LocalDeciderResult { throw URLError(.unsupportedURL) }
}
#endif

private final class WebhookURLProtocol: URLProtocol, @unchecked Sendable {
  nonisolated(unsafe) static var handler: ((URLRequest) throws -> (Int, Data))?
  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    do {
      guard let handler = Self.handler else { throw URLError(.badServerResponse) }
      let (status, data) = try handler(request)
      let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
      client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
      client?.urlProtocol(self, didLoad: data)
      client?.urlProtocolDidFinishLoading(self)
    } catch { client?.urlProtocol(self, didFailWithError: error) }
  }
  override func stopLoading() {}
}
