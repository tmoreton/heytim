import Foundation
import Observation
import XCTest
@testable import HeyTimApple

@MainActor final class ForegroundConversationSyncTests: XCTestCase {
  private let chief = ConversationSelection(kind: .bot, id: "chief")
  private var models: [AppModel] = []
  private var loops: [Task<Void, Never>] = []
  private var refreshes: [Task<Bool, Error>] = []
  private var gates: [ForegroundResponseGate] = []
  private var fixtures: [(String, URLSession)] = []
  private var observations: [ForegroundMessageObservation] = []

  override func tearDown() async throws {
    loops.forEach { $0.cancel() }
    refreshes.forEach { $0.cancel() }
    gates.forEach { $0.release() }
    models.forEach { $0.resetSession() }
    for task in loops { await task.value }
    for task in refreshes { _ = await task.result }
    observations.forEach { $0.stop() }
    for (host, session) in fixtures {
      session.invalidateAndCancel()
      ForegroundFixtureURLProtocol.remove(host: host)
    }
    try await super.tearDown()
  }

  func testForegroundLoopDiscoversExternalReplyAfterAnUnchangedIdleResponse() async throws {
    let unchanged = expectation(description: "Foreground idle response delivered")
    let (server, api) = try fixture(onFinish: { number in
      if number == 2 { unchanged.fulfill() }
    })
    let model = makeModel(api)
    try await model.loadMessages()
    model.composerText = "Keep this unsent follow-up"
    let attachment = Attachment(id: "draft-file", name: "draft.txt", size: 12,
      kind: "file", format: "txt", contentType: "text/plain")
    model.pendingAttachments = [attachment]
    model.sheet = .account
    let focusRevision = model.notificationFocusRevision
    let task = synchronize(model)
    await fulfillment(of: [unchanged], timeout: 2)
    XCTAssertEqual(model.messages.map(\.id), ["original"])
    XCTAssertFalse(model.messages.contains(where: \.isActive))

    // The external event arrives after synchronization has already seen an idle page.
    try server.setPage([message("original"), message("ring-user", role: "user"),
      message("ring-reply", text: "Answer from the ring request")], cursor: "new-page-cursor")
    await waitForMessage("ring-reply", in: model, timeout: 8)
    task.cancel()
    await task.value

    XCTAssertEqual(model.messages.map(\.id), ["original", "ring-user", "ring-reply"])
    XCTAssertEqual(Set(model.messages.map(\.id)).count, model.messages.count)
    XCTAssertEqual(model.selection, chief)
    XCTAssertEqual(model.loadedMessagesSelection, chief)
    XCTAssertEqual(model.composerText, "Keep this unsent follow-up")
    XCTAssertEqual(model.pendingAttachments, [attachment])
    XCTAssertEqual(model.sheet, .account)
    XCTAssertEqual(model.notificationFocusRevision, focusRevision)
    XCTAssertEqual(model.nextToken, "older-cursor")
    XCTAssertTrue(server.requests.allSatisfy { $0.httpMethod == "GET" })
    XCTAssertGreaterThanOrEqual(server.count(method: "GET", path: "/bots/chief/messages"), 3)
  }

  func testDelayedPassivePageCannotOverwriteNewlyLoadedHistoryAndCursor() async throws {
    let started = expectation(description: "Passive page held")
    let gate = makeGate()
    let (server, api) = try fixture(onRequest: { _, number in
      if number == 2 { started.fulfill(); gate.wait() }
    })
    let model = makeModel(api)
    try await model.loadMessages()
    try server.setPage([message("original"), message("stale-passive")], cursor: "wrong-cursor")
    try server.setPage([message("older")], cursor: "oldest-cursor",
      route: "GET /bots/chief/messages?cursor=older-cursor")
    let passive = refresh(model)
    await fulfillment(of: [started], timeout: 2)
    await model.loadEarlier()
    XCTAssertEqual(model.messages.map(\.id), ["older", "original"])
    XCTAssertEqual(model.nextToken, "oldest-cursor")

    gate.release()
    let changed = try await passive.value
    XCTAssertFalse(changed)
    XCTAssertEqual(model.messages.map(\.id), ["older", "original"])
    XCTAssertEqual(model.nextToken, "oldest-cursor")
    XCTAssertNil(model.messagesLoadError)
  }

  func testOldSessionResponseCannotPublishOrReleaseReplacementRefreshOwner() async throws {
    let oldStarted = expectation(description: "Old account passive response held")
    let newStarted = expectation(description: "Replacement account response held")
    let oldGate = makeGate()
    let newGate = makeGate()
    let (oldServer, oldAPI) = try fixture(onRequest: { _, number in
      if number == 2 { oldStarted.fulfill(); oldGate.wait() }
    })
    let model = makeModel(oldAPI)
    try await model.loadMessages()
    try oldServer.setPage([message("old-account-private")])
    let oldRefresh = refresh(model)
    await fulfillment(of: [oldStarted], timeout: 2)
    let (newServer, newAPI) = try fixture(onRequest: { _, number in
      if number == 1 { newStarted.fulfill(); newGate.wait() }
    })
    try newServer.setPage([message("replacement-account")])
    model.resetSession()
    model.connect(newAPI)
    model.bootstrap = DemoData.bootstrap
    model.selection = chief
    model.composerText = "Replacement account draft"
    let newRefresh = refresh(model)
    await fulfillment(of: [newStarted], timeout: 2)

    oldGate.release()
    let oldChanged = try await oldRefresh.value
    XCTAssertFalse(oldChanged)
    let overlapping = try await model.refreshForegroundConversation()
    XCTAssertFalse(overlapping)
    XCTAssertEqual(newServer.requests.count, 1)
    newGate.release()
    let newChanged = try await newRefresh.value
    XCTAssertTrue(newChanged)
    XCTAssertEqual(model.messages.map(\.id), ["replacement-account"])
    XCTAssertEqual(model.loadedMessagesSelection, chief)
    XCTAssertEqual(model.composerText, "Replacement account draft")
  }

  func testPassiveSnapshotRejectsSendAndUploadStateABA() async throws {
    for uploading in [false, true] {
      let started = expectation(description: uploading ? "Upload race page held" : "Send race page held")
      let gate = makeGate()
      let (server, api) = try fixture(onRequest: { _, number in
        if number == 2 { started.fulfill(); gate.wait() }
      })
      let model = makeModel(api)
      try await model.loadMessages()
      try server.setPage([message("original"), message("stale-after-activity")])
      let passive = refresh(model)
      await fulfillment(of: [started], timeout: 2)
      if uploading {
        XCTAssertEqual(model.reserveAttachmentSlots(1, for: chief), 1)
        model.releaseAttachmentSlots(1)
      } else {
        model.isSending = true
        model.isSending = false
      }
      XCTAssertFalse(model.isSending)
      XCTAssertFalse(model.isUploading)
      gate.release()
      let changed = try await passive.value
      XCTAssertFalse(changed, "A completed local state transition must invalidate the old snapshot")
      XCTAssertEqual(model.messages.map(\.id), ["original"])
      XCTAssertEqual(model.nextToken, "older-cursor")
    }
  }

  func testForegroundCancellationRejectsInFlightPageAndReactivationFetchesImmediately() async throws {
    let started = expectation(description: "Foreground response held before cancellation")
    let gate = makeGate()
    let (server, api) = try fixture(onRequest: { _, number in
      if number == 2 { started.fulfill(); gate.wait() }
    })
    let model = makeModel(api)
    try await model.loadMessages()
    try server.setPage([message("original"), message("cancelled-page")])
    let first = synchronize(model)
    await fulfillment(of: [started], timeout: 2)
    first.cancel()
    gate.release()
    await first.value
    XCTAssertEqual(model.messages.map(\.id), ["original"])
    XCTAssertNil(model.messagesLoadError)
    XCTAssertNil(model.errorMessage)

    try server.setPage([message("original"), message("arrived-while-inactive")])
    let resumed = synchronize(model)
    await waitForMessage("arrived-while-inactive", in: model, timeout: 2)
    resumed.cancel()
    await resumed.value
    XCTAssertFalse(model.messages.contains { $0.id == "cancelled-page" })
    XCTAssertEqual(server.count(method: "GET", path: "/bots/chief/messages"), 3)
  }

  func testPassiveNetworkFailureIsSilentAndDoesNotPreventTheNextRefresh() async throws {
    let (server, api) = try fixture()
    let model = makeModel(api)
    try await model.loadMessages()
    model.errorMessage = "Keep an unrelated existing error"
    model.composerText = "Unsent draft"
    model.sheet = .account
    server.setResponse(Data(#"{"code":"TEMPORARY","message":"Try again"}"#.utf8), status: 503)
    do {
      _ = try await model.refreshForegroundConversation()
      XCTFail("The passive caller must receive the network failure for backoff")
    } catch let error as APIError {
      guard case .requestFailed(let status, _, _) = error else { return XCTFail("Unexpected error: \(error)") }
      XCTAssertEqual(status, 503)
    }
    XCTAssertEqual(model.messages.map(\.id), ["original"])
    XCTAssertNil(model.messagesLoadError)
    XCTAssertEqual(model.errorMessage, "Keep an unrelated existing error")
    XCTAssertFalse(model.isLoadingMessages)
    XCTAssertEqual(model.sheet, .account)
    try server.setPage([message("original"), message("recovered")])
    let recovered = try await model.refreshForegroundConversation()
    XCTAssertTrue(recovered)
    XCTAssertEqual(model.messages.last?.id, "recovered")
    XCTAssertEqual(model.composerText, "Unsent draft")
    XCTAssertEqual(model.errorMessage, "Keep an unrelated existing error")
  }

  func testAcceptedSendWithFailedFollowupCanRecoverAndPassiveCallsCoalesce() async throws {
    let started = expectation(description: "Recovery response held")
    let gate = makeGate()
    let (server, api) = try fixture(onRequest: { _, number in
      if number == 4 { started.fulfill(); gate.wait() }
    })
    let model = makeModel(api)
    try await model.loadMessages()
    server.setResponse(Data("{}".utf8), route: "POST /bots/chief/messages")
    server.setResponse(Data(#"{"code":"TEMPORARY","message":"Follow-up failed"}"#.utf8), status: 503)
    model.composerText = "Accepted once"
    await model.send()
    XCTAssertEqual(server.count(method: "POST", path: "/bots/chief/messages"), 1)
    XCTAssertNil(model.loadedMessagesSelection)
    XCTAssertFalse(model.isSending)
    XCTAssertTrue(model.composerText.isEmpty)
    try server.setPage([message("original"), message("accepted-user", role: "user"), message("accepted-answer")])
    server.setResponse(try JSONEncoder().encode(DemoData.bootstrap), route: "GET /bootstrap")
    model.composerText = "New unsent draft"
    let first = refresh(model)
    await fulfillment(of: [started], timeout: 2)
    let duplicate = try await model.refreshForegroundConversation()
    XCTAssertFalse(duplicate)
    gate.release()
    let changed = try await first.value
    XCTAssertTrue(changed)
    XCTAssertEqual(model.messages.last?.id, "accepted-answer")
    XCTAssertEqual(model.loadedMessagesSelection, chief)
    XCTAssertEqual(model.composerText, "New unsent draft")
    XCTAssertEqual(server.count(method: "GET", path: "/bots/chief/messages"), 3)
    XCTAssertEqual(server.count(method: "POST", path: "/bots/chief/messages"), 1)
  }

  func testSessionReplacementDuringConfigurationBootstrapCannotSendTheNewAccountsQueue() async throws {
    let bootstrapStarted = expectation(description: "Old configuration bootstrap held")
    let gate = makeGate()
    let (oldServer, oldAPI) = try fixture(onRequest: { request, _ in
      if request.url?.path == "/bootstrap" { bootstrapStarted.fulfill(); gate.wait() }
    })
    let model = makeModel(oldAPI)
    try await model.loadMessages()
    var configured = message("old-configuration")
    configured.configurationChanged = true
    try oldServer.setPage([message("original"), configured])
    oldServer.setResponse(try JSONEncoder().encode(DemoData.bootstrap), route: "GET /bootstrap")
    let oldRefresh = refresh(model)
    await fulfillment(of: [bootstrapStarted], timeout: 2)

    let (newServer, newAPI) = try fixture()
    try newServer.setPage([message("new-account-history")])
    newServer.setResponse(Data("{}".utf8), route: "POST /bots/chief/messages")
    newServer.setResponse(try JSONEncoder().encode(DemoData.bootstrap), route: "GET /bootstrap")
    model.resetSession()
    model.connect(newAPI)
    model.bootstrap = DemoData.bootstrap
    model.selection = chief
    try await model.loadMessages(drainQueuedMessages: false)
    model.isSending = true
    model.composerText = "Replacement account queued follow-up"
    await model.send()
    model.isSending = false
    let queuedIDs = model.messageQueues[chief]?.map(\.id)
    XCTAssertEqual(queuedIDs?.count, 1)
    model.composerText = "Replacement account unsent draft"
    gate.release()
    let changed = try await oldRefresh.value

    XCTAssertFalse(changed)
    XCTAssertEqual(newServer.count(method: "POST", path: "/bots/chief/messages"), 0)
    XCTAssertEqual(model.messageQueues[chief]?.map(\.id), queuedIDs)
    XCTAssertEqual(model.messages.map(\.id), ["new-account-history"])
    XCTAssertEqual(model.loadedMessagesSelection, chief)
    XCTAssertEqual(model.composerText, "Replacement account unsent draft")
    XCTAssertNil(model.errorMessage)
  }

  func testCancellationDuringConfigurationBootstrapCannotDrainTheSameSessionsQueue() async throws {
    let bootstrapStarted = expectation(description: "Same-session configuration bootstrap held")
    let gate = makeGate()
    let (server, api) = try fixture(onRequest: { request, _ in
      if request.url?.path == "/bootstrap" { bootstrapStarted.fulfill(); gate.wait() }
    })
    let model = makeModel(api)
    try await model.loadMessages()
    server.setResponse(Data("{}".utf8), route: "POST /bots/chief/messages")
    server.setResponse(try JSONEncoder().encode(DemoData.bootstrap), route: "GET /bootstrap")
    model.isSending = true
    model.composerText = "Keep this queued follow-up"
    await model.send()
    model.isSending = false
    let queuedIDs = model.messageQueues[chief]?.map(\.id)
    XCTAssertEqual(queuedIDs?.count, 1)
    model.composerText = "Keep this separate unsent draft"
    var configured = message("cancelled-configuration")
    configured.configurationChanged = true
    try server.setPage([message("original"), configured])
    let passive = refresh(model)
    await fulfillment(of: [bootstrapStarted], timeout: 2)

    passive.cancel()
    gate.release()
    let changed = try await passive.value

    XCTAssertFalse(changed)
    XCTAssertEqual(server.count(method: "GET", path: "/bootstrap"), 1)
    XCTAssertEqual(server.count(method: "POST", path: "/bots/chief/messages"), 0)
    XCTAssertEqual(model.messageQueues[chief]?.map(\.id), queuedIDs)
    XCTAssertEqual(model.selection, chief)
    XCTAssertEqual(model.loadedMessagesSelection, chief)
    XCTAssertEqual(model.composerText, "Keep this separate unsent draft")
    XCTAssertFalse(model.isSending)
    XCTAssertNil(model.errorMessage)
    XCTAssertNil(model.messagesLoadError)
  }

  private func makeModel(_ api: HeyTimAPI) -> AppModel {
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = chief
    models.append(model)
    return model
  }

  private func message(_ id: String, role: String = "assistant", text: String? = nil) -> ChatMessage {
    ChatMessage(id: id, role: role, source: "webhook", text: text ?? id,
      createdAt: "2026-10-15T15:00:00Z", status: "complete")
  }

  private func makeGate() -> ForegroundResponseGate {
    let gate = ForegroundResponseGate()
    gates.append(gate)
    return gate
  }

  private func refresh(_ model: AppModel) -> Task<Bool, Error> {
    let task = Task { try await model.refreshForegroundConversation() }
    refreshes.append(task)
    return task
  }

  private func synchronize(_ model: AppModel) -> Task<Void, Never> {
    let task = Task { await model.synchronizeForegroundConversation() }
    loops.append(task)
    return task
  }

  private func waitForMessage(_ id: String, in model: AppModel, timeout: TimeInterval) async {
    let found = expectation(description: "Message \(id) published through the API")
    let observation = ForegroundMessageObservation(model: model, id: id, expectation: found)
    observations.append(observation)
    observation.observe()
    await fulfillment(of: [found], timeout: timeout)
    observation.stop()
  }

  private func fixture(
    onRequest: ((URLRequest, Int) -> Void)? = nil, onFinish: ((Int) -> Void)? = nil
  ) throws -> (ForegroundTestServer, HeyTimAPI) {
    let server = ForegroundTestServer(onRequest: onRequest, onFinish: onFinish)
    try server.setPage([message("original")], cursor: "older-cursor")
    let host = "foreground-\(UUID().uuidString.lowercased()).invalid"
    ForegroundFixtureURLProtocol.install(server, host: host)
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [ForegroundFixtureURLProtocol.self]
    let session = URLSession(configuration: configuration)
    fixtures.append((host, session))
    let api = HeyTimAPI(baseURL: URL(string: "https://\(host)")!, session: session) { "fixture-token" }
    return (server, api)
  }
}

private final class ForegroundResponseGate: @unchecked Sendable {
  private let semaphore = DispatchSemaphore(value: 0)
  func wait() { semaphore.wait() }
  func release() { semaphore.signal() }
}

private final class ForegroundTestServer: @unchecked Sendable {
  struct Response { var status: Int; var data: Data }
  private let lock = NSLock()
  private var responses: [String: Response] = [:]
  private var recordedRequests: [URLRequest] = []
  private let onRequest: ((URLRequest, Int) -> Void)?
  private let onFinish: ((Int) -> Void)?

  init(onRequest: ((URLRequest, Int) -> Void)?, onFinish: ((Int) -> Void)?) {
    self.onRequest = onRequest
    self.onFinish = onFinish
  }

  var requests: [URLRequest] { lock.withLock { recordedRequests } }
  func count(method: String, path: String) -> Int {
    requests.filter { $0.httpMethod == method && $0.url?.path == path }.count
  }
  func setPage(_ messages: [ChatMessage], cursor: String? = nil,
    route: String = "GET /bots/chief/messages") throws {
    setResponse(try JSONEncoder().encode(MessagePage(messages: messages, nextToken: cursor)), route: route)
  }
  func setResponse(_ data: Data, status: Int = 200, route: String = "GET /bots/chief/messages") {
    lock.withLock { responses[route] = Response(status: status, data: data) }
  }
  func response(to request: URLRequest) throws -> (Response, Int) {
    let (response, number): (Response?, Int) = lock.withLock {
      recordedRequests.append(request)
      let query = request.url?.query.map { "?\($0)" } ?? ""
      let key = "\(request.httpMethod ?? "") \(request.url?.path ?? "")\(query)"
      return (responses[key], recordedRequests.count)
    }
    guard let response else { throw URLError(.unsupportedURL) }
    // Snapshot before the barrier: releasing a slow response cannot read newer server state.
    onRequest?(request, number)
    return (response, number)
  }
  func finished(_ number: Int) { onFinish?(number) }
}

private final class ForegroundFixtureRegistry: @unchecked Sendable {
  private let lock = NSLock()
  private var servers: [String: ForegroundTestServer] = [:]
  func install(_ server: ForegroundTestServer, host: String) { lock.withLock { servers[host] = server } }
  func remove(_ host: String) { _ = lock.withLock { servers.removeValue(forKey: host) } }
  func server(_ host: String) -> ForegroundTestServer? { lock.withLock { servers[host] } }
}

private final class ForegroundFixtureURLProtocol: URLProtocol, @unchecked Sendable {
  private static let registry = ForegroundFixtureRegistry()
  private let lock = NSLock()
  private var stopped = false
  static func install(_ server: ForegroundTestServer, host: String) { registry.install(server, host: host) }
  static func remove(host: String) { registry.remove(host) }
  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    guard let host = request.url?.host, let server = Self.registry.server(host) else {
      client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
      return
    }
    DispatchQueue.global(qos: .userInitiated).async { [self] in
      do {
        let (response, number) = try server.response(to: request)
        guard !lock.withLock({ stopped }) else { return }
        let http = HTTPURLResponse(url: request.url!, statusCode: response.status,
          httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: response.data)
        client?.urlProtocolDidFinishLoading(self)
        server.finished(number)
      } catch {
        if !lock.withLock({ stopped }) { client?.urlProtocol(self, didFailWithError: error) }
      }
    }
  }
  override func stopLoading() { lock.withLock { stopped = true } }
}

@MainActor private final class ForegroundMessageObservation {
  private weak var model: AppModel?
  private let id: String
  private let expectation: XCTestExpectation
  private var stopped = false
  init(model: AppModel, id: String, expectation: XCTestExpectation) {
    self.model = model
    self.id = id
    self.expectation = expectation
  }
  func stop() { stopped = true }
  func observe() {
    guard !stopped, let model else { return }
    withObservationTracking {
      if model.messages.contains(where: { $0.id == id }) {
        stopped = true
        expectation.fulfill()
      }
    } onChange: { [weak self] in
      Task { @MainActor in self?.observe() }
    }
  }
}
