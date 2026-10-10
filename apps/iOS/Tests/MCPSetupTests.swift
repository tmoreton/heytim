import Foundation
import XCTest
@testable import HeyTimApple

final class MCPSetupTests: XCTestCase {
  func testSetupLinkOnlyOpensAFormAndPreservesEndpoint() throws {
    let url = try XCTUnwrap(URL(string:
      "heytim://connect-mcp?name=Home%20Assistant&url=https%3A%2F%2Fhome.example.com%2Fapi%2Fmcp%2Fassist"))
    let setup = try XCTUnwrap(MCPSetupLink(url: url))
    XCTAssertEqual(setup.name, "Home Assistant")
    XCTAssertEqual(setup.endpoint, "https://home.example.com/api/mcp/assist")
  }

  func testSetupLinkRejectsCredentialsUnknownFieldsAndOtherSchemes() throws {
    for value in [
      "https://connect-mcp?name=Test", "heytim://connect-mcp?token=secret",
      "heytim://connect-mcp?name=A&name=B", "heytim://connect-mcp?url=https%3A%2F%2Ftoken%40example.com%2Fmcp",
      "heytim://connect-mcp?url=https%3A%2F%2Fexample.com%2Fmcp%3Ftoken%3Dsecret"
    ] {
      XCTAssertNil(MCPSetupLink(url: try XCTUnwrap(URL(string: value))), value)
    }
  }

  func testDiscoveryDecodesServerAndReviewableTools() throws {
    let data = Data("""
      {"serverName":"Home Assistant","serverVersion":"1","protocolVersion":"2025-11-25",
       "tools":[{"name":"read_state","description":"Read state","digest":"abc"}]}
      """.utf8)
    let discovery = try JSONDecoder().decode(MCPDiscovery.self, from: data)
    XCTAssertEqual(discovery.tools.first?.name, "read_state")
    XCTAssertEqual(discovery.tools.first?.digest, "abc")
  }
}
