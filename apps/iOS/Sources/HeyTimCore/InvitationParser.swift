import Foundation

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
