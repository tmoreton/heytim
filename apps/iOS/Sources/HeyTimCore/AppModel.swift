import Foundation
import OSLog
import Observation

public enum AppSheet: Identifiable, Hashable, Sendable {
  case botLibrary
  case botEditor(String?)
  case groupEditor(String?)
  case schedules(ConversationSelection)
  case scheduleRuns(ConversationSelection)
  case memories(String?)
  case account, skills
  case skillEditor(String?)
  case connections
  case documents(String)
  case browser(botId: String, groupId: String?)
  case share(ConversationSelection)

  public var id: String {
    switch self {
    case .botLibrary: "bot-library"
    case .botEditor(let id): "bot-editor-\(id ?? "new")"
    case .groupEditor(let id): "group-editor-\(id ?? "new")"
    case .schedules(let value): "schedules-\(value.kind)-\(value.id)"
    case .scheduleRuns(let value): "runs-\(value.kind)-\(value.id)"
    case .memories(let id): "memory-\(id ?? "personal")"
    case .account: "account"
    case .skills: "skills"
    case .skillEditor(let id): "skill-\(id ?? "new")"
    case .connections: "connections"
    case .documents(let id): "documents-\(id)"
    case .browser(let botId, let groupId): "browser-\(botId)-\(groupId ?? "direct")"
    case .share(let value): "share-\(value.kind)-\(value.id)"
    }
  }
}

@MainActor @Observable
public final class AppModel {
  private struct ComposerDraft: Sendable {
    var text = ""
    var attachments: [Attachment] = []
    var workspaceFiles: [Attachment] = []
    var inboxMessageId: String?

    var isEmpty: Bool {
      text.isEmpty && attachments.isEmpty && workspaceFiles.isEmpty && inboxMessageId == nil
    }
  }

  private static let pushLogger = Logger(subsystem: "ai.heytim.app", category: "push")
  public var bootstrap: Bootstrap?
  public var selection: ConversationSelection? {
    didSet {
      if selection != oldValue { selectionGeneration &+= 1 }
    }
  }
  public var messages: [ChatMessage] = []
  public private(set) var loadedMessagesSelection: ConversationSelection?
  public var nextToken: String?
  public var isLoading = false
  public private(set) var isLoadingMessages = false
  public var isSending = false
  public private(set) var sendingSelection: ConversationSelection?
  public var errorMessage: String?
  public var sheet: AppSheet?
  public var pendingAttachments: [Attachment] = []
  public var pendingWorkspaceFiles: [Attachment] = []
  public var composerText = ""
  public var composerInboxMessageId: String?
  public var groupReplyBotId: String? = "all"
  public private(set) var uploadsInProgress = 0
  public var deepLinkInvite: (kind: String, token: String)?
  public private(set) var pushRegistrationState: PushRegistrationState = .idle
  public private(set) var notificationFocusRevision: UInt = 0

  @ObservationIgnored var api: HeyTimAPI?
  @ObservationIgnored private var pollTask: Task<Void, Never>?
  @ObservationIgnored private var demoMode: Bool
  @ObservationIgnored private var demoDelayedBotSwitch = false
  @ObservationIgnored private var demoHistorySwitch = false
  @ObservationIgnored private var pushToken: Data?
  @ObservationIgnored private var composerDrafts: [ConversationSelection: ComposerDraft] = [:]
  @ObservationIgnored private var selectionGeneration: UInt = 0
  @ObservationIgnored private var sessionGeneration: UInt = 0
  @ObservationIgnored private var refreshedConfigurationMessageIDs: Set<String> = []

  public init(api: HeyTimAPI? = nil, demoMode: Bool = false) {
    self.api = api
    self.demoMode = demoMode
    if demoMode {
      bootstrap = DemoData.bootstrap
      selection = .init(kind: .bot, id: DemoData.bootstrap.bots[0].id)
      let arguments = ProcessInfo.processInfo.arguments
      if arguments.contains("--ui-testing-group-progress") {
        bootstrap = DemoData.groupProgressBootstrap
        selection = .init(kind: .group, id: DemoData.groupProgressGroup.id)
        messages = DemoData.groupProgressMessages
      } else if arguments.contains("--ui-testing-history-switch") {
        bootstrap = DemoData.historySwitchBootstrap
        selection = .init(kind: .group, id: DemoData.groupProgressGroup.id)
        messages = DemoData.historySwitchGroupMessages
        demoHistorySwitch = true
      } else if arguments.contains("--ui-testing-two-bots") {
        bootstrap = DemoData.twoBotsBootstrap
      } else if arguments.contains("--ui-testing-delayed-bot-switch") {
        bootstrap = DemoData.twoBotsBootstrap
        demoDelayedBotSwitch = true
      } else if arguments.contains("--ui-testing-multiple-connections") {
        bootstrap = DemoData.multipleConnectionsBootstrap
      } else if arguments.contains("--ui-testing-empty-conversation") {
        messages = []
      } else if arguments.contains("--ui-testing-activity") {
        messages = DemoData.activityMessages
      } else if arguments.contains("--ui-testing-markdown") {
        messages = DemoData.markdownMessages
      } else if arguments.contains("--ui-testing-delayed-conversation") {
        var staleBootstrap = DemoData.bootstrap
        staleBootstrap.bots[0].processing = true
        bootstrap = staleBootstrap
        isLoadingMessages = true
        let delayedSelection = selection
        Task { [weak self] in
          try? await Task.sleep(for: .milliseconds(250))
          guard let self, self.selection == delayedSelection else { return }
          self.messages = DemoData.scrollMessages
          self.loadedMessagesSelection = delayedSelection
          self.isLoadingMessages = false
        }
      } else if arguments.contains("--ui-testing-scroll") {
        messages = DemoData.scrollMessages
      } else {
        messages = DemoData.messages
      }
      if arguments.contains("--ui-testing-chat-list-launch") {
        selection = nil
        messages = []
      }
      if !isLoadingMessages { loadedMessagesSelection = selection }
      #if DEBUG
        // Keep the destination in the option itself: macOS can interpret a
        // standalone value as a document to open and suppress the main window.
        let sheetPrefix = "--ui-testing-sheet="
        if let argument = arguments.first(where: { $0.hasPrefix(sheetPrefix) }) {
          sheet = Self.uiTestingSheet(
            named: String(argument.dropFirst(sheetPrefix.count)), bootstrap: DemoData.bootstrap)
        } else if let flag = arguments.firstIndex(of: "--ui-testing-sheet"),
          arguments.indices.contains(flag + 1)
        {
          sheet = Self.uiTestingSheet(named: arguments[flag + 1], bootstrap: DemoData.bootstrap)
        }
      #endif
    }
  }

  #if DEBUG
    private static func uiTestingSheet(named name: String, bootstrap: Bootstrap) -> AppSheet? {
      guard let bot = bootstrap.bots.first else { return nil }
      let selection = ConversationSelection(kind: .bot, id: bot.id)
      switch name {
      case "bot-library": return .botLibrary
      case "bot-editor": return .botEditor(nil)
      case "group-editor": return .groupEditor(nil)
      case "schedules": return .schedules(selection)
      case "schedule-runs": return .scheduleRuns(selection)
      case "memory": return .memories(nil)
      case "account": return .account
      case "skills": return .skills
      case "skill-editor": return .skillEditor(nil)
      case "connections": return .connections
      case "documents": return .documents(bot.id)
      case "browser": return .browser(botId: bot.id, groupId: nil)
      case "share": return .share(selection)
      default: return nil
      }
    }
  #endif

  deinit { pollTask?.cancel() }

  public func connect(_ api: HeyTimAPI) {
    sessionGeneration &+= 1
    pollTask?.cancel()
    pollTask = nil
    self.api = api
  }

  public func resetSession() {
    sessionGeneration &+= 1
    pollTask?.cancel()
    pollTask = nil
    api = nil
    bootstrap = nil
    selection = nil
    messages = []
    loadedMessagesSelection = nil
    nextToken = nil
    isLoading = false
    isLoadingMessages = false
    isSending = false
    sendingSelection = nil
    errorMessage = nil
    sheet = nil
    pendingAttachments = []
    pendingWorkspaceFiles = []
    composerText = ""
    composerInboxMessageId = nil
    groupReplyBotId = "all"
    uploadsInProgress = 0
    deepLinkInvite = nil
    pushToken = nil
    pushRegistrationState = .idle
    notificationFocusRevision = 0
    composerDrafts = [:]
    refreshedConfigurationMessageIDs = []
  }

  func requireAPI() throws -> HeyTimAPI {
    guard !demoMode, let api else {
      throw APIError.configuration("The service is not connected.")
    }
    return api
  }

  public var selectedBot: Bot? {
    guard selection?.kind == .bot else { return nil }
    return bootstrap?.bots.first { $0.id == selection?.id }
  }
  public var selectedGroup: BotGroup? {
    guard selection?.kind == .group else { return nil }
    return bootstrap?.groups.first { $0.id == selection?.id }
  }
  public var title: String { selectedBot?.name ?? selectedGroup?.name ?? "Hey Tim" }
  public var subtitle: String {
    selectedBot?.tagline ?? selectedGroup.map {
      "\($0.bots.count) bots · \($0.members.count) people"
    } ?? ""
  }
  public var canStop: Bool {
    if selectedGroup != nil {
      return messages.contains(where: { !$0.isUser && $0.isActive && $0.roundId != nil })
    }
    return selectedBot != nil
      && messages.last(where: { !$0.isUser })?.allowedActions?.contains("cancel") == true
  }
  public var constraints: AppConstraints { bootstrap?.constraints ?? .serviceDefaults }
  public var isUploading: Bool { uploadsInProgress > 0 }
  var sessionIdentifier: UInt { sessionGeneration }
  public var remainingAttachmentSlots: Int {
    guard let selection else { return 0 }
    return availableAttachmentSlots(for: selection)
  }
  public var activeGroupReplyBotId: String? {
    guard let group = selectedGroup, let requested = groupReplyBotId else { return nil }
    if requested == "all" { return group.bots.count > 1 ? requested : group.bots.first?.id }
    return group.bots.contains(where: { $0.id == requested })
      ? requested
      : (group.bots.count > 1 ? "all" : group.bots.first?.id)
  }

  public func load() async {
    guard !demoMode, let api else { return }
    let requestedSession = sessionGeneration
    isLoading = true
    defer {
      if sessionIsCurrent(requestedSession, api: api) { isLoading = false }
    }
    do {
      let value = try await api.bootstrap()
      guard sessionIsCurrent(requestedSession, api: api) else { return }
      bootstrap = value
      chooseAvailableSelection()
      try await loadMessages()
      guard sessionIsCurrent(requestedSession, api: api) else { return }
      if value.needsBotOnboarding { sheet = .botLibrary }
    } catch {
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
    }
  }

  @discardableResult public func refreshBootstrap() async -> Bool {
    guard !demoMode, let api else { return false }
    let requestedSession = sessionGeneration
    do {
      let value = try await api.bootstrap()
      guard sessionIsCurrent(requestedSession, api: api) else { return false }
      bootstrap = value
      if chooseAvailableSelection() { try await loadMessages() }
      return true
    } catch {
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
      return false
    }
  }

  public func select(_ value: ConversationSelection) {
    guard transitionSelection(to: value) else { return }
    Task { try? await loadMessages() }
  }

  /// Opens the exact conversation represented by a notification, including when
  /// the tap arrives during a cold launch or while that conversation is already selected.
  public func openConversationFromNotification(_ value: ConversationSelection) async {
    if demoMode {
      guard conversationExists(value) else { return }
      sheet = nil
      _ = transitionSelection(to: value)
      notificationFocusRevision &+= 1
      return
    }
    guard let api else { return }
    let requestedSession = sessionGeneration
    do {
      if !conversationExists(value) {
        let value = try await api.bootstrap()
        guard sessionIsCurrent(requestedSession, api: api) else { return }
        bootstrap = value
      }
      guard conversationExists(value) else { return }
      sheet = nil
      _ = transitionSelection(to: value)
      notificationFocusRevision &+= 1
      try await loadMessages()
    } catch {
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
    }
  }

  public func loadMessages() async throws {
    guard let requestedSelection = selection else { return }
    let requestedGeneration = selectionGeneration
    let requestedSession = sessionGeneration
    if demoMode {
      if demoHistorySwitch {
        isLoadingMessages = true
        try? await Task.sleep(for: .milliseconds(180))
        guard selection == requestedSelection, selectionGeneration == requestedGeneration else {
          return
        }
        messages = switch requestedSelection.kind {
        case .group: DemoData.historySwitchGroupMessages
        case .bot: requestedSelection.id == "researcher"
          ? DemoData.historySwitchResearchMessages : DemoData.messages
        }
      } else if demoDelayedBotSwitch {
        isLoadingMessages = true
        try? await Task.sleep(for: .milliseconds(550))
        guard selection == requestedSelection, selectionGeneration == requestedGeneration else {
          return
        }
        messages = requestedSelection.id == "researcher"
          ? DemoData.delayedResearchMessages : DemoData.messages
      }
      isLoadingMessages = false
      loadedMessagesSelection = requestedSelection
      return
    }
    guard let api else {
      isLoadingMessages = false
      throw APIError.configuration("The service is not connected.")
    }
    if messages.isEmpty { isLoadingMessages = true }
    defer {
      if selection == requestedSelection, selectionGeneration == requestedGeneration,
        sessionIsCurrent(requestedSession, api: api)
      {
        isLoadingMessages = false
      }
    }
    let page =
      requestedSelection.kind == .bot
      ? try await api.messages(bot: requestedSelection.id)
      : try await api.messages(group: requestedSelection.id)
    guard selection == requestedSelection, selectionGeneration == requestedGeneration,
      sessionIsCurrent(requestedSession, api: api)
    else {
      return
    }
    loadedMessagesSelection = requestedSelection
    let wasProcessing = messages.contains(where: \.isActive)
    let listedProcessing: Bool
    switch requestedSelection.kind {
    case .bot:
      listedProcessing = bootstrap?.bots.first { $0.id == requestedSelection.id }?.processing == true
    case .group:
      listedProcessing = bootstrap?.groups.first { $0.id == requestedSelection.id }?.processing == true
    }
    messages = Self.mergeLatest(current: messages, latest: page.messages)
    nextToken = page.nextToken
    if !messages.contains(where: \.isActive), wasProcessing || listedProcessing {
      _ = await refreshBootstrap()
      guard selection == requestedSelection, selectionGeneration == requestedGeneration,
        sessionIsCurrent(requestedSession, api: api)
      else { return }
    }
    configurePolling()
    let changedMessageIDs = Set(
      page.messages.lazy.filter { $0.configurationChanged == true }.map(\.id)
    )
    let unrefreshedMessageIDs = changedMessageIDs.subtracting(refreshedConfigurationMessageIDs)
    if !unrefreshedMessageIDs.isEmpty {
      if await refreshBootstrap() {
        refreshedConfigurationMessageIDs.formUnion(unrefreshedMessageIDs)
      }
    }
  }

  public func loadEarlier() async {
    guard let requestedSelection = selection, let cursor = nextToken, let api, !demoMode else {
      return
    }
    let requestedGeneration = selectionGeneration
    let requestedSession = sessionGeneration
    do {
      let page =
        requestedSelection.kind == .bot
        ? try await api.messages(bot: requestedSelection.id, cursor: cursor)
        : try await api.messages(group: requestedSelection.id, cursor: cursor)
      guard selection == requestedSelection, selectionGeneration == requestedGeneration,
        sessionIsCurrent(requestedSession, api: api)
      else {
        return
      }
      messages = Self.mergeEarlier(current: messages, earlier: page.messages)
      nextToken = page.nextToken
    } catch {
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
    }
  }

  public func send(homeAssistantHint: HomeAssistantRouteHint? = nil) async {
    let requestedSession = sessionGeneration
    let submitted = ComposerDraft(
      text: composerText, attachments: pendingAttachments,
      workspaceFiles: pendingWorkspaceFiles, inboxMessageId: composerInboxMessageId)
    let text = submitted.text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard let selection, !text.isEmpty || !submitted.attachments.isEmpty
      || !submitted.workspaceFiles.isEmpty, !isSending,
      !isUploading
    else { return }
    let attachmentIds = submitted.attachments.map(\.id)
    let workspaceFileIds = submitted.workspaceFiles.map(\.id)
    let replyBotId = selection.kind == .group ? activeGroupReplyBotId : nil
    composerText = ""
    composerInboxMessageId = nil
    pendingAttachments = []
    pendingWorkspaceFiles = []
    composerDrafts[selection] = nil
    isSending = true
    sendingSelection = selection
    defer {
      if sessionGeneration == requestedSession {
        isSending = false
        if sendingSelection == selection { sendingSelection = nil }
      }
    }
    if demoMode {
      let now = ISO8601DateFormatter().string(from: Date())
      messages.append(
        ChatMessage(
          id: UUID().uuidString, role: "user", text: text, createdAt: now, status: "complete"))
      await Task.yield()
      messages.append(
        ChatMessage(
          id: UUID().uuidString, role: "assistant", authorName: selectedBot?.name ?? "Hey Tim",
          text: "This is the native app’s offline test reply.", createdAt: now, status: "complete"))
      return
    }
    guard let api else {
      if sessionGeneration == requestedSession {
        restoreSubmittedDraft(submitted, for: selection)
      }
      return
    }
    do {
      if selection.kind == .bot {
        try await api.sendMessage(
          bot: selection.id, text: text, attachments: attachmentIds,
          workspaceFiles: workspaceFileIds, inboxMessageId: submitted.inboxMessageId,
          homeAssistantHint: homeAssistantHint)
      } else {
        try await api.sendMessage(
          group: selection.id, text: text, replyBotId: replyBotId,
          attachments: attachmentIds, workspaceFiles: workspaceFileIds)
      }
    } catch {
      guard sessionIsCurrent(requestedSession, api: api) else { return }
      restoreSubmittedDraft(submitted, for: selection)
      present(error)
      return
    }

    guard self.selection == selection, sessionIsCurrent(requestedSession, api: api) else { return }
    do {
      try await loadMessages()
    } catch {
      // The message was accepted. Keep the composer cleared even if the
      // follow-up refresh fails so the same message is not sent twice.
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
    }
  }

  public func stop() async {
    if let group = selectedGroup,
      let runId = messages.last(where: { !$0.isUser && $0.isActive && $0.roundId != nil })?.roundId,
      let api, !demoMode
    {
      do {
        try await api.cancelGroupRun(groupId: group.id, runId: runId)
        try await loadMessages()
      } catch { present(error) }
      return
    }
    guard let bot = selectedBot,
      let turn = messages.last(where: { !$0.isUser && $0.isActive }),
      let api, !demoMode
    else { return }
    do {
      try await api.cancel(botId: bot.id, turnId: Self.directTurnID(turn.id))
      try await loadMessages()
    } catch { present(error) }
  }

  public func approve(_ message: ChatMessage, always: Bool) async {
    guard let api, !demoMode else { return }
    do {
      if let group = selectedGroup, let runId = message.runId, let taskId = message.taskId {
        try await api.decideGroupAction(groupId: group.id, runId: runId, taskId: taskId, approved: true)
      } else if let bot = selectedBot {
        try await api.approve(botId: bot.id, turnId: Self.directTurnID(message.id), always: false)
      } else { return }
      try await loadMessages()
    } catch { present(error) }
  }

  public func reject(_ message: ChatMessage) async {
    guard let api, !demoMode else { return }
    do {
      if let group = selectedGroup, let runId = message.runId, let taskId = message.taskId {
        try await api.decideGroupAction(groupId: group.id, runId: runId, taskId: taskId, approved: false)
      } else if let bot = selectedBot {
        try await api.cancel(botId: bot.id, turnId: Self.directTurnID(message.id))
      } else { return }
      try await loadMessages()
    } catch { present(error) }
  }

  public func saveDecision(_ message: ChatMessage) async {
    guard let group = selectedGroup, let api, !demoMode else { return }
    do {
      _ = try await api.saveDecision(groupId: group.id, messageId: message.id)
      await refreshBootstrap()
      try await loadMessages()
    } catch { present(error) }
  }

  public func removeAttachment(_ id: String) { pendingAttachments.removeAll { $0.id == id } }
  public func removeWorkspaceFile(_ id: String) {
    pendingWorkspaceFiles.removeAll { $0.id == id }
  }
  public func addWorkspaceFile(_ file: Attachment) {
    guard selection != nil, remainingAttachmentSlots > 0,
      !pendingWorkspaceFiles.contains(where: { $0.id == file.id })
    else { return }
    pendingWorkspaceFiles.append(file)
  }

  public func registerPush(_ token: Data, platform: String) async {
    pushToken = token
    guard let api, !demoMode else { return }
    pushRegistrationState = .registering
    do {
      try await api.registerAPNsToken(token, platform: platform)
      pushRegistrationState = .registered
    } catch {
      pushRegistrationState = .failed(error.localizedDescription)
      Self.pushLogger.error(
        "Push registration failed without interrupting the chat: \(error.localizedDescription, privacy: .public)"
      )
    }
  }

  public func unregisterPush() async {
    guard let token = pushToken, let api, !demoMode else { return }
    do {
      try await api.unregisterAPNsToken(token)
      pushToken = nil
      pushRegistrationState = .idle
    } catch {
      Self.pushLogger.error(
        "Push unregistration failed: \(error.localizedDescription, privacy: .public)")
    }
  }

  public func reportPushRegistrationFailure(_ message: String) {
    pushRegistrationState = .failed(message)
  }

  @discardableResult public func handleConnectionCallback(_ url: URL) async
    -> ConnectionAuthorizationCallback?
  {
    guard let callback = ConnectionAuthorizationCallback(url: url) else { return nil }
    switch callback.status {
    case .connected:
      await refreshBootstrap()
    case .error:
      errorMessage = "The account could not be connected. Please try again."
    }
    return callback
  }

  public func upload(urls: [URL], for requestedSelection: ConversationSelection? = nil) async {
    guard let api, !demoMode, !isSending,
      let targetSelection = requestedSelection ?? selection
    else { return }
    let requestedSession = sessionGeneration
    let acceptedCount = reserveAttachmentSlots(urls.count, for: targetSelection)
    guard acceptedCount > 0 else { return }
    defer {
      if sessionGeneration == requestedSession { releaseAttachmentSlots(acceptedCount) }
    }
    await uploadReserved(
      urls: Array(urls.prefix(acceptedCount)), for: targetSelection, using: api,
      session: requestedSession)
  }

  @discardableResult public func reserveAttachmentSlots(
    _ requestedCount: Int, for targetSelection: ConversationSelection
  ) -> Int {
    guard requestedCount > 0, !isSending else { return 0 }
    let acceptedCount = min(requestedCount, availableAttachmentSlots(for: targetSelection))
    guard acceptedCount > 0 else { return 0 }
    uploadsInProgress += acceptedCount
    return acceptedCount
  }

  public func releaseAttachmentSlots(_ count: Int, session: UInt? = nil) {
    if let session, session != sessionGeneration { return }
    uploadsInProgress = max(0, uploadsInProgress - max(0, count))
  }

  @discardableResult public func enqueueUpload(
    urls: [URL], for requestedSelection: ConversationSelection? = nil
  ) -> Bool {
    guard let api, !demoMode, !isSending,
      let targetSelection = requestedSelection ?? selection
    else { return false }
    let requestedSession = sessionGeneration
    let acceptedCount = reserveAttachmentSlots(urls.count, for: targetSelection)
    guard acceptedCount > 0 else { return false }
    let acceptedURLs = Array(urls.prefix(acceptedCount))
    Task { @MainActor in
      defer {
        if sessionGeneration == requestedSession { releaseAttachmentSlots(acceptedCount) }
      }
      await uploadReserved(
        urls: acceptedURLs, for: targetSelection, using: api, session: requestedSession)
    }
    return true
  }

  public func uploadReserved(
    urls: [URL], for targetSelection: ConversationSelection, session requestedSession: UInt? = nil
  ) async {
    let requestedSession = requestedSession ?? sessionGeneration
    guard requestedSession == sessionGeneration, let api, !demoMode else { return }
    await uploadReserved(
      urls: urls, for: targetSelection, using: api, session: requestedSession)
  }

  private func uploadReserved(
    urls: [URL], for targetSelection: ConversationSelection, using api: HeyTimAPI,
    session requestedSession: UInt
  ) async {
    for url in urls {
      let scoped = url.startAccessingSecurityScopedResource()
      defer { if scoped { url.stopAccessingSecurityScopedResource() } }
      do {
        let attachment = try await api.upload(try UploadAsset(url: url))
        guard sessionIsCurrent(requestedSession, api: api) else { return }
        append(attachment, to: targetSelection)
      } catch {
        if sessionIsCurrent(requestedSession, api: api) { present(error) }
        return
      }
    }
  }

  public func saveBot(_ draft: BotDraft, id: String?) async -> Bool {
    guard let api, !demoMode else { return true }
    do {
      let bot = try await api.saveBot(draft, id: id)
      await refreshBootstrap()
      select(.init(kind: .bot, id: bot.id))
      return true
    } catch {
      present(error)
      return false
    }
  }
  public func installTemplate(_ id: String) async {
    guard let api, !demoMode else { return }
    do {
      let bot = try await api.installBotTemplate(id)
      await refreshBootstrap()
      select(.init(kind: .bot, id: bot.id))
      sheet = nil
    } catch { present(error) }
  }
  public func saveGroup(_ draft: GroupDraft, id: String?) async -> Bool {
    guard let api, !demoMode else { return true }
    do {
      let group = try await api.saveGroup(draft, id: id)
      await refreshBootstrap()
      select(.init(kind: .group, id: group.id))
      return true
    } catch {
      present(error)
      return false
    }
  }
  public func deleteCurrent() async {
    guard let deletedSelection = selection, let api, !demoMode else { return }
    do {
      if deletedSelection.kind == .bot {
        try await api.deleteBot(deletedSelection.id)
      } else {
        try await api.deleteGroup(deletedSelection.id)
      }
      composerDrafts[deletedSelection] = nil
      if selection == deletedSelection {
        setSelection(nil)
        messages = []
      }
      await refreshBootstrap()
      try await loadMessages()
    } catch { present(error) }
  }
  public func clearCurrent(forgetMemory: Bool) async {
    guard let clearedSelection = selection, let bot = selectedBot, let api, !demoMode else {
      return
    }
    do {
      try await api.clearBot(bot.id, forgetMemory: forgetMemory)
      guard selection == clearedSelection else { return }
      pollTask?.cancel()
      messages = []
      nextToken = nil
    } catch { present(error) }
  }

  public func share(_ selection: ConversationSelection) async -> URL? {
    guard let api, !demoMode else { return nil }
    let requestedSession = sessionGeneration
    do {
      let url =
        selection.kind == .bot
        ? try await api.share(botId: selection.id, scope: "chat")
        : try await api.shareGroup(selection.id)
      guard sessionIsCurrent(requestedSession, api: api) else { return nil }
      return url
    } catch {
      if sessionIsCurrent(requestedSession, api: api) { present(error) }
      return nil
    }
  }

  public func handle(url: URL) {
    guard let invite = InvitationParser.parse(url) else { return }
    deepLinkInvite = (invite.kind, invite.token)
  }

  public func acceptPendingInvite() async {
    guard let invite = deepLinkInvite, let api, !demoMode else { return }
    do {
      switch invite.kind {
      case "group":
        let group = try await api.joinGroup(token: invite.token)
        await refreshBootstrap()
        select(.init(kind: .group, id: group.id))
      case "skill":
        _ = try await api.importSkill(invite.token)
        await refreshBootstrap()
      default:
        let bot = try await api.importShare(invite.token)
        await refreshBootstrap()
        select(.init(kind: .bot, id: bot.id))
      }
      deepLinkInvite = nil
    } catch { present(error) }
  }

  public func present(_ error: Error) { errorMessage = error.localizedDescription }

  private func sessionIsCurrent(_ generation: UInt, api: HeyTimAPI) -> Bool {
    sessionGeneration == generation && self.api === api
  }

  private func conversationExists(_ value: ConversationSelection) -> Bool {
    switch value.kind {
    case .bot: bootstrap?.bots.contains(where: { $0.id == value.id }) == true
    case .group: bootstrap?.groups.contains(where: { $0.id == value.id }) == true
    }
  }

  private func saveVisibleDraft() {
    guard let selection else { return }
    let draft = ComposerDraft(
      text: composerText, attachments: pendingAttachments,
      workspaceFiles: pendingWorkspaceFiles, inboxMessageId: composerInboxMessageId)
    composerDrafts[selection] = draft.isEmpty ? nil : draft
  }

  private func setSelection(_ value: ConversationSelection?) {
    selection = value
    groupReplyBotId = "all"
    guard let value else {
      composerText = ""
      composerInboxMessageId = nil
      pendingAttachments = []
      pendingWorkspaceFiles = []
      return
    }
    let draft = composerDrafts.removeValue(forKey: value) ?? ComposerDraft()
    composerText = draft.text
    composerInboxMessageId = draft.inboxMessageId
    pendingAttachments = draft.attachments
    pendingWorkspaceFiles = draft.workspaceFiles
  }

  @discardableResult private func transitionSelection(
    to value: ConversationSelection?
  ) -> Bool {
    guard value != selection else { return false }
    saveVisibleDraft()
    setSelection(value)
    messages = []
    loadedMessagesSelection = nil
    nextToken = nil
    isLoadingMessages = value != nil && (!demoMode || demoDelayedBotSwitch || demoHistorySwitch)
    pollTask?.cancel()
    pollTask = nil
    return true
  }

  private func append(_ attachment: Attachment, to target: ConversationSelection) {
    if selection == target {
      guard pendingAttachments.count + pendingWorkspaceFiles.count < constraints.maxAttachmentsPerMessage,
        !pendingAttachments.contains(where: { $0.id == attachment.id })
      else { return }
      pendingAttachments.append(attachment)
      return
    }

    var draft = composerDrafts[target] ?? ComposerDraft()
    guard draft.attachments.count + draft.workspaceFiles.count < constraints.maxAttachmentsPerMessage,
      !draft.attachments.contains(where: { $0.id == attachment.id })
    else { return }
    draft.attachments.append(attachment)
    composerDrafts[target] = draft
  }

  private func availableAttachmentSlots(for target: ConversationSelection) -> Int {
    let attachmentCount =
      selection == target
      ? pendingAttachments.count + pendingWorkspaceFiles.count
      : (composerDrafts[target]?.attachments.count ?? 0)
        + (composerDrafts[target]?.workspaceFiles.count ?? 0)
    return max(
      0, constraints.maxAttachmentsPerMessage - attachmentCount - uploadsInProgress)
  }

  private func restoreSubmittedDraft(_ submitted: ComposerDraft, for target: ConversationSelection)
  {
    if selection == target {
      let current = ComposerDraft(
        text: composerText, attachments: pendingAttachments,
        workspaceFiles: pendingWorkspaceFiles, inboxMessageId: composerInboxMessageId)
      let restored = mergedDraft(submitted, with: current)
      composerText = restored.text
      composerInboxMessageId = restored.inboxMessageId
      pendingAttachments = restored.attachments
      pendingWorkspaceFiles = restored.workspaceFiles
    } else {
      composerDrafts[target] = mergedDraft(
        submitted, with: composerDrafts[target] ?? ComposerDraft())
    }
  }

  private func mergedDraft(_ submitted: ComposerDraft, with current: ComposerDraft) -> ComposerDraft
  {
    let text: String
    if submitted.text.isEmpty || submitted.text == current.text {
      text = current.text
    } else if current.text.isEmpty {
      text = submitted.text
    } else {
      text = submitted.text + "\n" + current.text
    }

    var attachmentIDs = Set<String>()
    let attachments = (submitted.attachments + current.attachments)
      .filter { attachmentIDs.insert($0.id).inserted }
      .prefix(constraints.maxAttachmentsPerMessage)
    var workspaceIDs = Set<String>()
    let workspaceFiles = (submitted.workspaceFiles + current.workspaceFiles)
      .filter { workspaceIDs.insert($0.id).inserted }
      .prefix(max(0, constraints.maxAttachmentsPerMessage - attachments.count))
    return ComposerDraft(
      text: text, attachments: Array(attachments), workspaceFiles: Array(workspaceFiles),
      inboxMessageId: current.inboxMessageId ?? submitted.inboxMessageId)
  }

  @discardableResult private func chooseAvailableSelection() -> Bool {
    guard let bootstrap else {
      return transitionSelection(to: nil)
    }
    if let value = selection {
      if value.kind == .bot, bootstrap.bots.contains(where: { $0.id == value.id }) { return false }
      if value.kind == .group, bootstrap.groups.contains(where: { $0.id == value.id }) {
        return false
      }
    }
    #if os(iOS)
      // On iOS, an unselected chat means the conversation list is the home screen.
      if selection == nil { return false }
    #endif
    if let group = bootstrap.groups.first {
      return transitionSelection(to: .init(kind: .group, id: group.id))
    } else if let bot = bootstrap.bots.first {
      return transitionSelection(to: .init(kind: .bot, id: bot.id))
    } else {
      return transitionSelection(to: nil)
    }
  }

  private func configurePolling() {
    pollTask?.cancel()
    guard messages.contains(where: { $0.isActive }) else { return }
    pollTask = Task { [weak self] in
      var failures = 0
      while !Task.isCancelled {
        let delay = Self.nextPollingDelay(base: 1_500, failures: failures)
        try? await Task.sleep(for: .milliseconds(delay))
        guard let self, !Task.isCancelled else { return }
        do {
          try await self.loadMessages()
          failures = 0
        } catch { failures += 1 }
        if !self.messages.contains(where: { $0.isActive }) { return }
      }
    }
  }

  public static func nextPollingDelay(
    base: Int, failures: Int, random: Double = Double.random(in: 0...1)
  ) -> Int {
    guard failures > 0 else { return base }
    let bounded = min(
      30_000.0, Double(base) * pow(2.0, Double(min(failures, 30))))
    let jitter = 0.8 + min(1, max(0, random)) * 0.4
    return min(30_000, Int((bounded * jitter).rounded()))
  }

  public static func directTurnID(_ messageID: String) -> String {
    messageID.hasSuffix("-assistant") ? String(messageID.dropLast("-assistant".count)) : messageID
  }

  public static func mergeLatest(current: [ChatMessage], latest: [ChatMessage]) -> [ChatMessage] {
    let ids = Set(latest.map(\.id))
    return current.filter { !ids.contains($0.id) } + latest
  }
  public static func mergeEarlier(current: [ChatMessage], earlier: [ChatMessage]) -> [ChatMessage] {
    let ids = Set(current.map(\.id))
    return earlier.filter { !ids.contains($0.id) } + current
  }
}

public enum DemoData {
  public static let constraints = AppConstraints(
    botNameMaxLength: 60, botTaglineMaxLength: 160, botPromptMaxLength: 20_000,
    groupNameMaxLength: 80, groupMemoryMaxLength: 20_000, messageMaxLength: 20_000,
    scheduleNameMaxLength: 100, schedulePromptMaxLength: 20_000,
    scheduleDayOfMonthMin: 1, scheduleDayOfMonthMax: 28,
    skillNameMaxLength: 80, skillDescriptionMaxLength: 500, skillInstructionsMaxLength: 30_000,
    memoryMaxLength: 2_000, maxAttachmentsPerMessage: 10,
    imageMaxBytes: 20_000_000, documentMaxBytes: 50_000_000, maxPhotoDimension: 4096
  )
  public static let tools = [
    Capability(
      id: "web_search", name: "Web Search",
      description: "Find current information from public web sources.", risk: "read",
      category: "Research", actions: ["Search the web", "Open public pages"],
      source: "official"),
    Capability(
      id: "code_interpreter", name: "Files & Data",
      description: "Analyze data and create useful documents.", risk: "interactive",
      category: "Files", actions: ["Analyze files", "Create documents"],
      source: "official"),
  ]
  private static let demoConnectionProviders = [
    ConnectionProvider(
      id: "x", name: "X",
      description: "Search posts and read your profile with a connected X account.",
      category: "Social", iconText: "X",
      permissionsSummary: "Read-only account access",
      privacyTitle: "Your X account stays private",
      privacyDescription: "Connect an account before a bot can search X.",
      familyId: "x", familyName: "X",
      familyDescription: "Connect an X account for search and profile access.",
      familyIconText: "X", familyLogoProviderId: "x",
      serviceName: "Account access"),
    ConnectionProvider(
      id: "youtube", name: "YouTube",
      description: "Search public videos with your connected YouTube account; channel tools are optional.",
      category: "Social", iconText: "YT",
      permissionsSummary: "Read-only YouTube account access",
      privacyTitle: "Your YouTube connection is optional",
      privacyDescription: "Connect an account before a bot can search YouTube.",
      familyId: "youtube", familyName: "YouTube",
      familyDescription: "Connect an account for YouTube search.",
      familyIconText: "YT", familyLogoProviderId: "youtube",
      serviceName: "YouTube account"),
    ConnectionProvider(
      id: "home_assistant", name: "Home Assistant",
      description: "Read exposed devices and request home actions through your own Home Assistant instance.",
      category: "Smart home", iconText: "HA",
      permissionsSummary: "Only entities exposed to Assist; each action requires review",
      privacyTitle: "Your home stays under your control",
      privacyDescription: "Connect your own Home Assistant Assist MCP server.",
      familyId: "mcp", familyName: "MCP servers",
      familyDescription: "Connect Home Assistant or another MCP server.",
      familyIconText: "MCP", familyLogoProviderId: "mcp_server"),
    ConnectionProvider(
      id: "mcp_server", name: "MCP server",
      description: "Connect a remote MCP server by HTTPS URL and access token.",
      category: "Integrations", iconText: "MCP",
      permissionsSummary: "The selected bot can use tools exposed by this server",
      privacyTitle: "Assign each server only to bots that need it",
      privacyDescription: "The access token is stored privately on the server.",
      familyId: "mcp", familyName: "MCP servers",
      familyDescription: "Connect Home Assistant or another MCP server.",
      familyIconText: "MCP", familyLogoProviderId: "mcp_server"),
    ConnectionProvider(
      id: "gmail", name: "Gmail",
      description: "Search and summarize email, then create drafts for review.",
      category: "Email", iconText: "G",
      permissionsSummary: "No sending, deleting, relabeling, or archiving",
      privacyTitle: "Your Gmail account stays private",
      privacyDescription: "Used only when a bot needs the account.",
      familyId: "google", familyName: "Google",
      familyDescription: "Connect the Google accounts each bot needs.",
      familyIconText: "G", familyLogoProviderId: "google_workspace",
      serviceName: "Gmail"),
    ConnectionProvider(
      id: "google_workspace", name: "Google Workspace",
      description: "Search and read Drive files, Docs, and Calendar events.",
      category: "Productivity", iconText: "GW",
      permissionsSummary: "Read-only Drive, Docs, and Calendar access",
      privacyTitle: "Workspace content stays user-scoped",
      privacyDescription: "It cannot change files or calendar events.",
      familyId: "google", familyName: "Google",
      familyDescription: "Connect the Google accounts each bot needs.",
      familyIconText: "G", familyLogoProviderId: "google_workspace",
      serviceName: "Workspace"),
  ]
  public static let skills = [
    Skill(
      id: "deep-research", name: "Deep Research",
      description: "Produce a current, sourced, decision-ready synthesis.",
      category: "Research", featured: true, version: 1,
      requiredToolIds: ["web_search", "code_interpreter"], source: "official",
      visibility: "public", editable: false)
  ]
  public static let botTemplates = [
    BotTemplate(
      id: "research-reports", version: 1, name: "Research & Reports",
      tagline: "Finds reliable answers and turns them into useful files.",
      prompt:
        "Research broad questions with current, high-quality sources and lead with the conclusion. Distinguish evidence from interpretation and create a polished report when it helps.",
      color: "#5C6BC0", skillIds: ["deep-research"], toolIds: [],
      category: "Research", author: "Hey Tim", tags: ["research", "reports"],
      featured: true)
  ]
  public static let bootstrap = Bootstrap(
    bots: [
      Bot(
        id: "chief", name: "Chief", tagline: "Your capable AI chief of staff", color: "#FFBC3B",
        prompt: "Help thoughtfully.", toolIds: [], skillIds: [],
        systemRole: "chief",
        createdAt: "2026-09-12T12:00:00.000Z", updatedAt: "2026-09-12T12:00:00.000Z",
        lastMessage: "Your project brief is ready.", lastMessageAt: "2026-09-12T12:01:00.000Z",
        allowedActions: ["schedule", "share", "documents", "browser", "edit", "clear", "delete"])
    ],
    botTemplates: botTemplates, connectionProviders: demoConnectionProviders,
    needsBotOnboarding: false, groups: [], tools: tools,
    retiredToolIds: [], skills: skills, constraints: constraints
  )
  public static var multipleConnectionsBootstrap: Bootstrap {
    var value = bootstrap
    value.tools += [
      Capability(
        id: "connection_gmail_alpha", name: "Gmail",
        description: "Read and draft email.", provider: "gmail", source: "user",
        connectedAccount: "alpha@example.com"),
      Capability(
        id: "connection_gmail_beta", name: "Gmail",
        description: "Read and draft email.", provider: "gmail", source: "user",
        connectedAccount: "beta@example.com"),
      Capability(
        id: "connection_github_team", name: "GitHub",
        description: "Read connected repositories.", provider: "github", source: "user",
        connectedAccount: "team", repositories: [
          ConnectedRepository(id: 101, name: "team/api"),
          ConnectedRepository(id: 102, name: "team/app"),
        ]),
    ]
    value.connectionProviders.append(
      ConnectionProvider(
        id: "github", name: "GitHub", description: "Read connected repositories.",
        category: "Development", iconText: "GH",
        permissionsSummary: "Read-only repository access",
        privacyTitle: "Choose repositories for each bot",
        privacyDescription: "Only selected repositories are available."))
    return value
  }
  public static var twoBotsBootstrap: Bootstrap {
    var value = bootstrap
    value.bots.append(
      Bot(
        id: "researcher", name: "Research Bot", tagline: "Investigates questions",
        color: "#3488E8", prompt: "Research carefully.", toolIds: [], skillIds: [],
        createdAt: "2026-09-12T12:02:00.000Z", updatedAt: "2026-09-12T12:02:00.000Z",
        lastMessage: "Ready to research.", lastMessageAt: "2026-09-12T12:03:00.000Z",
        allowedActions: ["schedule", "share", "documents", "browser", "edit", "clear", "delete"]))
    return value
  }
  public static let messages = [
    ChatMessage(
      id: "m1", role: "user", authorName: "You", isMine: true,
      text: "Can you summarize the launch plan?", createdAt: "2026-09-12T12:00:00.000Z",
      status: "complete"),
    ChatMessage(
      id: "m2", role: "assistant", authorType: "bot", authorId: "chief", authorName: "Chief",
      authorColor: "#FFBC3B",
      text:
        "Absolutely. The native SwiftUI client is sharing the same backend and API contract across iPhone and Mac.\n\n- Authentication and data stay in AWS.\n- Conversations and background tasks are preserved.\n- The existing web app remains available.",
      createdAt: "2026-09-12T12:01:00.000Z", status: "complete"),
  ]
  public static let scrollMessages = (1...24).map { index in
    ChatMessage(
      id: "scroll-\(index)", role: index.isMultiple(of: 2) ? "assistant" : "user",
      authorType: index.isMultiple(of: 2) ? "bot" : "user",
      authorName: index.isMultiple(of: 2) ? "Chief" : "You",
      authorColor: index.isMultiple(of: 2) ? "#FFBC3B" : nil,
      isMine: !index.isMultiple(of: 2),
      text: index == 24
        ? "Latest message before send."
        : "Conversation history item \(index) with enough detail to exercise scrolling.",
      createdAt: "2026-09-12T12:\(String(format: "%02d", index)):00.000Z",
      status: "complete")
  }
  public static var delayedResearchMessages: [ChatMessage] {
    var value = scrollMessages
    value[value.count - 1].text = String(
      repeating: "A researched detail that makes this response taller than the screen.\n\n",
      count: 18) + "Research Bot answer visible after loading."
    return value
  }
  public static let activityMessages = [
    ChatMessage(
      id: "activity-user", role: "user", isMine: true,
      text: "Please inspect the project and summarize what needs attention.",
      createdAt: "2026-09-12T12:02:00.000Z", status: "complete"),
    ChatMessage(
      id: "activity-assistant", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B", text: "",
      activity: [
        "Reviewing the repository structure and current branch.",
        "Checking `README.md` for the intended release workflow.",
        "Inspecting the native conversation layout and message state.",
        "Comparing API routes with the generated client contract.",
        "Checking notification delivery and account cleanup behavior.",
        "Reviewing attachment handling for images and documents.",
        "Verifying session changes cannot leak drafts between accounts.",
        "Running the focused native test suite.",
        "Checking the final build for embedded framework duplication.",
        "Preparing the verified summary and recommended follow-up.",
      ],
      createdAt: "2026-09-12T12:02:01.000Z", activityUpdatedAt: "2026-09-12T12:02:10.000Z",
      status: "running"),
  ]
  public static let groupProgressGroup = BotGroup(
    id: "research-team", name: "Research Team", memory: "", memoryUpdatedAt: nil,
    memoryUpdatedByName: nil, ownerId: "owner", currentUserId: "owner", isOwner: true,
    allowedActions: ["schedule", "share", "viewMemory", "manageMemory", "edit", "clear", "delete"],
    members: [
      GroupMember(id: "owner", name: "You", role: "owner", allowedActions: [])
    ],
    bots: [
      GroupBot(
        id: "researcher", ownerId: "owner", name: "YouTube Research",
        tagline: "Researches source material", color: "#3488E8", systemRole: nil),
      GroupBot(
        id: "chief", ownerId: "owner", name: "Chief", tagline: "Coordinates the team",
        color: "#FFBC3B", systemRole: "chief"),
      GroupBot(
        id: "reviewer", ownerId: "owner", name: "Reviewer", tagline: "Checks the result",
        color: "#6C5CE7", systemRole: nil),
    ], decisions: [], createdAt: "2026-09-13T11:00:00.000Z",
    updatedAt: "2026-09-13T11:00:00.000Z", lastMessage: "Researching the request",
    lastMessageAt: "2026-09-13T11:00:00.000Z", processing: true,
    processingBotName: "YouTube Research")
  public static var groupProgressBootstrap: Bootstrap {
    var value = bootstrap
    value.groups = [groupProgressGroup]
    return value
  }
  public static var historySwitchBootstrap: Bootstrap {
    var value = twoBotsBootstrap
    var group = groupProgressGroup
    group.processing = false
    group.processingBotName = nil
    value.groups = [group]
    return value
  }
  public static let historySwitchGroupMessages = [
    ChatMessage(
      id: "history-group-user", role: "user", authorName: "You", isMine: true,
      text: "Group conversation history before switching.",
      createdAt: "2026-09-13T11:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "history-group-reply", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B",
      text: "Group answer remains available after switching.",
      createdAt: "2026-09-13T11:01:00.000Z", status: "complete"),
  ]
  public static let historySwitchResearchMessages = [
    ChatMessage(
      id: "history-research-user", role: "user", authorName: "You", isMine: true,
      text: "Research Bot conversation history before switching.",
      createdAt: "2026-09-13T12:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "history-research-reply", role: "assistant", authorType: "bot",
      authorId: "researcher", authorName: "Research Bot", authorColor: "#3488E8",
      text: "Research Bot answer remains available after switching.",
      createdAt: "2026-09-13T12:01:00.000Z", status: "complete"),
  ]
  public static let groupProgressMessages = [
    ChatMessage(
      id: "group-request", role: "user", authorType: "user", authorName: "You", isMine: true,
      text: "Research the launch options and recommend the best approach.",
      createdAt: "2026-09-13T11:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "group-running", role: "assistant", authorType: "bot", authorId: "researcher",
      authorName: "YouTube Research", authorColor: "#3488E8", text: "",
      activity: [
        "Reviewing the available source material.",
        "Comparing the strongest options and supporting evidence.",
      ], roundId: "round-1", roundPosition: 1, roundSize: 3, roundRole: "contributor",
      createdAt: "2026-09-13T11:00:01.000Z", status: "running"),
    ChatMessage(
      id: "group-pending", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B", text: "", roundId: "round-1",
      roundPosition: 2, roundSize: 3, roundRole: "synthesizer",
      createdAt: "2026-09-13T11:00:02.000Z", status: "pending"),
    ChatMessage(
      id: "group-waiting", role: "assistant", authorType: "bot", authorId: "reviewer",
      authorName: "Reviewer", authorColor: "#FFBC3B", text: "", roundId: "round-1",
      roundPosition: 3, roundSize: 3, roundRole: "contributor",
      createdAt: "2026-09-13T11:00:03.000Z", status: "waiting"),
  ]
  public static let markdownMessages = [
    ChatMessage(
      id: "markdown-assistant", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B",
      text: """
        ## Release check

        The **important details** now render cleanly.

        1. Open the pull request.
        2. Verify `main` before release.

        | Item | Status |
        | :--- | ---: |
        | Credentials | Protected |
        """,
      createdAt: "2026-09-12T12:03:00.000Z", status: "complete")
  ]
}

public enum InvitationParser {
  public static func parse(_ url: URL) -> PendingInvitation? {
    let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
    let queryKind = query.first { $0.name == "kind" }?.value
    let queryToken = query.first { $0.name == "token" }?.value
    if let kind = queryKind, let token = queryToken, validKinds.contains(kind), !token.isEmpty {
      return PendingInvitation(kind: kind, token: token)
    }
    let path = url.pathComponents.filter { $0 != "/" }
    if let index = path.firstIndex(where: { ["share", "group", "skill"].contains($0) }),
      path.count > index + 1
    {
      let segment = path[index]
      return PendingInvitation(kind: segment == "share" ? "bot" : segment, token: path[index + 1])
    }
    if let host = url.host, ["share", "group", "skill"].contains(host), let token = path.first {
      return PendingInvitation(kind: host == "share" ? "bot" : host, token: token)
    }
    return nil
  }
  private static let validKinds: Set<String> = ["bot", "chat", "group", "skill"]
}
