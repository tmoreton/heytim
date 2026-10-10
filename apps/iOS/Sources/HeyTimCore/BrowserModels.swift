import Foundation

public struct BrowserState: Codable, Equatable, Sendable {
  public var botId: String
  public var groupId: String?
  public var status: String
  public var contextLabel: String
  public var hasSavedLogin: Bool
  public var blocksSending: Bool?
  public var profileSavePending: Bool?
  public var display: String?
  public var viewport: BrowserViewport?
  public var mobileSiteSupported: Bool?
  public var recoveryRequired: Bool?
  public var sessionExpiresAt: String?
  public var liveViewUrl: String?
  public var liveViewExpiresAt: String?
  public var resumedTurnId: String?

  public var requiresHandoff: Bool {
    // Older servers did not return blocksSending. An expired display state can
    // still hide stored human control, so require explicit recovery in that case.
    blocksSending ?? ["human_control", "opening", "resuming", "expired"].contains(status)
  }
}

enum BrowserResumeError: LocalizedError {
  case busy, stillSaving, unconfirmed

  var errorDescription: String? {
    switch self {
    case .busy: "Wait for the current browser operation to finish."
    case .stillSaving:
      "Your login is still being saved. Choose Continue Saving Login to check again. The bot has not resumed."
    case .unconfirmed:
      "The browser handoff has not been confirmed. Check the conversation and browser status before trying again."
    }
  }
}

public struct BrowserViewport: Codable, Equatable, Sendable {
  public var width: Int
  public var height: Int
}
