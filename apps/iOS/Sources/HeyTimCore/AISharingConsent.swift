import Foundation

public struct AISharingConsent: Codable, Equatable, Sendable {
  public var version: Int
  public var granted: Bool
  public var reviewed: Bool

  public init(version: Int = 1, granted: Bool = false, reviewed: Bool = false) {
    self.version = version
    self.granted = granted
    self.reviewed = reviewed
  }

  private enum CodingKeys: String, CodingKey { case version, granted, reviewed }

  public init(from decoder: Decoder) throws {
    let values = try decoder.container(keyedBy: CodingKeys.self)
    version = try values.decode(Int.self, forKey: .version)
    granted = try values.decode(Bool.self, forKey: .granted)
    reviewed = try values.decodeIfPresent(Bool.self, forKey: .reviewed) ?? granted
  }

  public func encode(to encoder: Encoder) throws {
    // The grant endpoint accepts only version and granted. Review status is
    // server-owned and is included only in bootstrap and mutation responses.
    var values = encoder.container(keyedBy: CodingKeys.self)
    try values.encode(version, forKey: .version)
    try values.encode(granted, forKey: .granted)
  }
}
