import Foundation
import XCTest
@testable import HeyTimApple

@MainActor final class AppleDeviceToolTests: XCTestCase {
  private var coordinators: [AppleDeviceToolCoordinator] = []
  private var fixtureSession: URLSession?
  private var fixtureDefaults: (UserDefaults, String)?

  override func tearDown() async throws {
    for coordinator in coordinators { await coordinator.disconnectAndWait() }
    fixtureSession?.invalidateAndCancel()
    DeviceToolURLProtocol.handler = nil
    if let (defaults, suite) = fixtureDefaults { defaults.removePersistentDomain(forName: suite) }
    try await super.tearDown()
  }

  func testTerminalOutputStaysInMemoryAndRestartDoesNotReplayAnUnuploadedCommand() async throws {
    let suite = "AppleDeviceToolTests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
    fixtureDefaults = (defaults, suite)
    let firstUpload = expectation(description: "Terminal result upload failed")
    let restoredUpload = expectation(description: "Restored replay-prevention result uploaded")
    let transcript = "private-terminal-transcript-\(UUID().uuidString)"
    let call = DeviceCall(
      id: String(repeating: "a", count: 64), turnId: "turn-1", botId: "bot-1",
      botName: "Fixture bot", toolId: "mac_terminal",
      operation: "mac_terminal_execute_command",
      arguments: ["sessionId": .string("fixture-session"), "revision": .string("fixture-revision"),
        "command": .string("printf fixture")],
      requestDigest: String(repeating: "b", count: 64),
      expiresAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(300)))
    let fixture = DeviceToolHTTPFixture(
      call: call, firstUpload: firstUpload, restoredUpload: restoredUpload)
    DeviceToolURLProtocol.handler = { try fixture.handle($0) }
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [DeviceToolURLProtocol.self]
    let session = URLSession(configuration: configuration)
    fixtureSession = session
    let api = HeyTimAPI(baseURL: URL(string: "https://example.invalid")!, session: session) {
      "fixture-token"
    }
    let registration = DeviceCapabilityRegistration(
      platform: "macos", appVersion: "fixture", tools: [
        DeviceToolCapability(id: "mac_terminal", operations: [call.operation])
      ], botGrants: [DeviceBotGrant(botId: call.botId, toolIds: ["mac_terminal"])])
    let executions = DeviceExecutionCount()
    let coordinator = AppleDeviceToolCoordinator(defaults: defaults)
    coordinators.append(coordinator)
    coordinator.connect(api: api, registration: { registration }) { _ in
      executions.value += 1
      return .success(.object(["submitted": .bool(true), "contents": .string(transcript)]))
    }
    await fulfillment(of: [firstUpload], timeout: 3)
    try await waitUntil { coordinator.lastError != nil }
    XCTAssertEqual(executions.value, 1)
    let saved = try XCTUnwrap(defaults.data(forKey: "heytim.device-tools.completed-results"))
    XCTAssertFalse(String(decoding: saved, as: UTF8.self).contains(transcript))
    let cache = try XCTUnwrap(JSONSerialization.jsonObject(with: saved) as? [String: [String: Any]])
    let claim = try XCTUnwrap(cache[call.id])
    XCTAssertNil(claim["result"])
    XCTAssertTrue((claim["error"] as? String)?.contains("did not replay") == true)
    await coordinator.disconnectAndWait()
    XCTAssertEqual(fixture.unregistrations, 1)

    let restored = AppleDeviceToolCoordinator(defaults: defaults)
    coordinators.append(restored)
    XCTAssertEqual(restored.deviceID, coordinator.deviceID)
    restored.connect(api: api, registration: { registration }) { _ in
      executions.value += 1
      XCTFail("A restored pending command must not execute again")
      return .failure("Unexpected replay")
    }
    await fulfillment(of: [restoredUpload], timeout: 3)
    XCTAssertEqual(executions.value, 1)
    let uploads = fixture.uploads
    XCTAssertEqual(uploads.count, 2)
    let original = try XCTUnwrap(JSONSerialization.jsonObject(with: uploads[0]) as? [String: Any])
    XCTAssertEqual(original["status"] as? String, "success")
    XCTAssertEqual((original["result"] as? [String: Any])?["contents"] as? String, transcript)
    let replayPrevention = try XCTUnwrap(JSONSerialization.jsonObject(with: uploads[1]) as? [String: Any])
    XCTAssertEqual(replayPrevention["status"] as? String, "error")
    XCTAssertNil(replayPrevention["result"])
    XCTAssertTrue((replayPrevention["error"] as? String)?.contains("did not replay") == true)
    XCTAssertFalse(String(decoding: uploads[1], as: UTF8.self).contains(transcript))
    await restored.disconnectAndWait()
    XCTAssertEqual(fixture.unregistrations, 2)
  }

  private func waitUntil(_ condition: @MainActor () -> Bool) async throws {
    let deadline = Date().addingTimeInterval(3)
    while !condition(), Date() < deadline {
      try await Task.sleep(for: .milliseconds(10))
    }
    XCTAssertTrue(condition(), "The device poll did not finish its expected state transition")
  }
}

@MainActor private final class DeviceExecutionCount {
  var value = 0
}

private final class DeviceToolHTTPFixture: @unchecked Sendable {
  private let lock = NSLock()
  private let call: DeviceCall
  private let firstUpload: XCTestExpectation
  private let restoredUpload: XCTestExpectation
  private var storedUploads: [Data] = []
  private var storedUnregistrations = 0

  init(call: DeviceCall, firstUpload: XCTestExpectation, restoredUpload: XCTestExpectation) {
    self.call = call
    self.firstUpload = firstUpload
    self.restoredUpload = restoredUpload
  }

  var uploads: [Data] { lock.withLock { storedUploads } }
  var unregistrations: Int { lock.withLock { storedUnregistrations } }

  func handle(_ request: URLRequest) throws -> (Int, Data) {
    XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fixture-token")
    if request.httpMethod == "PUT", request.url?.path.hasSuffix("/capabilities") == true {
      let deviceID = request.url!.pathComponents.dropLast().last!
      return (200, try JSONSerialization.data(withJSONObject: [
        "registered": true, "deviceId": deviceID, "leaseExpiresAt": 4_000_000_000
      ]))
    }
    if request.httpMethod == "DELETE" {
      lock.withLock { storedUnregistrations += 1 }
      return (200, Data("{}".utf8))
    }
    if request.httpMethod == "GET", request.url?.path.hasSuffix("/calls") == true {
      return (200, try JSONEncoder().encode(DeviceCallPage(calls: [call])))
    }
    guard request.httpMethod == "POST", request.url?.path.hasSuffix("/result") == true else {
      XCTFail("Unexpected device request: \(request.httpMethod ?? "") \(request.url?.path ?? "")")
      throw URLError(.badURL)
    }
    let body = try Self.body(request)
    let count = lock.withLock {
      storedUploads.append(body)
      return storedUploads.count
    }
    if count == 1 {
      firstUpload.fulfill()
      throw URLError(.networkConnectionLost)
    }
    restoredUpload.fulfill()
    return (202, try JSONSerialization.data(withJSONObject: ["accepted": true, "turnId": call.turnId]))
  }

  private static func body(_ request: URLRequest) throws -> Data {
    if let data = request.httpBody { return data }
    guard let stream = request.httpBodyStream else { return Data() }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
      let count = stream.read(&buffer, maxLength: buffer.count)
      if count <= 0 { break }
      data.append(buffer, count: count)
    }
    return data
  }
}

private final class DeviceToolURLProtocol: URLProtocol, @unchecked Sendable {
  nonisolated(unsafe) static var handler: ((URLRequest) throws -> (Int, Data))?
  override class func canInit(with request: URLRequest) -> Bool { true }
  override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
  override func startLoading() {
    do {
      guard let handler = Self.handler else { throw URLError(.badServerResponse) }
      let (status, data) = try handler(request)
      let response = HTTPURLResponse(url: request.url!, statusCode: status,
        httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
      client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
      client?.urlProtocol(self, didLoad: data)
      client?.urlProtocolDidFinishLoading(self)
    } catch { client?.urlProtocol(self, didFailWithError: error) }
  }
  override func stopLoading() {}
}
