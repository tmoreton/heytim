import Foundation

public struct BrowserState: Codable, Equatable, Sendable {
  public var botId: String
  public var groupId: String?
  public var status: String
  public var contextLabel: String
  public var hasSavedLogin: Bool
  public var blocksSending: Bool?
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

public struct BrowserViewport: Codable, Equatable, Sendable {
  public var width: Int
  public var height: Int
}
