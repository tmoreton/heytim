import XCTest
import CoreGraphics
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

@testable import HeyTimApple

@MainActor final class HeyTimAppleTests: XCTestCase {
  override func tearDown() {
    MockURLProtocol.handler = nil
    ConcurrentMockURLProtocol.handler = nil
    super.tearDown()
  }

  #if os(macOS)
    func testDesktopUpdateConfigurationRequiresHTTPSAndAResolvedPublicKey() {
      XCTAssertTrue(
        DesktopUpdateConfiguration(info: [
          "SUFeedURL": "https://example.com/appcast.xml",
          "SUPublicEDKey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ]).isConfigured)
      XCTAssertFalse(
        DesktopUpdateConfiguration(info: [
          "SUFeedURL": "http://example.com/appcast.xml",
          "SUPublicEDKey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ]).isConfigured)
      XCTAssertFalse(
        DesktopUpdateConfiguration(info: [
          "SUFeedURL": "https://example.com/appcast.xml",
          "SUPublicEDKey": "$(HEYTIM_SPARKLE_PUBLIC_KEY)",
        ]).isConfigured)
    }

    func testDesktopLocalPolicyBlocksHighImpactControls() {
      for label in ["Send", "Delete message", "Delete…", "Buy now", "Allow", "OK", "Save"] {
        XCTAssertTrue(DesktopControlCoordinator.isHighImpact(label: label), label)
      }
      for label in ["Open details", "Next tab", "Show calendar", "Pause"] {
        XCTAssertFalse(DesktopControlCoordinator.isHighImpact(label: label), label)
      }
    }

    func testDesktopLayaReceivesOnlyBoundedSafeVisibleCandidates() {
      let controls = [
        DesktopControlSummary(id: "next", role: "AXButton", label: "Next", blockedByPolicy: false),
        DesktopControlSummary(id: "previous", role: "AXButton", label: "Previous", blockedByPolicy: false),
        DesktopControlSummary(id: "save", role: "AXButton", label: "Save next item", blockedByPolicy: true),
      ]
      XCTAssertEqual(
        DesktopControlCoordinator.layaCandidates(for: "next month", from: controls).map(\.id),
        ["next"])
      XCTAssertTrue(DesktopControlCoordinator.layaCandidates(
        for: "save next", from: Array(repeating: controls[2], count: 5)).isEmpty)
      XCTAssertTrue(DesktopControlCoordinator.layaCandidates(
        for: "unrelated", from: controls).isEmpty)
    }

    func testDesktopAutomaticActionsRequireAnExactLowRiskMatch() {
      let calendar = DesktopApplication(id: 1, name: "Calendar", bundleIdentifier: "com.apple.iCal")
      let notes = DesktopApplication(id: 2, name: "Notes", bundleIdentifier: "com.apple.Notes")
      let next = DesktopControlSummary(id: "next", role: "AXButton", label: "Next", blockedByPolicy: false)
      let save = DesktopControlSummary(id: "save", role: "AXButton", label: "Save", blockedByPolicy: true)
      let newNote = DesktopControlSummary(id: "note", role: "AXButton", label: "New Note", blockedByPolicy: false)

      XCTAssertTrue(DesktopControlCoordinator.canAutoExecute(
        intent: "Click Next in Calendar", control: next, application: calendar, noteText: nil))
      XCTAssertFalse(DesktopControlCoordinator.canAutoExecute(
        intent: "Click next month in Calendar", control: next, application: calendar, noteText: nil))
      XCTAssertFalse(DesktopControlCoordinator.canAutoExecute(
        intent: "Click Next in Notes", control: next, application: calendar, noteText: nil))
      XCTAssertFalse(DesktopControlCoordinator.canAutoExecute(
        intent: "Click Save in Calendar", control: save, application: calendar, noteText: nil))
      XCTAssertTrue(DesktopControlCoordinator.canAutoExecute(
        intent: "Add a note saying Hello World", control: newNote,
        application: notes, noteText: "Hello World"))
      XCTAssertFalse(DesktopControlCoordinator.canAutoExecute(
        intent: "Add a note saying Hello World", control: newNote,
        application: notes, noteText: "Different text"))
    }

    func testHomeAssistantRequestsAreNotMistakenForMacUIActions() {
      XCTAssertFalse(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Turn on the living room lights"))
      XCTAssertFalse(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "What lights are currently on?"))
      XCTAssertFalse(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Press the bedroom light switch"))
      XCTAssertFalse(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "What if I press Next in Calendar?"))
      XCTAssertFalse(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Do not add a note saying Hello World"))
      XCTAssertTrue(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Click Next in Calendar on my Mac"))
      XCTAssertTrue(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Add a note to Apple Notes that says hello"))
      XCTAssertTrue(DesktopControlCoordinator.shouldOfferDesktopAction(for:
        "Add a note saying Hello World"))
      XCTAssertEqual(
        DesktopControlCoordinator.visibleControlRequest("Click Next in Calendar on my Mac")?.app,
        "Calendar")
      XCTAssertEqual(
        DesktopControlCoordinator.noteContent(from: "Add a note to Apple Notes that says hello"),
        "hello")
      XCTAssertTrue(DesktopControlCoordinator.noteCreationCandidate(
        "Add a note saying Hello World"))
      XCTAssertTrue(DesktopControlCoordinator.noteCreationCandidate(
        "Add to Apple Notes"))
      XCTAssertFalse(DesktopControlCoordinator.noteCreationCandidate(
        "Tell me about Apple Notes"))
      XCTAssertFalse(DesktopControlCoordinator.noteCreationCandidate(
        "Turn off the bedroom light"))
      XCTAssertEqual(DesktopControlCoordinator.noteContent(from: "Add a note saying Hello World"), "Hello World")
      XCTAssertNil(DesktopControlCoordinator.noteContent(from: "Add to Apple Notes"))
      XCTAssertNil(DesktopControlCoordinator.noteContent(from: "Show my Notes app"))
    }

    func testPinnedLayaShipsInsideMacApp() throws {
      let model = try XCTUnwrap(Bundle.main.resourceURL?.appendingPathComponent("laya-coreml"))
      XCTAssertTrue(FileManager.default.fileExists(atPath: model.appendingPathComponent("tokenizer.json").path))
      XCTAssertTrue(FileManager.default.fileExists(
        atPath: model.appendingPathComponent("laya_multilingual_e8_L128_options32.mlmodelc").path))
    }
  #endif

  func testGeneratedContractIncludesEveryBackendRoute() throws {
    XCTAssertEqual(Set(GeneratedAPIContract.routes.keys), Set(APIRouteID.allCases))
    XCTAssertEqual(
      try GeneratedAPIContract.route(.githubSkillsScan).pathTemplate,
      "/skills/github/scan")
    XCTAssertEqual(
      try GeneratedAPIContract.route(.githubSkillPreview).pathTemplate,
      "/skills/github/preview")
  }

  func testRouteParametersAndCursorAreSafelyEncoded() throws {
    let path = try GeneratedAPIContract.route(.botMessagesList).path(
      parameters: ["botId": "bot/with spaces"],
      queryItems: [.init(name: "cursor", value: "a+b/=")]
    )
    XCTAssertEqual(path, "/bots/bot%2Fwith%20spaces/messages?cursor=a+b/%3D")
  }

  func testBillingAPIUsesSummaryCheckoutAndPortalRoutes() async throws {
    var requests: [(String, String)] = []
    MockURLProtocol.handler = { request in
      requests.append((request.httpMethod ?? "", request.url?.path ?? ""))
      switch request.url?.path {
      case "/billing":
        return Self.response(
          for: request,
          body: #"{"plan":"free","status":"free","creditsUsed":7,"creditsRemaining":23,"creditLimit":30,"resetsAt":"2026-10-01T00:00:00Z","cancelAtPeriodEnd":false,"billingAvailable":true,"checkoutAvailable":true,"managementAvailable":false,"supportedStorefrontCountryCode":"USA","price":{"currency":"usd","unitAmount":2000,"interval":"month"},"mode":"test"}"#)
      case "/billing/checkout":
        let body = try Self.jsonBody(request)
        XCTAssertEqual(body["storefrontCountryCode"] as? String, "USA")
        XCTAssertNotNil(body["requestId"] as? String)
        return Self.response(
          for: request, body: #"{"url":"https://checkout.stripe.com/test"}"#)
      case "/billing/portal":
        return Self.response(
          for: request, body: #"{"url":"https://billing.stripe.com/test"}"#)
      default:
        throw APIError.invalidResponse
      }
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let summary = try await api.billingSummary()
    let checkout = try await api.createBillingCheckout(storefrontCountryCode: "USA")
    let portal = try await api.createBillingPortal()

    XCTAssertEqual(summary.creditsRemaining, 23)
    XCTAssertEqual(checkout.host, "checkout.stripe.com")
    XCTAssertEqual(portal.host, "billing.stripe.com")
    XCTAssertEqual(requests.map { "\($0.0) \($0.1)" }, [
      "GET /billing", "POST /billing/checkout", "POST /billing/portal",
    ])
  }

  func testPollingBackoffIsBoundedAndJittered() {
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 0), 1_500)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 1, random: 0), 2_400)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: 20, random: 1), 30_000)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: .max, random: 0), 24_000)
    XCTAssertEqual(AppModel.nextPollingDelay(base: 1_500, failures: .max, random: 1), 30_000)
  }

  func testConversationScrollUpdatesOnlyForTheLatestMessage() {
    let original = [
      ConversationMessageRevision(id: "one", fingerprint: 1),
      ConversationMessageRevision(id: "two", fingerprint: 2),
    ]

    XCTAssertEqual(
      ConversationTranscriptUpdate.classify(previous: [], current: original), .initial)
    XCTAssertEqual(
      ConversationTranscriptUpdate.classify(
        previous: original,
        current: original + [ConversationMessageRevision(id: "three", fingerprint: 3)]),
      .newLatest)
    XCTAssertEqual(
      ConversationTranscriptUpdate.classify(
        previous: original,
        current: [original[0], ConversationMessageRevision(id: "two", fingerprint: 20)]),
      .revisedLatest)
    XCTAssertEqual(
      ConversationTranscriptUpdate.classify(
        previous: original,
        current: [ConversationMessageRevision(id: "older", fingerprint: 0)] + original),
      .none)
  }

  func testAppearancePreferencesResolveSystemLightAndDarkModes() {
    XCTAssertNil(FroggyAppearancePreference.system.colorScheme)
    XCTAssertEqual(FroggyAppearancePreference.light.colorScheme, .light)
    XCTAssertEqual(FroggyAppearancePreference.dark.colorScheme, .dark)
  }

  func testConversationStyleUsesBotColorAndAStableSharedGroupAccent() throws {
    var bot = try XCTUnwrap(DemoData.bootstrap.bots.first)
    bot.color = "#336699"
    let group = Self.demoGroup()

    XCTAssertEqual(
      ConversationStyle.accentHex(bot: bot, group: nil, activeGroupBotID: nil),
      "#336699")
    XCTAssertEqual(
      ConversationStyle.accentHex(bot: nil, group: group, activeGroupBotID: "writer"),
      "#336699")
    XCTAssertEqual(
      ConversationStyle.accentHex(bot: nil, group: group, activeGroupBotID: "all"),
      ConversationStyle.sharedGroupAccentHex)
    XCTAssertEqual(
      ConversationStyle.accentHex(bot: nil, group: group, activeGroupBotID: nil),
      ConversationStyle.sharedGroupAccentHex)
  }

  func testTextSizePreferencesResolveToIncreasingDynamicTypeSizes() {
    XCTAssertEqual(
      FroggyTextSizePreference.system.resolvedSize(systemSize: .accessibility2),
      .accessibility2)
    XCTAssertEqual(FroggyTextSizePreference.standard.resolvedSize(systemSize: .small), .large)
    XCTAssertEqual(FroggyTextSizePreference.large.resolvedSize(systemSize: .small), .xLarge)
    XCTAssertEqual(FroggyTextSizePreference.extraLarge.resolvedSize(systemSize: .small), .xxLarge)
    XCTAssertEqual(FroggyTextSizePreference.standard.macScale, 1)
    XCTAssertGreaterThan(FroggyTextSizePreference.large.macScale, FroggyTextSizePreference.standard.macScale)
    XCTAssertGreaterThan(
      FroggyTextSizePreference.extraLarge.macScale, FroggyTextSizePreference.large.macScale)
  }

  func testWebAuthenticationCompletionMayArriveOffMainActor() async throws {
    let controller = WebAuthenticationController()
    let callbackURL = try XCTUnwrap(URL(string: "heytim://app?connection=gmail&status=connected"))

    await Task.detached {
      controller.finish(callbackURL: callbackURL, error: nil)
    }.value
    for _ in 0..<100 where controller.outcome == nil {
      await Task.yield()
    }

    XCTAssertEqual(controller.outcome, .callback(callbackURL))
    XCTAssertFalse(controller.isRunning)
  }

  #if os(macOS)
    func testMacTextSizePreferenceChangesRenderedSemanticText() throws {
      let standard = ImageRenderer(
        content: Text("Sidebar title")
          .froggyFont(.headline)
          .froggyTextSize(.standard, systemSize: .large)
          .fixedSize())
      let extraLarge = ImageRenderer(
        content: Text("Sidebar title")
          .froggyFont(.headline)
          .froggyTextSize(.extraLarge, systemSize: .large)
          .fixedSize())

      let standardSize = try XCTUnwrap(standard.nsImage?.size)
      let extraLargeSize = try XCTUnwrap(extraLarge.nsImage?.size)
      XCTAssertGreaterThan(extraLargeSize.width, standardSize.width)
      XCTAssertGreaterThan(extraLargeSize.height, standardSize.height)
    }
  #endif

  func testActivityStepsRenderInlineMarkdownInsteadOfLiteralMarkers() {
    let formatted = formattedActivityStep("Checking `README.md` before **release**.")

    XCTAssertEqual(String(formatted.characters), "Checking README.md before release.")
  }

  func testMessageActivityPhasesUseAccurateProgressLabels() {
    XCTAssertTrue(MessageActivityPhase(status: "running").isIndeterminate)
    XCTAssertTrue(MessageActivityPhase(status: "running").isActive)
    XCTAssertTrue(MessageActivityPhase(status: "queued").isActive)
    XCTAssertTrue(MessageActivityPhase(status: "waiting").isActive)
    XCTAssertFalse(MessageActivityPhase(status: "complete").isActive)
    XCTAssertEqual(
      MessageActivityPhase(status: "running").title(stepCount: 2), "Processing · 2 updates")
    XCTAssertEqual(MessageActivityPhase(status: "pending").title(stepCount: 0), "Processing…")
    XCTAssertTrue(MessageActivityPhase(status: "pending").isIndeterminate)
    XCTAssertEqual(
      MessageActivityPhase(status: "running").title(
        steps: ["Reviewing files.", "Planning the implementation."]),
      "Planning the implementation.")
    XCTAssertEqual(
      MessageActivityPhase(status: "waiting").title(stepCount: 0), "Waiting for its turn")
    XCTAssertEqual(
      MessageActivityPhase(status: "complete").title(stepCount: 1), "1 step completed")
    XCTAssertEqual(MessageActivityPhase(status: "error").title(stepCount: 0), "Couldn’t finish")
    XCTAssertFalse(MessageActivityPhase(status: "waiting").isIndeterminate)
  }

  func testMessageMarkdownParsesHeadingListAndTableAsBlocks() throws {
    let blocks = MarkdownBlockParser.parse(
      """
      ## I can't flip visibility

      Two separate things:

      1. **Visibility** is managed in settings.
         This remains part of the first item.
      2. Protect `main` before release.

      | Key | Value |
      | :--- | ---: |
      | SITE_EDITOR_AGENT_ARN | Protected |
      """)

    XCTAssertEqual(blocks.count, 4)
    XCTAssertEqual(blocks[0], .heading(level: 2, text: "I can't flip visibility"))
    XCTAssertEqual(blocks[1], .paragraph("Two separate things:"))

    guard case .list(let ordered, let items) = blocks[2] else {
      return XCTFail("Expected an ordered list")
    }
    XCTAssertTrue(ordered)
    XCTAssertEqual(items.map(\.number), [1, 2])
    XCTAssertEqual(
      items[0].text,
      "**Visibility** is managed in settings. This remains part of the first item.")

    guard case .table(let table) = blocks[3] else {
      return XCTFail("Expected a table")
    }
    XCTAssertEqual(table.headers, ["Key", "Value"])
    XCTAssertEqual(table.rows, [["SITE_EDITOR_AGENT_ARN", "Protected"]])
    XCTAssertEqual(table.alignments, [.leading, .trailing])
  }

  func testMessageMarkdownParsesQuoteCodeAndTaskList() {
    let blocks = MarkdownBlockParser.parse(
      """
      > Check this before release.

      - [x] Tests pass
      - [ ] Upload build

      ```swift
      let ready = true
      ```
      """)

    XCTAssertEqual(blocks[0], .quote("Check this before release."))
    guard case .list(let ordered, let items) = blocks[1] else {
      return XCTFail("Expected a task list")
    }
    XCTAssertFalse(ordered)
    XCTAssertEqual(items.map(\.checkbox), [true, false])
    XCTAssertEqual(blocks[2], .code(language: "swift", text: "let ready = true"))
  }

  func testResetSessionClearsAccountScopedStateAndDisconnects() throws {
    let api = HeyTimAPI(baseURL: try XCTUnwrap(URL(string: "https://api.example.com"))) {
      "id-token"
    }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.messages = DemoData.messages
    model.nextToken = "next"
    model.composerText = "Private draft"
    model.pendingAttachments = [Self.attachment("private-file")]
    model.sheet = .account
    model.errorMessage = "Private error"
    model.deepLinkInvite = ("group", "private-token")
    _ = model.reserveAttachmentSlots(1, for: try XCTUnwrap(model.selection))

    model.resetSession()

    XCTAssertNil(model.bootstrap)
    XCTAssertNil(model.selection)
    XCTAssertTrue(model.messages.isEmpty)
    XCTAssertNil(model.nextToken)
    XCTAssertTrue(model.composerText.isEmpty)
    XCTAssertTrue(model.pendingAttachments.isEmpty)
    XCTAssertNil(model.sheet)
    XCTAssertNil(model.errorMessage)
    XCTAssertNil(model.deepLinkInvite)
    XCTAssertFalse(model.isLoading)
    XCTAssertFalse(model.isSending)
    XCTAssertFalse(model.isUploading)
    XCTAssertThrowsError(try model.requireAPI())
  }

  func testBotEditorOnlyOffersExistingInteractiveApprovalsForRevocation() throws {
    let tools = try JSONDecoder().decode(
      [Capability].self,
      from: Data(
        #"""
        [
          {"id":"browser","name":"Browser","description":"","risk":"interactive"},
          {"id":"home","name":"Home","description":"","risk":"interactive"},
          {"id":"web","name":"Web","description":"","risk":"read"}
        ]
        """#.utf8))
    var draft = BotDraft()
    draft.toolIds = tools.map(\.id)
    draft.alwaysAllowedToolIds = ["browser", "web"]

    XCTAssertEqual(
      revocableAlwaysAllowedTools(tools: tools, skills: [], draft: draft).map(\.id),
      ["browser"])
  }

  func testMemoryUsageMakesActiveScopeAndCleanupExplicit() {
    let fact = MemoryRecord(
      id: "fact", kind: "fact", content: "Prefers tea", createdAt: "2026-09-13T12:00:00Z",
      scope: "personal", source: "learned", botId: nil, botName: nil)
    let activeSummary = MemoryRecord(
      id: "summary", kind: "summary", content: "Trip planning", createdAt: "2026-09-13T12:00:00Z",
      scope: "personal", source: "learned", botId: "travel", botName: "Travel Bot")
    var unusedSummary = activeSummary
    unusedSummary.botId = nil
    unusedSummary.botName = nil

    XCTAssertEqual(memoryUsageState(for: fact, groupID: nil), .allBots)
    XCTAssertEqual(memoryUsageState(for: activeSummary, groupID: nil), .bot("Travel Bot"))
    XCTAssertEqual(memoryUsageState(for: unusedSummary, groupID: nil), .unused)
    XCTAssertEqual(memoryUsageState(for: fact, groupID: "group"), .group)
  }

  func testBotMemoryUsesScopedRoutesInsteadOfAccountMemory() async throws {
    let record = #"{"id":"mem-bot","kind":"summary","content":"Bot-only note","createdAt":"2026-09-16T12:00:00Z","scope":"bot","source":"manual","botId":"chief","botName":"Chief"}"#
    var requests: [(String, String)] = []
    MockURLProtocol.handler = { request in
      let path = request.url?.path ?? ""
      let method = request.httpMethod ?? ""
      requests.append((method, path))
      if method == "GET" {
        return Self.response(
          for: request, body: "{\"records\":[\(record)],\"rawConversationRetentionDays\":30}")
      }
      if method == "DELETE" {
        return Self.response(for: request, body: #"{"deleted":true}"#)
      }
      return Self.response(for: request, body: record)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let snapshot = try await api.memories(botId: "chief")
    XCTAssertEqual(snapshot.records.map(\.id), ["mem-bot"])
    _ = try await api.createMemory(content: "Bot-only note", botId: "chief")
    _ = try await api.updateMemory(id: "mem-bot", content: "Updated", botId: "chief")
    try await api.deleteMemory(id: "mem-bot", botId: "chief")

    XCTAssertEqual(requests.map { "\($0.0) \($0.1)" }, [
      "GET /bots/chief/memory",
      "POST /bots/chief/memory",
      "PUT /bots/chief/memory/mem-bot",
      "DELETE /bots/chief/memory/mem-bot",
    ])
  }

  func testSharedAndGroupMemoryEditsUseRecordIDInTheirRoutes() async throws {
    let record = #"{"id":"mem-1","kind":"fact","content":"Updated","createdAt":"2026-09-16T12:00:00Z","scope":"personal","source":"manual"}"#
    var paths: [String] = []
    MockURLProtocol.handler = { request in
      paths.append(request.url?.path ?? "")
      if request.httpMethod == "DELETE" {
        return Self.response(for: request, body: #"{"deleted":true}"#)
      }
      return Self.response(for: request, body: record)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    _ = try await api.updateMemory(id: "mem-1", content: "Updated")
    try await api.deleteMemory(id: "mem-1")
    _ = try await api.updateMemory(id: "mem-1", content: "Updated", groupId: "team")
    try await api.deleteMemory(id: "mem-1", groupId: "team")

    XCTAssertEqual(paths, [
      "/memory/mem-1", "/memory/mem-1",
      "/groups/team/memory/mem-1", "/groups/team/memory/mem-1",
    ])
  }

  func testNewCustomBotStartsWithAServiceSupportedColor() {
    XCTAssertEqual(BotDraft().color, "#58BEAA")
  }

  func testBotTemplateResolvesToolsInheritedFromSkillsWithoutDuplicates() throws {
    let template = try XCTUnwrap(DemoData.botTemplates.first)

    XCTAssertEqual(
      template.effectiveToolIDs(skills: DemoData.skills),
      ["web_search", "code_interpreter"])
  }

  func testConnectionCallbackAcceptsOnlyCompletedNativeOAuthResults() throws {
    XCTAssertEqual(
      ConnectionAuthorizationCallback(
        url: try XCTUnwrap(
          URL(string: "heytim://app?connection=gmail&status=connected"))),
      ConnectionAuthorizationCallback(
        url: try XCTUnwrap(
          URL(string: "heytim://app?status=connected&connection=gmail"))))
    XCTAssertEqual(
      ConnectionAuthorizationCallback(
        url: try XCTUnwrap(URL(string: "heytim://app?connection=gmail&status=error")))?
        .status,
      .error)
    XCTAssertNil(
      ConnectionAuthorizationCallback(
        url: try XCTUnwrap(URL(string: "heytim://invite?connection=gmail&status=connected"))))
    XCTAssertNil(
      ConnectionAuthorizationCallback(
        url: try XCTUnwrap(URL(string: "heytim://app?connection=gmail"))))
  }

  func testDirectMessageIDsMapBackToBackendTurnIDs() {
    XCTAssertEqual(AppModel.directTurnID("turn-123-assistant"), "turn-123")
    XCTAssertEqual(AppModel.directTurnID("group-message"), "group-message")
  }

  func testConversationListSortsBotsAndGroupsByMostRecentActivity() {
    var olderBot = DemoData.bootstrap.bots[0]
    olderBot.id = "older-bot"
    olderBot.name = "Older Bot"
    olderBot.lastMessageAt = "2026-09-13T12:00:00.000Z"

    var newestBot = olderBot
    newestBot.id = "newest-bot"
    newestBot.name = "Newest Bot"
    newestBot.lastMessageAt = "2026-09-13T14:00:00.000Z"

    var middleGroup = Self.demoGroup()
    middleGroup.id = "middle-group"
    middleGroup.name = "Middle Group"
    middleGroup.lastMessageAt = "2026-09-13T13:00:00.000Z"

    let items = ConversationListItem.recentFirst(
      bots: [olderBot, newestBot], groups: [middleGroup])

    XCTAssertEqual(
      items.map(\.selection),
      [
        ConversationSelection(kind: .bot, id: "newest-bot"),
        ConversationSelection(kind: .group, id: "middle-group"),
        ConversationSelection(kind: .bot, id: "older-bot"),
      ])
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
    model.addWorkspaceFile(Self.attachment("saved-file"))
    XCTAssertEqual(model.remainingAttachmentSlots, 3)

    model.select(group)
    XCTAssertEqual(model.composerText, "")
    XCTAssertTrue(model.pendingAttachments.isEmpty)
    XCTAssertTrue(model.pendingWorkspaceFiles.isEmpty)
    model.composerText = "Team draft"

    model.select(bot)
    XCTAssertEqual(model.composerText, "Chief draft")
    XCTAssertEqual(model.pendingAttachments.map(\.id), ["chief-file"])
    XCTAssertEqual(model.pendingWorkspaceFiles.map(\.id), ["saved-file"])
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

  func testInitialMessageLoadRemainsLoadingUntilHistoryArrives() async throws {
    let requestStarted = expectation(description: "History request started")
    let releaseRequest = DispatchSemaphore(value: 0)
    MockURLProtocol.handler = { request in
      requestStarted.fulfill()
      releaseRequest.wait()
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"history","role":"assistant","text":"Existing reply","createdAt":"2026-09-12T12:00:00Z","status":"complete"}],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.selection = .init(kind: .bot, id: "chief")

    let load = Task { try await model.loadMessages() }
    await fulfillment(of: [requestStarted], timeout: 2)

    XCTAssertTrue(model.isLoadingMessages)
    XCTAssertTrue(model.messages.isEmpty)

    releaseRequest.signal()
    try await load.value

    XCTAssertFalse(model.isLoadingMessages)
    XCTAssertEqual(model.messages.map(\.id), ["history"])
  }

  func testCompletedHistoryRefreshesAStaleWorkingBadge() async throws {
    var staleBootstrap = DemoData.bootstrap
    staleBootstrap.bots[0].processing = true
    let refreshedBootstrap = DemoData.bootstrap
    let refreshedData = try JSONEncoder().encode(refreshedBootstrap)
    var paths: [String] = []
    MockURLProtocol.handler = { request in
      let path = request.url?.path ?? ""
      paths.append(path)
      if path == "/bootstrap" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          refreshedData
        )
      }
      XCTAssertEqual(path, "/bots/chief/messages")
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"finished","role":"assistant","text":"Done","createdAt":"2026-09-16T12:00:00Z","status":"complete"}],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = staleBootstrap
    model.selection = .init(kind: .bot, id: "chief")

    try await model.loadMessages()

    XCTAssertEqual(paths, ["/bots/chief/messages", "/bootstrap"])
    XCTAssertEqual(model.messages.last?.status, "complete")
    XCTAssertEqual(model.bootstrap?.bots.first?.processing, nil)
  }

  #if os(iOS)
    func testLaunchAndRefreshLeaveChatListUnselected() async throws {
      let bootstrapData = try JSONEncoder().encode(DemoData.bootstrap)
      MockURLProtocol.handler = { request in
        XCTAssertEqual(request.url?.path, "/bootstrap")
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          bootstrapData
        )
      }
      let api = HeyTimAPI(
        baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
      ) { "id-token" }
      let model = AppModel(api: api)

      await model.load()
      XCTAssertNotNil(model.bootstrap)
      XCTAssertNil(model.selection)
      XCTAssertTrue(model.messages.isEmpty)

      let refreshed = await model.refreshBootstrap()
      XCTAssertTrue(refreshed)
      XCTAssertNil(model.selection)
    }
  #endif

  func testBootstrapRefreshLoadsMessagesForAReplacementSelection() async throws {
    var writer = try XCTUnwrap(DemoData.bootstrap.bots.first)
    writer.id = "writer"
    writer.name = "Writer"
    var refreshedBootstrap = DemoData.bootstrap
    refreshedBootstrap.bots = [writer]
    let bootstrapData = try JSONEncoder().encode(refreshedBootstrap)

    MockURLProtocol.handler = { request in
      if request.url?.path == "/bootstrap" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          bootstrapData
        )
      }
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"writer-message","role":"assistant","text":"Writer reply","createdAt":"2026-09-12T12:01:00Z","status":"complete"}],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.messages = DemoData.messages

    await model.refreshBootstrap()

    XCTAssertEqual(model.selection, .init(kind: .bot, id: "writer"))
    XCTAssertEqual(model.messages.map(\.id), ["writer-message"])
  }

  func testSharingUsesTheRequestedSelectionAndDoesNotReuseAFailedLink() async throws {
    var paths: [String] = []
    MockURLProtocol.handler = { request in
      paths.append(request.url?.path ?? "")
      if paths.count == 1 {
        return Self.response(
          for: request, body: #"{"url":"https://example.com/group-link"}"#)
      }
      return Self.response(
        for: request, status: 503,
        body: #"{"code":"temporarily_unavailable","message":"Try again later"}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")

    let shared = await model.share(.init(kind: .group, id: "team"))
    let failed = await model.share(.init(kind: .bot, id: "chief"))

    XCTAssertEqual(shared?.absoluteString, "https://example.com/group-link")
    XCTAssertNil(failed)
    XCTAssertEqual(paths, ["/groups/team/invites", "/shares"])
    XCTAssertEqual(model.errorMessage, "Try again later")
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
    let api = HeyTimAPI(
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
    let api = HeyTimAPI(
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
    let api = HeyTimAPI(
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
        try XCTUnwrap(URL(string: "https://heytim.ai/invite?kind=group&token=abc%2B123"))),
      PendingInvitation(kind: "group", token: "abc+123")
    )
    XCTAssertEqual(
      InvitationParser.parse(
        try XCTUnwrap(URL(string: "heytim://invite?kind=skill&token=shared"))),
      PendingInvitation(kind: "skill", token: "shared")
    )
  }

  func testAuthenticationTestsUseAnIsolatedKeychainService() {
    XCTAssertTrue(AuthSession.keychainServiceForCurrentProcess.hasPrefix("ai.heytim.app.auth.tests."))
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

  func testStaleAuthenticationSessionCannotExpireAReplacementLogin() async throws {
    var issuedSessions = 0
    MockURLProtocol.handler = { request in
      let operation = request.value(forHTTPHeaderField: "X-Amz-Target") ?? ""
      guard operation.hasSuffix("InitiateAuth") else {
        return Self.response(for: request, body: #"{}"#)
      }
      issuedSessions += 1
      let suffix = issuedSessions == 1 ? "old" : "new"
      return Self.response(
        for: request,
        body:
          """
          {"AuthenticationResult":{"AccessToken":"access-\(suffix)","ExpiresIn":3600,"IdToken":"id-\(suffix)","RefreshToken":"refresh-\(suffix)"}}
          """)
    }
    let auth = AuthSession(configuration: configuration, network: mockSession)

    await auth.begin(email: "old@example.com", invitation: nil)
    let oldSession = auth.sessionIdentifier
    let loadedOldToken = try await auth.idToken(forSession: oldSession)
    let oldToken = try XCTUnwrap(loadedOldToken)
    auth.expire(ifUsing: oldToken, session: oldSession)
    XCTAssertEqual(auth.phase, .signedOut)

    await auth.begin(email: "new@example.com", invitation: nil)
    let newSession = auth.sessionIdentifier
    let loadedNewToken = try await auth.idToken(forSession: newSession)
    let newToken = try XCTUnwrap(loadedNewToken)
    XCTAssertEqual(newToken, "id-new")

    auth.expire(ifUsing: oldToken, session: oldSession)
    XCTAssertEqual(auth.phase, .signedIn)
    let retainedToken = try await auth.idToken(forSession: newSession)
    XCTAssertEqual(retainedToken, "id-new")
    do {
      _ = try await auth.idToken(forSession: oldSession)
      XCTFail("An old API client must not borrow the replacement account's token")
    } catch let error as APIError {
      XCTAssertEqual(error, .sessionExpired)
    }

    await auth.signOut()
  }

  func testDelayedSignOutCannotClearAReplacementLogin() async throws {
    let revokeStarted = expectation(description: "Old session revocation started")
    let releaseRevoke = DispatchSemaphore(value: 0)
    defer {
      releaseRevoke.signal()
      ConcurrentMockURLProtocol.handler = nil
    }
    ConcurrentMockURLProtocol.handler = { request in
      let operation = request.value(forHTTPHeaderField: "X-Amz-Target") ?? ""
      let body = try Self.jsonBody(request)
      if operation.hasSuffix("RevokeToken") {
        revokeStarted.fulfill()
        releaseRevoke.wait()
        return Self.response(for: request, body: #"{}"#)
      }
      let parameters = body["AuthParameters"] as? [String: String]
      let suffix = parameters?["USERNAME"] == "new@example.com" ? "new" : "old"
      return Self.response(
        for: request,
        body:
          """
          {"AuthenticationResult":{"AccessToken":"access-\(suffix)","ExpiresIn":3600,"IdToken":"id-\(suffix)","RefreshToken":"refresh-\(suffix)"}}
          """)
    }
    let networkConfiguration = URLSessionConfiguration.ephemeral
    networkConfiguration.protocolClasses = [ConcurrentMockURLProtocol.self]
    let auth = AuthSession(
      configuration: configuration, network: URLSession(configuration: networkConfiguration))
    await auth.begin(email: "old@example.com", invitation: nil)
    let oldSession = auth.sessionIdentifier

    let delayedSignOut = Task { await auth.signOut() }
    await fulfillment(of: [revokeStarted], timeout: 2)
    XCTAssertEqual(auth.phase, .signedOut)

    await auth.begin(email: "new@example.com", invitation: nil)
    let newSession = auth.sessionIdentifier
    let loadedNewToken = try await auth.idToken(forSession: newSession)
    let newToken = try XCTUnwrap(loadedNewToken)
    XCTAssertEqual(newToken, "id-new")

    releaseRevoke.signal()
    await delayedSignOut.value

    XCTAssertEqual(auth.phase, .signedIn)
    let retainedNewToken = try await auth.idToken(forSession: newSession)
    XCTAssertEqual(retainedNewToken, "id-new")
    do {
      _ = try await auth.idToken(forSession: oldSession)
      XCTFail("The signed-out API client must remain invalid")
    } catch let error as APIError {
      XCTAssertEqual(error, .sessionExpired)
    }
    auth.expire(ifUsing: newToken, session: newSession)
  }

  func testTerminalRefreshFailureClearsTheNativeSession() async throws {
    MockURLProtocol.handler = { request in
      let body = try Self.jsonBody(request)
      if body["AuthFlow"] as? String == "REFRESH_TOKEN_AUTH" {
        return Self.response(
          for: request, status: 400,
          body: #"{"__type":"NotAuthorizedException","message":"Refresh Token has expired"}"#)
      }
      return Self.response(
        for: request,
        body:
          #"{"AuthenticationResult":{"AccessToken":"access","ExpiresIn":0,"IdToken":"id","RefreshToken":"refresh"}}"#)
    }
    let auth = AuthSession(configuration: configuration, network: mockSession)
    await auth.begin(email: "expired@example.com", invitation: nil)
    let session = auth.sessionIdentifier

    do {
      _ = try await auth.idToken(forSession: session)
      XCTFail("Expected the expired refresh token to end the session")
    } catch let error as APIError {
      XCTAssertEqual(error, .sessionExpired)
    }

    XCTAssertEqual(auth.phase, .signedOut)
    XCTAssertEqual(auth.errorMessage, APIError.sessionExpired.localizedDescription)
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
    let api = HeyTimAPI(
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
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let bootstrap = try await api.bootstrap()

    XCTAssertTrue(bootstrap.connectionProviders.isEmpty)
    XCTAssertEqual(bootstrap.constraints, .serviceDefaults)
  }

  func testBootstrapAcceptsThePublicConnectionProviderShape() async throws {
    MockURLProtocol.handler = { request in
      Self.response(
        for: request,
        body:
          #"{"bots":[],"botTemplates":[],"connectionProviders":[{"id":"github","name":"GitHub","description":"Work with selected repositories.","category":"Developer tools","iconText":"GH","permissionsSummary":"Selected repositories only","privacyTitle":"Repository access stays scoped","privacyDescription":"Uses an installation grant.","connectLabel":"Install app","reconnectLabel":"Update installation"}],"needsBotOnboarding":false,"groups":[],"tools":[],"retiredToolIds":[],"skills":[],"constraints":{"botNameMaxLength":48,"botTaglineMaxLength":120,"botPromptMaxLength":12000,"groupNameMaxLength":64,"groupMemoryMaxLength":4000,"messageMaxLength":8000,"scheduleNameMaxLength":64,"schedulePromptMaxLength":8000,"scheduleDayOfMonthMin":1,"scheduleDayOfMonthMax":28,"skillNameMaxLength":80,"skillDescriptionMaxLength":240,"skillInstructionsMaxLength":20000,"memoryMaxLength":16000,"maxAttachmentsPerMessage":5,"imageMaxBytes":3750000,"documentMaxBytes":4500000,"maxPhotoDimension":1920}}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let bootstrap = try await api.bootstrap()

    let provider = try XCTUnwrap(bootstrap.connectionProviders.first)
    XCTAssertEqual(provider.id, "github")
    XCTAssertEqual(provider.connectLabel, "Install app")
    XCTAssertEqual(provider.reconnectLabel, "Update installation")
  }

  func testConnectionProviderPresentationIsEntirelyServerDefined() throws {
    let data = try XCTUnwrap(
      #"{"id":"future-provider","name":"Future Provider","description":"A new connection.","category":"Productivity","iconText":"FP","permissionsSummary":"Read-only","privacyTitle":"Private by default","privacyDescription":"Delegated only when needed.","connectLabel":"Connect workspace","reconnectLabel":"Update workspace","familyId":"future-family","familyName":"Future Family","familyDescription":"Related services.","familyIconText":"FF","familyLogoProviderId":"future-provider","familyIncludedSummary":"Public tools included","familyIncludedToolIds":["future-search"],"serviceName":"Private access"}"#
        .data(using: .utf8))

    let provider = try JSONDecoder().decode(ConnectionProvider.self, from: data)

    XCTAssertEqual(provider.id, "future-provider")
    XCTAssertEqual(provider.connectLabel, "Connect workspace")
    XCTAssertEqual(provider.reconnectLabel, "Update workspace")
    XCTAssertEqual(provider.familyId, "future-family")
    XCTAssertEqual(provider.familyName, "Future Family")
    XCTAssertEqual(provider.familyIncludedSummary, "Public tools included")
    XCTAssertEqual(provider.familyIncludedToolIds, ["future-search"])
    XCTAssertEqual(provider.serviceName, "Private access")
  }

  func testConnectionProviderFamiliesGroupServicesWithoutMergingProviders() throws {
    let data = try XCTUnwrap(
      #"[{"id":"gmail","name":"Gmail","description":"Email.","category":"Email","iconText":"G","permissionsSummary":"Read and draft","privacyTitle":"Private","privacyDescription":"Email access.","connectLabel":"Connect","reconnectLabel":"Reconnect","familyId":"google","familyName":"Google","familyDescription":"Choose services.","familyIconText":"G","familyLogoProviderId":"google_workspace","familyIncludedSummary":"Public YouTube research included","familyIncludedToolIds":["youtube_search"],"serviceName":"Gmail"},{"id":"youtube","name":"YouTube Studio","description":"Channel.","category":"Video","iconText":"YT","permissionsSummary":"Read channel","privacyTitle":"Private","privacyDescription":"Channel access.","connectLabel":"Connect","reconnectLabel":"Reconnect","familyId":"google","familyName":"Google","familyDescription":"Choose services.","familyIconText":"G","familyLogoProviderId":"google_workspace","familyIncludedSummary":"Public YouTube research included","familyIncludedToolIds":["youtube_search"],"serviceName":"YouTube Studio"},{"id":"google_workspace","name":"Google Workspace","description":"Drive, Docs, and Calendar.","category":"Productivity","iconText":"GW","permissionsSummary":"Read workspace","privacyTitle":"Private","privacyDescription":"Workspace access.","connectLabel":"Connect","reconnectLabel":"Reconnect","familyId":"google","familyName":"Google","familyDescription":"Choose services.","familyIconText":"G","familyLogoProviderId":"google_workspace","familyIncludedSummary":"Public YouTube research included","familyIncludedToolIds":["youtube_search"],"serviceName":"Workspace"}]"#
        .data(using: .utf8))
    let providers = try JSONDecoder().decode([ConnectionProvider].self, from: data)

    let families = connectionProviderFamilies(providers)

    XCTAssertEqual(families.map(\.id), ["google"])
    XCTAssertEqual(families[0].providers.map(\.id), ["gmail", "youtube", "google_workspace"])
    XCTAssertEqual(families[0].includedSummary, "Public YouTube research included")
    XCTAssertEqual(families[0].includedToolIDs, ["youtube_search"])

    let toolsData = try XCTUnwrap(
      #"[{"id":"youtube_search","name":"YouTube Search","description":"Search public videos.","provider":"agentcore-gateway"},{"id":"connection-youtube","name":"YouTube Studio","description":"Read a connected channel.","provider":"youtube","source":"user","editable":true,"connectionStatus":"connected"},{"id":"web_search","name":"Web Search","description":"Search the web.","provider":"agentcore-gateway"}]"#
        .data(using: .utf8))
    let tools = try JSONDecoder().decode([Capability].self, from: toolsData)

    let grouped = connectionProviderToolGroups(tools: tools, providers: providers)

    XCTAssertEqual(grouped.groups.map(\.id), ["google"])
    XCTAssertEqual(grouped.groups[0].tools.map(\.id), ["youtube_search", "connection-youtube"])
    XCTAssertEqual(grouped.ungrouped.map(\.id), ["web_search"])
  }

  func testConnectionProviderAcceptsThePreviouslyDeployedResponseShape() throws {
    let data = try XCTUnwrap(
      #"{"id":"gmail","name":"Gmail","description":"Email access.","category":"Productivity","iconText":"G","permissionsSummary":"Read email","privacyTitle":"Private by default","privacyDescription":"Used only when requested.","authType":"oauth","uiKind":"oauth"}"#
        .data(using: .utf8))

    let provider = try JSONDecoder().decode(ConnectionProvider.self, from: data)

    XCTAssertEqual(provider.connectLabel, "Connect account")
    XCTAssertEqual(provider.reconnectLabel, "Reconnect account")
  }

  func testAPIServerErrorPreservesStatusCodeAndMessage() async throws {
    MockURLProtocol.handler = { request in
      Self.response(
        for: request, status: 409,
        body: #"{"code":"conflict","message":"Wait for this bot to finish."}"#)
    }
    let api = HeyTimAPI(
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

  func testUnauthorizedAPIResponseExpiresTheNativeSession() async throws {
    let expired = expectation(description: "Session expired callback")
    MockURLProtocol.handler = { request in
      Self.response(
        for: request, status: 401,
        body: #"{"code":"unauthorized","message":"Token expired"}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession,
      onSessionExpired: { rejectedToken in
        XCTAssertEqual(rejectedToken, "id-token")
        expired.fulfill()
      }
    ) { "id-token" }

    do {
      _ = try await api.bootstrap()
      XCTFail("Expected the native session to expire")
    } catch let error as APIError {
      XCTAssertEqual(error, .sessionExpired)
    }
    await fulfillment(of: [expired], timeout: 1)
  }

  func testUnauthorizedPublicResponseDoesNotExpireTheSignedInSession() async throws {
    let expired = expectation(description: "Session expiry callback remains unused")
    expired.isInverted = true
    MockURLProtocol.handler = { request in
      Self.response(
        for: request, status: 401,
        body: #"{"code":"invalid_invite","message":"Invitation expired"}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession,
      onSessionExpired: { _ in expired.fulfill() }
    ) { "id-token" }

    do {
      _ = try await api.invitePreview(kind: "group", token: "expired")
      XCTFail("Expected a typed public API error")
    } catch let error as APIError {
      XCTAssertEqual(
        error,
        .requestFailed(status: 401, code: "invalid_invite", message: "Invitation expired"))
    }
    await fulfillment(of: [expired], timeout: 0.1)
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
    let api = HeyTimAPI(
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

  func testSendFromAResetSessionCannotRestoreIntoTheNextAccount() async throws {
    let sendStarted = expectation(description: "Old account send started")
    let releaseSend = DispatchSemaphore(value: 0)
    MockURLProtocol.handler = { request in
      sendStarted.fulfill()
      releaseSend.wait()
      return Self.response(
        for: request, status: 503,
        body: #"{"code":"temporarily_unavailable","message":"Old account failure"}"#)
    }
    let oldAPI = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "old-token" }
    let model = AppModel(api: oldAPI)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.composerText = "Old account draft"

    let oldSend = Task { await model.send() }
    await fulfillment(of: [sendStarted], timeout: 2)
    model.resetSession()
    let newAPI = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "new-token" }
    model.connect(newAPI)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.composerText = "New account draft"
    releaseSend.signal()
    await oldSend.value

    XCTAssertEqual(model.composerText, "New account draft")
    XCTAssertNil(model.errorMessage)
    XCTAssertFalse(model.isSending)
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
    let api = HeyTimAPI(
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
    HeyTimAPI.removeDownloadedPreview(at: file)
    XCTAssertFalse(FileManager.default.fileExists(atPath: previewFolder.path))
  }

  func testMemoryExportDownloadsAndValidatesTheSignedJSONFile() async throws {
    var requestedURLs: [URL] = []
    let export = #"{"format":"HeyTim memory export","version":1,"memories":[]}"#
    MockURLProtocol.handler = { request in
      requestedURLs.append(try XCTUnwrap(request.url))
      if request.url?.host == "files.example.com" {
        return Self.response(for: request, body: export)
      }
      return Self.response(
        for: request, body: #"{"url":"https://files.example.com/signed/memory"}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }

    let data = try await api.downloadMemoryExport()

    XCTAssertEqual(String(decoding: data, as: UTF8.self), export)
    XCTAssertEqual(requestedURLs.map(\.absoluteString), [
      "https://api.example.com/memory/export",
      "https://files.example.com/signed/memory",
    ])
  }

  func testPushRegistrationFailureIsVisibleToSettings() async throws {
    MockURLProtocol.handler = { request in
      Self.response(
        for: request, status: 503,
        body: #"{"code":"native_push_unavailable","message":"Native reply notifications are not configured"}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)

    await model.registerPush(Data(repeating: 1, count: 32), platform: "ios")

    guard case .failed(let message) = model.pushRegistrationState else {
      return XCTFail("Expected a visible push registration failure")
    }
    XCTAssertEqual(message, "Native reply notifications are not configured")
  }

  func testPushSelectionAcceptsConversationTargetsAndRejectsMalformedPayloads() throws {
    let selection = try XCTUnwrap(
      PushSelection(userInfo: ["botId": "bot-one", "groupId": "group-one"]))

    XCTAssertEqual(selection.botId, "bot-one")
    XCTAssertEqual(selection.groupId, "group-one")
    XCTAssertNil(PushSelection(userInfo: ["botId": "", "groupId": 42]))
    XCTAssertNil(PushSelection(userInfo: ["messageId": "message-one"]))
  }

  func testNotificationOpensExactConversationAndRefreshesItsMessages() async throws {
    var writer = try XCTUnwrap(DemoData.bootstrap.bots.first)
    writer.id = "writer"
    writer.name = "Writer"
    var bootstrap = DemoData.bootstrap
    bootstrap.bots.append(writer)
    MockURLProtocol.handler = { request in
      XCTAssertEqual(request.url?.path, "/bots/writer/messages")
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"notification-message","role":"assistant","text":"New reply","createdAt":"2026-09-15T12:00:00Z","status":"complete"}],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = bootstrap
    model.selection = .init(kind: .bot, id: "chief")
    model.messages = DemoData.messages
    model.sheet = .account

    await model.openConversationFromNotification(.init(kind: .bot, id: "writer"))

    XCTAssertEqual(model.selection, .init(kind: .bot, id: "writer"))
    XCTAssertEqual(model.messages.map(\.id), ["notification-message"])
    XCTAssertNil(model.sheet)
    XCTAssertEqual(model.notificationFocusRevision, 1)
  }

  func testNotificationRefreshesBootstrapWhenConversationArrivesDuringLaunch() async throws {
    var writer = try XCTUnwrap(DemoData.bootstrap.bots.first)
    writer.id = "writer"
    writer.name = "Writer"
    var refreshedBootstrap = DemoData.bootstrap
    refreshedBootstrap.bots.append(writer)
    let bootstrapData = try JSONEncoder().encode(refreshedBootstrap)
    var paths: [String] = []
    MockURLProtocol.handler = { request in
      paths.append(request.url?.path ?? "")
      if request.url?.path == "/bootstrap" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          bootstrapData
        )
      }
      return Self.response(for: request, body: #"{"messages":[],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap

    await model.openConversationFromNotification(.init(kind: .bot, id: "writer"))

    XCTAssertEqual(paths, ["/bootstrap", "/bots/writer/messages"])
    XCTAssertEqual(model.selection, .init(kind: .bot, id: "writer"))
    XCTAssertEqual(model.notificationFocusRevision, 1)
  }

  func testCompletedBotConfigurationChangeRefreshesVisibleBootstrap() async throws {
    var renamedBot = try XCTUnwrap(DemoData.bootstrap.bots.first)
    renamedBot.name = "Updated Chief"
    var refreshedBootstrap = DemoData.bootstrap
    refreshedBootstrap.bots = [renamedBot]
    let bootstrapData = try JSONEncoder().encode(refreshedBootstrap)
    var paths: [String] = []
    MockURLProtocol.handler = { request in
      paths.append(request.url?.path ?? "")
      if request.url?.path == "/bootstrap" {
        return (
          HTTPURLResponse(
            url: try XCTUnwrap(request.url), statusCode: 200, httpVersion: nil,
            headerFields: nil)!,
          bootstrapData
        )
      }
      return Self.response(
        for: request,
        body:
          #"{"messages":[{"id":"changed","role":"assistant","text":"Updated","createdAt":"2026-09-15T12:00:00Z","status":"complete","configurationChanged":true}],"nextToken":null}"#)
    }
    let api = HeyTimAPI(
      baseURL: try XCTUnwrap(URL(string: "https://api.example.com")), session: mockSession
    ) { "id-token" }
    let model = AppModel(api: api)
    model.bootstrap = DemoData.bootstrap
    model.selection = .init(kind: .bot, id: "chief")

    try await model.loadMessages()

    XCTAssertEqual(paths, ["/bots/chief/messages", "/bootstrap"])
    XCTAssertEqual(model.selectedBot?.name, "Updated Chief")
  }

  func testPushResponseCompletesAndPublishesNavigationOnMainThread() async throws {
    let delegate = PushNotificationDelegate.shared
    _ = delegate.consumePendingSelection()
    let completion = expectation(description: "Notification response completed")
    let publication = expectation(description: "Push selection published")
    let expected = try XCTUnwrap(PushSelection(userInfo: ["botId": "chief"]))
    let observer = NotificationCenter.default.addObserver(
      forName: .froggyPushSelection, object: nil, queue: nil
    ) { notification in
      XCTAssertTrue(Thread.isMainThread)
      XCTAssertEqual(notification.object as? PushSelection, expected)
      publication.fulfill()
    }
    defer { NotificationCenter.default.removeObserver(observer) }

    delegate.handleResponse(userInfo: ["botId": "chief"]) {
      XCTAssertTrue(Thread.isMainThread)
      completion.fulfill()
    }

    await fulfillment(of: [completion, publication], timeout: 1)
    // AppRoot may already have consumed the buffered selection in the test host.
    _ = delegate.consumePendingSelection()
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

private final class ConcurrentMockURLProtocol: URLProtocol, @unchecked Sendable {
  nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    DispatchQueue.global(qos: .userInitiated).async { [self] in
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
  }
  override func stopLoading() {}
}
