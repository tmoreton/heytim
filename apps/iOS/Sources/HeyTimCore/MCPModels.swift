import Foundation

public struct MCPDiscoveredTool: Codable, Identifiable, Hashable, Sendable {
  public var name: String
  public var description: String
  public var digest: String
  public var id: String { name }
}

public struct MCPDiscovery: Codable, Equatable, Sendable {
  public var serverName: String
  public var serverVersion: String
  public var protocolVersion: String
  public var tools: [MCPDiscoveredTool]
}

private struct MCPDiscoveryRequest: Encodable, Sendable {
  var url: String
  var accessToken: String?
}

private struct MCPConnectRequest: Encodable, Sendable {
  var name: String
  var url: String
  var authType: String
  var accessToken: String?
  var approvedTools: [String: String]
}

extension HeyTimAPI {
  public func discoverMCPServer(url: String, accessToken: String?) async throws -> MCPDiscovery {
    try await request(.mcpServerDiscover, body: MCPDiscoveryRequest(url: url, accessToken: accessToken))
  }

  public func connectReviewedMCPServer(
    name: String, url: String, accessToken: String?, approvedTools: [String: String]
  ) async throws -> Capability {
    try await request(.mcpServerConnect, body: MCPConnectRequest(
      name: name, url: url, authType: accessToken == nil ? "none" : "bearer_token",
      accessToken: accessToken, approvedTools: approvedTools))
  }
}
