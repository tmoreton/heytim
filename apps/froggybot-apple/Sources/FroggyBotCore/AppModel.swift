import Foundation
import Observation
import OSLog

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
  private static let pushLogger = Logger(subsystem: "com.frogbot.app", category: "push")
  public var bootstrap: Bootstrap?
  public var selection: ConversationSelection?
  public var messages: [ChatMessage] = []
  public var nextToken: String?
  public var isLoading = false
  public var isSending = false
  public var errorMessage: String?
  public var sheet: AppSheet?
  public var pendingAttachments: [Attachment] = []
  public var composerText = ""
  public var groupReplyBotId: String? = "all"
  public var lastSharedURL: URL?
  public var deepLinkInvite: (kind: String, token: String)?

  @ObservationIgnored var api: FrogBotAPI?
  @ObservationIgnored private var pollTask: Task<Void, Never>?
  @ObservationIgnored private var demoMode: Bool
  @ObservationIgnored private var pushToken: Data?

  public init(api: FrogBotAPI? = nil, demoMode: Bool = false) {
    self.api = api
    self.demoMode = demoMode
    if demoMode {
      bootstrap = DemoData.bootstrap
      selection = .init(kind: .bot, id: DemoData.bootstrap.bots[0].id)
      messages = DemoData.messages
    }
  }

  deinit { pollTask?.cancel() }

  public func connect(_ api: FrogBotAPI) { self.api = api }

  public var selectedBot: Bot? {
    guard selection?.kind == .bot else { return nil }
    return bootstrap?.bots.first { $0.id == selection?.id }
  }
  public var selectedGroup: BotGroup? {
    guard selection?.kind == .group else { return nil }
    return bootstrap?.groups.first { $0.id == selection?.id }
  }
  public var title: String { selectedBot?.name ?? selectedGroup?.name ?? "FroggyBot" }
  public var subtitle: String {
    selectedBot?.tagline ?? selectedGroup.map {
      "\($0.bots.count) bots · \($0.members.count) people"
    } ?? ""
  }
  public var canStop: Bool {
    selectedBot != nil
      && messages.last(where: { !$0.isUser })?.allowedActions?.contains("cancel") == true
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
    isLoading = true
    defer { isLoading = false }
    do {
      let value = try await api.bootstrap()
      bootstrap = value
      chooseAvailableSelection()
      try await loadMessages()
      if value.needsBotOnboarding { sheet = .botLibrary }
    } catch { present(error) }
  }

  public func refreshBootstrap() async {
    guard !demoMode, let api else { return }
    do {
      bootstrap = try await api.bootstrap()
      chooseAvailableSelection()
    } catch { present(error) }
  }

  public func select(_ value: ConversationSelection) {
    guard value != selection else { return }
    selection = value
    messages = []
    nextToken = nil
    pendingAttachments = []
    pollTask?.cancel()
    Task { try? await loadMessages() }
  }

  public func loadMessages() async throws {
    guard let selection else { return }
    if demoMode { return }
    guard let api else { throw APIError.configuration("The service is not connected.") }
    let page =
      selection.kind == .bot
      ? try await api.messages(bot: selection.id)
      : try await api.messages(group: selection.id)
    messages = Self.mergeLatest(current: messages, latest: page.messages)
    nextToken = page.nextToken
    configurePolling()
  }

  public func loadEarlier() async {
    guard let selection, let cursor = nextToken, let api, !demoMode else { return }
    do {
      let page =
        selection.kind == .bot
        ? try await api.messages(bot: selection.id, cursor: cursor)
        : try await api.messages(group: selection.id, cursor: cursor)
      messages = Self.mergeEarlier(current: messages, earlier: page.messages)
      nextToken = page.nextToken
    } catch { present(error) }
  }

  public func send() async {
    let text = composerText.trimmingCharacters(in: .whitespacesAndNewlines)
    guard let selection, !text.isEmpty || !pendingAttachments.isEmpty, !isSending else { return }
    let attachmentIds = pendingAttachments.map(\.id)
    composerText = ""
    pendingAttachments = []
    isSending = true
    defer { isSending = false }
    if demoMode {
      let now = ISO8601DateFormatter().string(from: Date())
      messages.append(
        ChatMessage(
          id: UUID().uuidString, role: "user", text: text, createdAt: now, status: "complete"))
      messages.append(
        ChatMessage(
          id: UUID().uuidString, role: "assistant", authorName: selectedBot?.name ?? "FroggyBot",
          text: "This is the native app’s offline test reply.", createdAt: now, status: "complete"))
      return
    }
    guard let api else { return }
    do {
      if selection.kind == .bot {
        try await api.sendMessage(bot: selection.id, text: text, attachments: attachmentIds)
      } else {
        try await api.sendMessage(
          group: selection.id, text: text, replyBotId: activeGroupReplyBotId,
          attachments: attachmentIds)
      }
      try await loadMessages()
    } catch {
      composerText = text
      present(error)
    }
  }

  public func stop() async {
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
    guard let bot = selectedBot, let api, !demoMode else { return }
    do {
      try await api.approve(botId: bot.id, turnId: Self.directTurnID(message.id), always: always)
      try await loadMessages()
      if always { await refreshBootstrap() }
    } catch { present(error) }
  }

  public func reject(_ message: ChatMessage) async {
    guard let bot = selectedBot, let api, !demoMode else { return }
    do {
      try await api.cancel(botId: bot.id, turnId: Self.directTurnID(message.id))
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

  public func registerPush(_ token: Data, platform: String) async {
    pushToken = token
    guard let api, !demoMode else { return }
    do {
      try await api.registerAPNsToken(token, platform: platform)
    } catch {
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
    } catch {
      Self.pushLogger.error(
        "Push unregistration failed: \(error.localizedDescription, privacy: .public)")
    }
  }

  public func upload(urls: [URL]) async {
    guard let api, !demoMode else { return }
    isSending = true
    defer { isSending = false }
    for url in urls {
      let scoped = url.startAccessingSecurityScopedResource()
      defer { if scoped { url.stopAccessingSecurityScopedResource() } }
      do { pendingAttachments.append(try await api.upload(try UploadAsset(url: url))) } catch {
        present(error)
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
    guard let selection, let api, !demoMode else { return }
    do {
      if selection.kind == .bot {
        try await api.deleteBot(selection.id)
      } else {
        try await api.deleteGroup(selection.id)
      }
      self.selection = nil
      messages = []
      await refreshBootstrap()
      try await loadMessages()
    } catch { present(error) }
  }
  public func clearCurrent(forgetMemory: Bool) async {
    guard let bot = selectedBot, let api, !demoMode else { return }
    do {
      try await api.clearBot(bot.id, forgetMemory: forgetMemory)
      messages = []
    } catch { present(error) }
  }

  public func shareCurrent() async {
    guard let selection, let api, !demoMode else { return }
    do {
      lastSharedURL =
        selection.kind == .bot
        ? try await api.share(botId: selection.id, scope: "chat")
        : try await api.shareGroup(selection.id)
    } catch { present(error) }
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

  private func chooseAvailableSelection() {
    guard let bootstrap else {
      selection = nil
      return
    }
    if let value = selection {
      if value.kind == .bot, bootstrap.bots.contains(where: { $0.id == value.id }) { return }
      if value.kind == .group, bootstrap.groups.contains(where: { $0.id == value.id }) { return }
    }
    if let group = bootstrap.groups.first {
      selection = .init(kind: .group, id: group.id)
    } else if let bot = bootstrap.bots.first {
      selection = .init(kind: .bot, id: bot.id)
    } else {
      selection = nil
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

  public static func nextPollingDelay(base: Int, failures: Int, random: Double = 0.5) -> Int {
    guard failures > 0 else { return base }
    let bounded = min(30_000, base * Int(pow(2.0, Double(failures))))
    let jitter = 0.8 + min(1, max(0, random)) * 0.4
    return min(30_000, Int((Double(bounded) * jitter).rounded()))
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
  public static let bootstrap = Bootstrap(
    bots: [
      Bot(
        id: "chief", name: "Chief", tagline: "Your capable AI chief of staff", color: "#59B86B",
        prompt: "Help thoughtfully.", toolIds: [], skillIds: [],
        createdAt: "2026-09-12T12:00:00.000Z", updatedAt: "2026-09-12T12:00:00.000Z",
        lastMessage: "Your project brief is ready.", lastMessageAt: "2026-09-12T12:01:00.000Z")
    ],
    botTemplates: [], connectionProviders: [], needsBotOnboarding: false, groups: [], tools: [],
    retiredToolIds: [], skills: [], constraints: constraints
  )
  public static let messages = [
    ChatMessage(
      id: "m1", role: "user", authorName: "You", isMine: true,
      text: "Can you summarize the launch plan?", createdAt: "2026-09-12T12:00:00.000Z",
      status: "complete"),
    ChatMessage(
      id: "m2", role: "assistant", authorType: "bot", authorId: "chief", authorName: "Chief",
      authorColor: "#59B86B",
      text:
        "Absolutely. The native SwiftUI client is sharing the same backend and API contract across iPhone and Mac.\n\n- Authentication and data stay in AWS.\n- Conversations and background tasks are preserved.\n- The existing web app remains available.",
      createdAt: "2026-09-12T12:01:00.000Z", status: "complete"),
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
