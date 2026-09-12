import XCTest

@testable import FroggyBotApple

@MainActor final class FroggyBotAppleTests: XCTestCase {
  override func tearDown() {
    MockURLProtocol.handler = nil
    super.tearDown()
  }

  func testGeneratedContractIncludesEveryBackendRoute() throws {
    XCTAssertEqual(APIRouteID.allCases.count, 69)
    XCTAssertEqual(GeneratedAPIContract.routes.count, APIRouteID.allCases.count)
  }

  func testRouteParametersAndCursorAreSafelyEncoded() throws {
    let path = try GeneratedAPIContract.route(.botMessagesList).path(
      parameters: ["botId": "bot/with spaces"],
      queryItems: [.init(name: "cursor", value: "a+b/=")]
    )
    XCTAssertEqual(path, "/bots/bot%2Fwith%20spaces/messages?cursor=a+b/%3D")
  }

  func testPollingBackoffIsBoundedAndJittered() {
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 0), 1_500)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 1, random: 0), 2_400)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 20, random: 1), 30_000)
  }

  func testDirectMessageIDsMapBackToBackendTurnIDs() {
    XCTAssertEqual(AppModel.directTurnID("turn-123-assistant"), "turn-123")
    XCTAssertEqual(AppModel.directTurnID("group-message"), "group-message")
  }

  func testGroupReplyTargetDefaultsAndExplicitPeopleOnlySelection() {
    let model = AppModel(demoMode: true)
    var bootstrap = DemoData.bootstrap
    bootstrap.groups = [
      BotGroup(
        id: "group", name: "Team", memory: "", memoryUpdatedAt: nil,
        memoryUpdatedByName: nil, ownerId: "owner", currentUserId: "owner", isOwner: true,
        allowedActions: nil, members: [],
        bots: [
          GroupBot(
            id: "chief", ownerId: "owner", name: "Chief", tagline: "", color: "#59B86B",
            systemRole: "chief"),
          GroupBot(
            id: "writer", ownerId: "owner", name: "Writer", tagline: "", color: "#336699",
            systemRole: nil),
        ], decisions: [], createdAt: "now", updatedAt: "now", lastMessage: "",
        lastMessageAt: "now", processing: nil, processingBotName: nil)
    ]
    model.bootstrap = bootstrap
    model.selection = .init(kind: .group, id: "group")

    XCTAssertEqual(model.activeGroupReplyBotId, "all")
    model.groupReplyBotId = "writer"
    XCTAssertEqual(model.activeGroupReplyBotId, "writer")
    model.groupReplyBotId = nil
    XCTAssertNil(model.activeGroupReplyBotId)
  }

  func testMessageMergesPreserveHistoryWithoutDuplicates() {
    let current = DemoData.messages
    let latest = [current[1]]
    XCTAssertEqual(AppModel.mergeLatest(current: current, latest: latest).map(\.id), ["m1", "m2"])
    XCTAssertEqual(
      AppModel.mergeEarlier(current: current, earlier: current).map(\.id), ["m1", "m2"])
  }

  func testDemoLaunchHasAUsableConversation() {
    let model = AppModel(demoMode: true)
    let selected = model.selection
    let messages = model.messages
    XCTAssertEqual(selected, ConversationSelection(kind: .bot, id: "chief"))
    XCTAssertEqual(messages.count, 2)
  }

  func testInvitationLinksMatchWebAndNativeFormats() throws {
    XCTAssertEqual(
      InvitationParser.parse(
        try XCTUnwrap(URL(string: "https://froggybot.com/invite?kind=group&token=abc%2B123"))),
      PendingInvitation(kind: "group", token: "abc+123")
    )
    XCTAssertEqual(
      InvitationParser.parse(
        try XCTUnwrap(URL(string: "froggybot://invite?kind=skill&token=shared"))),
      PendingInvitation(kind: "skill", token: "shared")
    )
  }

  func testEmailOTPUsesCognitoChallengeResponseField() async throws {
    var requests: [[String: Any]] = []
    MockURLProtocol.handler = { request in
      requests.append(try Self.jsonBody(request))
      let operation = request.value(forHTTPHeaderField: "X-Amz-Target")
      if operation?.hasSuffix("InitiateAuth") == true {
        return Self.response(
          for: request, body: #"{"ChallengeName":"EMAIL_OTP","Session":"challenge-session"}"#)
      }
      return Self.response(
        for: request, status: 400,
        body: #"{"__type":"CodeMismatchException","message":"Expected test stop"}"#)
    }

    let auth = AuthSession(configuration: configuration, network: mockSession)
    await auth.begin(email: "friend@example.com", invitation: nil)
    await auth.confirm(code: "12345678")

    XCTAssertEqual(requests.count, 2)
    let challenge = try XCTUnwrap(requests.last?["ChallengeResponses"] as? [String: String])
    XCTAssertEqual(challenge["USERNAME"], "friend@example.com")
    XCTAssertEqual(challenge["EMAIL_OTP_CODE"], "12345678")
    XCTAssertNil(challenge["EMAIL_OTP"])
  }

  func testSignUpSessionIsForwardedForAutomaticSignIn() async throws {
    var requests: [(String, [String: Any])] = []
    MockURLProtocol.handler = { request in
      let operation =
        request.value(forHTTPHeaderField: "X-Amz-Target")?.split(separator: ".").last.map(
          String.init) ?? ""
      requests.append((operation, try Self.jsonBody(request)))
      switch operation {
      case "SignUp": return Self.response(for: request, body: #"{"Session":"signup-session"}"#)
      case "ConfirmSignUp":
        return Self.response(for: request, body: #"{"Session":"confirmed-session"}"#)
      default:
        return Self.response(
          for: request, status: 400,
          body: #"{"__type":"NotAuthorizedException","message":"Expected test stop"}"#)
      }
    }

    let auth = AuthSession(configuration: configuration, network: mockSession)
    await auth.begin(
      email: "new@example.com",
      invitation: PendingInvitation(kind: "bot", token: "invite-token")
    )
    await auth.confirm(code: "123456")

    XCTAssertEqual(requests.map(\.0), ["SignUp", "ConfirmSignUp", "InitiateAuth"])
    let confirmRequest = try XCTUnwrap(requests.first(where: { $0.0 == "ConfirmSignUp" })?.1)
    let initiateRequest = try XCTUnwrap(requests.first(where: { $0.0 == "InitiateAuth" })?.1)
    XCTAssertEqual(confirmRequest["Session"] as? String, "signup-session")
    XCTAssertEqual(initiateRequest["Session"] as? String, "confirmed-session")
    let authParameters = try XCTUnwrap(initiateRequest["AuthParameters"] as? [String: String])
    XCTAssertEqual(authParameters, ["USERNAME": "new@example.com"])
  }

  func testAPIRequestUsesBearerTokenAndDecodesMessages() async throws {
    var captured: URLRequest?
    MockURLProtocol.handler = { request in
      captured = request
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"turn-assistant","role":"assistant","text":"Ready","createdAt":"2026-09-12T12:00:00Z","status":"complete"}],"nextToken":"next"}"#
      )
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let page = try await api.messages(bot: "bot/one", cursor: "next page")

    XCTAssertEqual(page.messages.first?.text, "Ready")
    XCTAssertEqual(page.nextToken, "next")
    XCTAssertEqual(captured?.value(forHTTPHeaderField: "Authorization"), "Bearer id-token")
    XCTAssertEqual(
      captured?.url?.absoluteString,
      "https://api.example.com/bots/bot%2Fone/messages?cursor=next%20page")
  }

  func testBootstrapSupportsTheDeployedLegacyShape() async throws {
    MockURLProtocol.handler = { request in
      Self.response(
        for: request,
        body:
          #"{"bots":[],"botTemplates":[],"needsBotOnboarding":false,"groups":[],"tools":[],"retiredToolIds":[],"skills":[]}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let bootstrap = try await api.bootstrap()

    XCTAssertTrue(bootstrap.connectionProviders.isEmpty)
    XCTAssertEqual(bootstrap.constraints, .serviceDefaults)
  }

  func testAPIServerErrorPreservesStatusCodeAndMessage() async throws {
    MockURLProtocol.handler = { request in
      Self.response(
        for: request, status: 409,
        body: #"{"code":"conflict","message":"Wait for this bot to finish."}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    do {
      try await api.deleteBot("chief")
      XCTFail("Expected a typed API error")
    } catch let error as APIError {
      XCTAssertEqual(
        error,
        .requestFailed(status: 409, code: "conflict", message: "Wait for this bot to finish."))
    }
  }

  private var configuration: AppConfiguration {
    .init(
      auth: .init(userPoolId: "us-east-1_test", awsRegion: "us-east-1", userPoolClientId: "client"),
      custom: .init(apiUrl: "https://api.example.com", shareBaseUrl: "https://example.com/invite")
    )
  }

  private var mockSession: URLSession {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [MockURLProtocol.self]
    return URLSession(configuration: configuration)
  }

  private static func jsonBody(_ request: URLRequest) throws -> [String: Any] {
    let data: Data
    if let body = request.httpBody {
      data = body
    } else {
      let stream = try XCTUnwrap(request.httpBodyStream)
      stream.open()
      defer { stream.close() }
      var value = Data()
      let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4_096)
      defer { buffer.deallocate() }
      while true {
        let count = stream.read(buffer, maxLength: 4_096)
        if count < 0 { throw stream.streamError ?? APIError.invalidResponse }
        if count == 0 { break }
        value.append(buffer, count: count)
      }
      data = value
    }
    return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
  }

  private static func response(for request: URLRequest, status: Int = 200, body: String) -> (
    HTTPURLResponse, Data
  ) {
    (
      HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!,
      Data(body.utf8)
    )
  }
}

private final class MockURLProtocol: URLProtocol, @unchecked Sendable {
  nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    do {
      let (response, data) =
        try Self.handler?(request)
        ?? {
          throw APIError.invalidResponse
        }()
      client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
      client?.urlProtocol(self, didLoad: data)
      client?.urlProtocolDidFinishLoading(self)
    } catch {
      client?.urlProtocol(self, didFailWithError: error)
    }
  }
  override func stopLoading() {}
}
