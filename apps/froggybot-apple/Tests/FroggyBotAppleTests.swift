import XCTest
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

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

    bootstrap.groups = [Self.demoGroup(bots: Array(bootstrap.groups[0].bots.prefix(1)))]
    model.bootstrap = bootstrap
    model.groupReplyBotId = "missing-bot"
    XCTAssertEqual(model.activeGroupReplyBotId, "chief")
  }

  func testComposerDraftsAndAttachmentsStayWithTheirConversation() {
    let model = AppModel(demoMode: true)
    var bootstrap = DemoData.bootstrap
    bootstrap.constraints = .serviceDefaults
    bootstrap.groups = [Self.demoGroup()]
    model.bootstrap = bootstrap
    let bot = ConversationSelection(kind: .bot, id: "chief")
    let group = ConversationSelection(kind: .group, id: "group")

    model.composerText = "Chief draft"
    model.pendingAttachments = [Self.attachment("chief-file")]
    XCTAssertEqual(model.remainingAttachmentSlots, 4)

    model.select(group)
    XCTAssertEqual(model.composerText, "")
    XCTAssertTrue(model.pendingAttachments.isEmpty)
    model.composerText = "Team draft"

    model.select(bot)
    XCTAssertEqual(model.composerText, "Chief draft")
    XCTAssertEqual(model.pendingAttachments.map(\.id), ["chief-file"])
    model.select(group)
    XCTAssertEqual(model.composerText, "Team draft")
  }

  func testRemainingAttachmentSlotsNeverDropsBelowZero() {
    let model = AppModel(demoMode: true)
    var bootstrap = DemoData.bootstrap
    bootstrap.constraints = .serviceDefaults
    model.bootstrap = bootstrap
    model.pendingAttachments = (0..<7).map { Self.attachment("file-\($0)") }

    XCTAssertEqual(model.remainingAttachmentSlots, 0)
  }

  func testAttachmentReservationCoversPreparationAndBlocksSending() async throws {
    let model = AppModel(demoMode: true)
    var bootstrap = DemoData.bootstrap
    bootstrap.constraints = .serviceDefaults
    model.bootstrap = bootstrap
    let selection = try XCTUnwrap(model.selection)
    model.pendingAttachments = [Self.attachment("existing")]
    model.composerText = "Keep this draft"

    let acceptedCount = model.reserveAttachmentSlots(10, for: selection)
    XCTAssertEqual(acceptedCount, 4)
    XCTAssertTrue(model.isUploading)
    XCTAssertEqual(model.remainingAttachmentSlots, 0)
    await model.send()
    XCTAssertEqual(model.composerText, "Keep this draft")

    model.releaseAttachmentSlots(acceptedCount)
    XCTAssertFalse(model.isUploading)
    XCTAssertEqual(model.remainingAttachmentSlots, 4)
  }

  func testPhotoPreparationProducesBoundedJPEGData() throws {
    let source = try Self.imageData(width: 2_400, height: 1_200)
    let prepared = try PhotoUploadPreparer.jpegData(
      from: source, maxDimension: 1_920, maxBytes: 3_750_000)
    let imageSource = try XCTUnwrap(CGImageSourceCreateWithData(prepared as CFData, nil))
    let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(imageSource, 0, nil))

    XCTAssertEqual(CGImageSourceGetType(imageSource) as String?, UTType.jpeg.identifier)
    XCTAssertLessThanOrEqual(max(image.width, image.height), 1_920)
    XCTAssertLessThanOrEqual(prepared.count, 3_750_000)
    XCTAssertThrowsError(
      try PhotoUploadPreparer.jpegData(from: source, maxDimension: 1_920, maxBytes: 1))
  }

  func testPhotoPreparationRejectsInvalidData() {
    XCTAssertThrowsError(
      try PhotoUploadPreparer.jpegData(
        from: Data("not an image".utf8), maxDimension: 1_920, maxBytes: 3_750_000))
  }

  func testMessageMergesPreserveHistoryWithoutDuplicates() {
    let current = DemoData.messages
    let latest = [current[1]]
    XCTAssertEqual(AppModel.mergeLatest(current: current, latest: latest).map(\.id), ["m1", "m2"])
    XCTAssertEqual(
      AppModel.mergeEarlier(current: current, earlier: current).map(\.id), ["m1", "m2"])
  }

  func testEarlierSelectionGenerationCannotOverwriteCurrentMessages() async throws {
    let firstRequestStarted = expectation(description: "First Chief request started")
    let requestLock = NSLock()
    var chiefRequestCount = 0
    MockURLProtocol.handler = { request in
      requestLock.lock()
      chiefRequestCount += 1
      let requestNumber = chiefRequestCount
      requestLock.unlock()

      if requestNumber == 1 {
        firstRequestStarted.fulfill()
        Thread.sleep(forTimeInterval: 0.2)
        return Self.response(
          for: request,
          body:
            #"{"messages":[{"id":"stale","role":"assistant","text":"Stale","createdAt":"2026-09-12T12:00:00Z","status":"complete"}],"nextToken":null}"#)
      }
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"fresh","role":"assistant","text":"Fresh","createdAt":"2026-09-12T12:01:00Z","status":"complete"}],"nextToken":null}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    let chief = ConversationSelection(kind: .bot, id: "chief")
    let writer = ConversationSelection(kind: .bot, id: "writer")
    model.selection = chief

    let staleLoad = Task { try await model.loadMessages() }
    await fulfillment(of: [firstRequestStarted], timeout: 2)
    model.selection = writer
    model.selection = chief
    try await staleLoad.value
    XCTAssertTrue(model.messages.isEmpty)

    try await model.loadMessages()
    XCTAssertEqual(model.messages.map(\.id), ["fresh"])
  }

  func testDeletingPreviousConversationPreservesCurrentDraft() async throws {
    let deleteStarted = expectation(description: "Chief deletion started")
    let releaseDelete = DispatchSemaphore(value: 0)
    var writer = try XCTUnwrap(DemoData.bootstrap.bots.first)
    writer.id = "writer"
    writer.name = "Writer"
    var refreshedBootstrap = DemoData.bootstrap
    refreshedBootstrap.bots = [writer]
    let refreshedBootstrapData = try JSONEncoder().encode(refreshedBootstrap)

    MockURLProtocol.handler = { request in
      if request.httpMethod == "DELETE" {
        deleteStarted.fulfill()
        releaseDelete.wait()
        return Self.response(for: request, body: #"{}"#)
      }
      if request.url?.path == "/bootstrap" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          refreshedBootstrapData
        )
      }
      return Self.response(
        for: request, body: #"{"messages":[],"nextToken":null}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    var initialBootstrap = DemoData.bootstrap
    initialBootstrap.bots.append(writer)
    model.bootstrap = initialBootstrap
    let chief = ConversationSelection(kind: .bot, id: "chief")
    let writerSelection = ConversationSelection(kind: .bot, id: "writer")
    model.selection = chief
    model.composerText = "Chief draft"

    let deletion = Task { await model.deleteCurrent() }
    await fulfillment(of: [deleteStarted], timeout: 2)
    model.select(writerSelection)
    model.composerText = "Writer draft"
    releaseDelete.signal()
    await deletion.value

    XCTAssertEqual(model.selection, writerSelection)
    XCTAssertEqual(model.composerText, "Writer draft")
  }

  func testClearingPreviousConversationPreservesCurrentMessagesAndCursor() async throws {
    let clearStarted = expectation(description: "Chief clear started")
    let releaseClear = DispatchSemaphore(value: 0)
    MockURLProtocol.handler = { request in
      clearStarted.fulfill()
      releaseClear.wait()
      return Self.response(for: request, body: #"{}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    var writer = try XCTUnwrap(DemoData.bootstrap.bots.first)
    writer.id = "writer"
    writer.name = "Writer"
    var bootstrap = DemoData.bootstrap
    bootstrap.bots.append(writer)
    model.bootstrap = bootstrap
    let chief = ConversationSelection(kind: .bot, id: "chief")
    let writerSelection = ConversationSelection(kind: .bot, id: "writer")
    model.selection = chief

    let clearing = Task { await model.clearCurrent(forgetMemory: false) }
    await fulfillment(of: [clearStarted], timeout: 2)
    model.selection = writerSelection
    var writerMessage = try XCTUnwrap(DemoData.messages.last)
    writerMessage.id = "writer-message"
    writerMessage.text = "Writer response"
    model.messages = [writerMessage]
    model.nextToken = "writer-cursor"
    releaseClear.signal()
    await clearing.value

    XCTAssertEqual(model.selection, writerSelection)
    XCTAssertEqual(model.messages.map(\.id), ["writer-message"])
    XCTAssertEqual(model.nextToken, "writer-cursor")
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

  func testSuccessfulSendIsNotRestoredWhenOnlyRefreshFails() async throws {
    var methods: [String] = []
    MockURLProtocol.handler = { request in
      methods.append(request.httpMethod ?? "")
      if request.httpMethod == "POST" {
        return Self.response(for: request, body: #"{}"#)
      }
      return Self.response(
        for: request, status: 503,
        body: #"{"code":"temporarily_unavailable","message":"Refresh failed"}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.composerText = "Send this once"

    await model.send()

    XCTAssertEqual(methods, ["POST", "GET"])
    XCTAssertEqual(model.composerText, "")
    XCTAssertTrue(model.pendingAttachments.isEmpty)
    XCTAssertEqual(model.errorMessage, "Refresh failed")
  }

  func testDownloadedDocumentIsPreparedForQuickLook() async throws {
    var requestedURLs: [URL] = []
    MockURLProtocol.handler = { request in
      requestedURLs.append(try XCTUnwrap(request.url))
      if request.url?.host == "files.example.com" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "text/plain"])!,
          Data("A native document preview".utf8)
        )
      }
      return Self.response(
        for: request, body: #"{"url":"https://files.example.com/signed/document"}"#)
    }
    let api = FrogBotAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let file = try await api.downloadFile(
      fileId: "file one", name: "Meeting Notes.txt", groupId: "team/one")
    let previewFolder = file.deletingLastPathComponent()

    XCTAssertEqual(file.lastPathComponent, "Meeting Notes.txt")
    XCTAssertEqual(try Data(contentsOf: file), Data("A native document preview".utf8))
    XCTAssertEqual(
      requestedURLs.first?.absoluteString,
      "https://api.example.com/groups/team%2Fone/files/file%20one/download")
    XCTAssertEqual(requestedURLs.last?.absoluteString, "https://files.example.com/signed/document")
    FrogBotAPI.removeDownloadedPreview(at: file)
    XCTAssertFalse(FileManager.default.fileExists(atPath: previewFolder.path))
  }

  private static func demoGroup(bots: [GroupBot]? = nil) -> BotGroup {
    BotGroup(
      id: "group", name: "Team", memory: "", memoryUpdatedAt: nil,
      memoryUpdatedByName: nil, ownerId: "owner", currentUserId: "owner", isOwner: true,
      allowedActions: nil, members: [],
      bots: bots ?? [
        GroupBot(
          id: "chief", ownerId: "owner", name: "Chief", tagline: "", color: "#59B86B",
          systemRole: "chief"),
        GroupBot(
          id: "writer", ownerId: "owner", name: "Writer", tagline: "", color: "#336699",
          systemRole: nil),
      ], decisions: [], createdAt: "now", updatedAt: "now", lastMessage: "",
      lastMessageAt: "now", processing: nil, processingBotName: nil)
  }

  private static func attachment(_ id: String) -> Attachment {
    Attachment(
      id: id, name: "\(id).txt", size: 10, kind: "document", format: "txt",
      contentType: "text/plain", createdAt: nil)
  }

  private static func imageData(width: Int, height: Int) throws -> Data {
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let context = try XCTUnwrap(
      CGContext(
        data: nil, width: width, height: height, bitsPerComponent: 8,
        bytesPerRow: width * 4, space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
    context.setFillColor(red: 0.1, green: 0.7, blue: 0.35, alpha: 1)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let image = try XCTUnwrap(context.makeImage())
    let output = NSMutableData()
    let destination = try XCTUnwrap(
      CGImageDestinationCreateWithData(
        output, UTType.png.identifier as CFString, 1, nil))
    CGImageDestinationAddImage(destination, image, nil)
    XCTAssertTrue(CGImageDestinationFinalize(destination))
    return output as Data
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
