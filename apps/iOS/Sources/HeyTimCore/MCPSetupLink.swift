import Foundation

public struct MCPSetupLink: Equatable, Sendable {
  public var name: String
  public var endpoint: String

  public init?(url: URL) {
    guard url.scheme == "heytim", url.host == "connect-mcp",
      url.user == nil, url.password == nil, url.port == nil,
      url.fragment == nil, url.path.isEmpty,
      let parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
    else { return nil }
    let items = parts.queryItems ?? []
    guard items.count <= 2, Set(items.map(\.name)).count == items.count,
      items.allSatisfy({ ["name", "url"].contains($0.name) }) else { return nil }
    let name = items.first(where: { $0.name == "name" })?.value ?? "MCP server"
    let endpoint = items.first(where: { $0.name == "url" })?.value ?? ""
    guard !name.isEmpty, name.count <= 80, endpoint.count <= 500 else { return nil }
    if !endpoint.isEmpty {
      guard let value = URLComponents(string: endpoint), value.scheme == "https",
        value.host != nil, value.user == nil, value.password == nil,
        value.query == nil, value.fragment == nil, value.port == nil || value.port == 443
      else { return nil }
    }
    self.name = name
    self.endpoint = endpoint
  }
}
