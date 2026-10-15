import Foundation

@MainActor
extension AppModel {
  /// Refreshes an idle conversation without changing navigation or the composer.
  @discardableResult public func refreshForegroundConversation() async throws -> Bool {
    guard !demoMode, api != nil, foregroundRefreshOwner == nil,
      !isLoading, !isLoadingMessages, !isSending, !isUploading,
      let selection, loadedMessagesSelection == nil || loadedMessagesSelection == selection,
      !messages.contains(where: \.isActive),
      !Task.isCancelled else { return false }
    let owner = UUID()
    foregroundRefreshOwner = owner
    defer {
      if foregroundRefreshOwner == owner { foregroundRefreshOwner = nil }
    }
    return try await loadMessages(passiveRefresh: true)
  }

  /// The view owns this task so backgrounding or signing out cancels discovery.
  /// Already-active replies retain their existing faster polling loop.
  public func synchronizeForegroundConversation() async {
    guard !demoMode, let api else { return }
    let requestedSession = sessionGeneration
    var failures = 0
    while !Task.isCancelled, sessionIsCurrent(requestedSession, api: api) {
      do {
        _ = try await refreshForegroundConversation()
        failures = 0
      } catch {
        failures = min(failures + 1, 30)
      }
      guard !Task.isCancelled, sessionIsCurrent(requestedSession, api: api) else { return }
      let delay = Self.nextPollingDelay(base: 5_000, failures: failures)
      do { try await Task.sleep(for: .milliseconds(delay)) } catch { return }
    }
  }
}
