import Foundation

extension AppModel {
  #if DEBUG
    func configureBrowserDemo(arguments: [String]) {
      if arguments.contains("--ui-testing-browser-expired"), let bot = bootstrap?.bots.first {
        messages = []
        composerText = "Keep this draft"
        updateBrowserState(
          BrowserState(
            botId: bot.id, status: "expired", contextLabel: "Private direct chat",
            hasSavedLogin: true, blocksSending: true))
      }
      if arguments.contains("--ui-testing-browser-saving"), let bot = bootstrap?.bots.first {
        messages = []
        composerText = "Keep this draft"
        updateBrowserState(
          BrowserState(botId: bot.id, status: "resuming", contextLabel: "Private direct chat",
            hasSavedLogin: false, blocksSending: true, profileSavePending: true,
            recoveryRequired: false))
      }
    }
  #endif

  public var browserBlocksSending: Bool {
    guard let selection else { return false }
    return browserBlocksSending(for: selection)
  }

  func browserBlocksSending(for selection: ConversationSelection) -> Bool {
    selection.kind == .bot
      && (blockedBrowserBotIDs.contains(selection.id)
        || busyBrowserBotIDs.contains(selection.id)
        || closingBrowserBotIDs.contains(selection.id)
        || browserStates[selection.id]?.requiresHandoff == true)
  }

  public func updateBrowserState(_ state: BrowserState) {
    guard state.groupId == nil else { return }
    var summary = state
    // The panel owns its short-lived viewer URL. Shared chat state needs only
    // the status, and a background GET must not replace an active viewer URL.
    summary.liveViewUrl = nil
    summary.liveViewExpiresAt = nil
    browserStates[state.botId] = summary
    browserStateRevisions[state.botId, default: 0] &+= 1
    if state.requiresHandoff {
      blockedBrowserBotIDs.insert(state.botId)
    } else {
      blockedBrowserBotIDs.remove(state.botId)
    }
  }

  @discardableResult public func refreshBrowserState(botId: String) async -> BrowserState? {
    try? await fetchBrowserState(botId: botId)
  }

  public func fetchBrowserState(botId: String) async throws -> BrowserState? {
    guard let api, !demoMode else { return browserStates[botId] }
    let session = sessionGeneration
    let revision = browserStateRevisions[botId, default: 0]
    let state = try await api.browserState(botId: botId)
    guard sessionIsCurrent(session, api: api), state.botId == botId, state.groupId == nil
    else { return nil }
    guard browserStateRevisions[botId, default: 0] == revision
    else { return nil }
    updateBrowserState(state)
    return state
  }

  func beginBrowserOperation(botId: String) -> Bool {
    guard !busyBrowserBotIDs.contains(botId), !closingBrowserBotIDs.contains(botId)
    else { return false }
    busyBrowserBotIDs.insert(botId)
    browserStateRevisions[botId, default: 0] &+= 1
    return true
  }

  /// Poll only an explicitly confirmed profile save, never an uncertain enqueue.
  @discardableResult func resumeBrowserHandoff(
    botId: String, rememberLogin: Bool,
    maximumPolls: Int = 10,
    pause: () async throws -> Void = { try await Task.sleep(for: .seconds(2)) }
  ) async throws -> BrowserState {
    guard let api else { throw APIError.configuration("Sign in to resume the browser.") }
    guard beginBrowserOperation(botId: botId) else { throw BrowserResumeError.busy }
    let session = sessionGeneration
    defer {
      if sessionGeneration == session { busyBrowserBotIDs.remove(botId) }
    }
    for attempt in 0...max(0, maximumPolls) {
      try Task.checkCancellation()
      guard sessionIsCurrent(session, api: api) else { throw CancellationError() }
      let value = try await api.resumeBrowser(botId: botId, rememberLogin: rememberLogin)
      guard sessionIsCurrent(session, api: api) else { throw CancellationError() }
      guard value.botId == botId, value.groupId == nil else { throw APIError.invalidResponse }
      updateBrowserState(value)
      if value.status == "ready", value.resumedTurnId?.isEmpty == false,
        !value.requiresHandoff {
        return value
      }
      guard rememberLogin, value.status == "resuming", value.profileSavePending == true
      else { throw BrowserResumeError.unconfirmed }
      guard attempt < maximumPolls else { throw BrowserResumeError.stillSaving }
      try await pause()
    }
    throw BrowserResumeError.stillSaving
  }

  @discardableResult public func endBrowserHandoff(botId: String) async -> Bool {
    guard !closingBrowserBotIDs.contains(botId), !busyBrowserBotIDs.contains(botId)
    else { return false }
    closingBrowserBotIDs.insert(botId)
    browserStateRevisions[botId, default: 0] &+= 1
    let session = sessionGeneration
    defer {
      if sessionGeneration == session { closingBrowserBotIDs.remove(botId) }
    }
    if demoMode {
      if var state = browserStates[botId] {
        state.status = "closed"
        state.blocksSending = false
        state.recoveryRequired = false
        updateBrowserState(state)
      }
      return true
    }
    guard let api else { return false }
    do {
      let state = try await api.closeBrowser(botId: botId)
      guard sessionIsCurrent(session, api: api) else { return false }
      guard state.botId == botId, state.groupId == nil else { throw APIError.invalidResponse }
      updateBrowserState(state)
      return !state.requiresHandoff
    } catch {
      if sessionIsCurrent(session, api: api) { present(error) }
      return false
    }
  }

  func isBrowserHandoffError(_ error: Error) -> Bool {
    guard case APIError.requestFailed(let status, let code, let message) = error,
      status == 409
    else { return false }
    return code == "browser_handoff_incomplete"
      // Compatibility while the client and backend roll out independently.
      || (code == "browser_error"
        && message
          == "Finish the browser handoff with Resume or Close before sending another message")
  }
}
