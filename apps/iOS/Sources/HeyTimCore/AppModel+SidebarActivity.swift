import Foundation

@MainActor
extension AppModel {
  public var sidebarActiveSelections: Set<ConversationSelection> {
    var active = Set<ConversationSelection>()
    if let bootstrap {
      for bot in bootstrap.bots where bot.processing == true {
        active.insert(.init(kind: .bot, id: bot.id))
      }
      for group in bootstrap.groups where group.processing == true {
        active.insert(.init(kind: .group, id: group.id))
      }
    }
    if let selection, loadedMessagesSelection == selection {
      active.remove(selection)
      if messages.contains(where: \.isActive) { active.insert(selection) }
    }
    if let sendingSelection { active.insert(sendingSelection) }
    return active
  }

  func sessionIsCurrent(_ generation: UInt, api: HeyTimAPI) -> Bool {
    sessionGeneration == generation && self.api === api
  }

  func conversationExists(_ value: ConversationSelection) -> Bool {
    switch value.kind {
    case .bot: bootstrap?.bots.contains(where: { $0.id == value.id }) == true
    case .group: bootstrap?.groups.contains(where: { $0.id == value.id }) == true
    }
  }

  func markListedProcessing(
    _ target: ConversationSelection, name: String? = nil, active: Bool
  ) {
    guard var bootstrap else { return }
    switch target.kind {
    case .bot:
      guard let index = bootstrap.bots.firstIndex(where: { $0.id == target.id }) else { return }
      bootstrap.bots[index].processing = active
    case .group:
      guard let index = bootstrap.groups.firstIndex(where: { $0.id == target.id }) else { return }
      bootstrap.groups[index].processing = active
      bootstrap.groups[index].processingBotName = active ? name : nil
    }
    self.bootstrap = bootstrap
  }

  func configureSidebarPolling() {
    let hasBackgroundActivity = sidebarActiveSelections.contains { $0 != selection }
    guard !demoMode, let api, hasBackgroundActivity else {
      sidebarPollTask?.cancel()
      sidebarPollTask = nil
      return
    }
    guard sidebarPollTask == nil else { return }
    let requestedSession = sessionGeneration
    sidebarPollTask = Task { [weak self] in
      while !Task.isCancelled {
        do { try await Task.sleep(for: .seconds(5)) } catch { return }
        guard let self, self.sessionIsCurrent(requestedSession, api: api) else { return }
        if let value = try? await api.bootstrap(),
          self.sessionIsCurrent(requestedSession, api: api), !Task.isCancelled
        {
          self.bootstrap = value
          self.configureSidebarPolling()
        }
      }
    }
  }
}
