#if os(macOS)
  import Foundation
  import XCTest
  @testable import HeyTimApple

  private actor TerminalFixture: MacTerminalServing {
    private var sessions: [MacTerminalSession]
    private var commands: [String] = []
    private var submitWaiter: CheckedContinuation<Void, Never>?
    private var isSubmitting = false
    private var suspendSubmission = false
    private var readHook: (@Sendable () async -> Void)?

    init(_ sessions: [MacTerminalSession]) { self.sessions = sessions }
    func listSessions() async throws -> [MacTerminalSession] { sessions }
    func readSession(id: String) async throws -> MacTerminalSession {
      if let readHook { await readHook() }
      guard let session = sessions.first(where: { $0.id == id }) else {
        throw NSError(domain: "TerminalFixture", code: 1)
      }
      return session
    }
    func submit(command: String, to session: MacTerminalSession) async throws {
      isSubmitting = true
      submitWaiter?.resume()
      submitWaiter = nil
      if suspendSubmission { try await Task.sleep(for: .seconds(10)) }
      try Task.checkCancellation()
      commands.append(command)
    }
    func update(_ session: MacTerminalSession) { sessions = [session] }
    func setSuspendSubmission() { suspendSubmission = true }
    func setReadHook(_ hook: @escaping @Sendable () async -> Void) { readHook = hook }
    func submittedCommands() -> [String] { commands }
    func waitUntilSubmitting() async {
      if isSubmitting { return }
      await withCheckedContinuation { submitWaiter = $0 }
    }
  }

  @MainActor private final class TerminalClock {
    var date = Date(timeIntervalSince1970: 1_800_000_000)
  }

  @MainActor final class MacTerminalTests: XCTestCase {
    private var suite = ""
    private var defaults: UserDefaults!

    override func setUp() async throws {
      try await super.setUp()
      await MainActor.run {
        suite = "MacTerminalTests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)!
      }
    }

    override func tearDown() async throws {
      await MainActor.run {
        defaults.removePersistentDomain(forName: suite)
        defaults = nil
      }
      try await super.tearDown()
    }

    private func session(contents: String = "tim@home:~$ ", busy: Bool = true) -> MacTerminalSession {
      MacTerminalSession(processID: 101, windowID: 22, tty: "/dev/ttys004", title: "SSH home",
        busy: busy, processes: ["zsh", "ssh"], contents: contents)
    }

    private func call(_ operation: String, _ arguments: [String: JSONValue] = [:], botID: String = "bot-a") -> DeviceCall {
      DeviceCall(id: UUID().uuidString, turnId: "turn", botId: botID, botName: "Tim",
        toolId: "mac_terminal", operation: operation, arguments: arguments,
        requestDigest: "digest", expiresAt: "2099-01-01T00:00:00Z")
    }

    private func enabled(_ fixture: TerminalFixture, clock: TerminalClock? = nil) -> MacTerminalCoordinator {
      let coordinator = MacTerminalCoordinator(defaults: defaults, terminal: fixture,
        now: { clock?.date ?? Date() })
      coordinator.isEnabled = true
      coordinator.setEnabled(true, for: "bot-a")
      return coordinator
    }

    private func read(_ coordinator: MacTerminalCoordinator, _ session: MacTerminalSession) async throws -> String {
      let outcome = await coordinator.execute(call("mac_terminal_read_session", ["sessionId": .string(session.id)]))
      guard case .success(let result) = outcome else {
        XCTFail("Expected a readable Terminal session: \(outcome)")
        throw NSError(domain: "MacTerminalTests", code: 1)
      }
      return try XCTUnwrap(result.objectValue?["revision"]?.stringValue)
    }

    private func command(_ session: MacTerminalSession, revision: String, botID: String = "bot-a") -> DeviceCall {
      call("mac_terminal_execute_command", ["sessionId": .string(session.id),
        "revision": .string(revision), "command": .string("uname -a"), "waitSeconds": .number(0)], botID: botID)
    }

    func testAccessStartsDisabledAndRequiresSeparateBotGrant() async {
      let fixture = TerminalFixture([session()])
      let coordinator = MacTerminalCoordinator(defaults: defaults, terminal: fixture)
      XCTAssertFalse(coordinator.isEnabled)
      coordinator.setEnabled(true, for: "bot-a")
      XCTAssertFalse(coordinator.isEnabled(for: "bot-a"))
      if case .success = await coordinator.execute(call("mac_terminal_list_sessions")) { XCTFail("Disabled access ran") }
      coordinator.isEnabled = true
      XCTAssertTrue(coordinator.isEnabled(for: "bot-a"))
      XCTAssertFalse(coordinator.isEnabled(for: "bot-b"))
      let restored = MacTerminalCoordinator(defaults: defaults, terminal: fixture)
      XCTAssertTrue(restored.isEnabled(for: "bot-a"))
    }

    func testBusySSHSessionSubmitsInSameSessionWithoutClaimingSuccess() async throws {
      let observed = session()
      let fixture = TerminalFixture([observed])
      let coordinator = enabled(fixture)
      let revision = try await read(coordinator, observed)
      let outcome = await coordinator.execute(command(observed, revision: revision))
      guard case .success(let result) = outcome else { return XCTFail("SSH prompt should accept a command: \(outcome)") }
      XCTAssertEqual(result.objectValue?["submitted"], .bool(true))
      XCTAssertEqual(result.objectValue?["successVerified"], .bool(false))
      let commands = await fixture.submittedCommands()
      XCTAssertEqual(commands, ["uname -a"])
      if case .success = await coordinator.execute(command(observed, revision: revision)) {
        XCTFail("The command revision was reusable")
      }
    }

    func testRevisionsAreScopedToBotAndExpire() async throws {
      let observed = session()
      let fixture = TerminalFixture([observed])
      let clock = TerminalClock()
      let coordinator = enabled(fixture, clock: clock)
      coordinator.setEnabled(true, for: "bot-b")
      let revision = try await read(coordinator, observed)
      if case .success = await coordinator.execute(command(observed, revision: revision, botID: "bot-b")) {
        XCTFail("Another bot reused the observation")
      }
      clock.date.addTimeInterval(121)
      if case .success = await coordinator.execute(command(observed, revision: revision)) { XCTFail("Expired observation ran") }
      let commands = await fixture.submittedCommands()
      XCTAssertTrue(commands.isEmpty)
    }

    func testObservationExpiryIsRecheckedAfterAwaitedRead() async throws {
      let observed = session()
      let fixture = TerminalFixture([observed])
      let clock = TerminalClock()
      let coordinator = enabled(fixture, clock: clock)
      let revision = try await read(coordinator, observed)
      await fixture.setReadHook { await MainActor.run { clock.date.addTimeInterval(121) } }
      if case .success = await coordinator.execute(command(observed, revision: revision)) { XCTFail("Expired during read") }
      let commands = await fixture.submittedCommands()
      XCTAssertTrue(commands.isEmpty)
    }

    func testChangedTerminalStateAndPartialInputRejectSubmission() async throws {
      for changed in [session(contents: "tim@home:~$ partial"), session(busy: false)] {
        let observed = session()
        let fixture = TerminalFixture([observed])
        let coordinator = enabled(fixture)
        let revision = try await read(coordinator, observed)
        await fixture.update(changed)
        if case .success = await coordinator.execute(command(observed, revision: revision)) { XCTFail("Changed tab ran") }
        let commands = await fixture.submittedCommands()
        XCTAssertTrue(commands.isEmpty)
      }
      for text in ["tim@home:~$ unfinished", "tim@home:~$ rm file #", "Password:", "Enter passphrase for key:", "Are you sure you want to continue connecting (yes/no)?"] {
        let observed = session(contents: text)
        let fixture = TerminalFixture([observed])
        let coordinator = enabled(fixture)
        let revision = try await read(coordinator, observed)
        if case .success = await coordinator.execute(command(observed, revision: revision)) { XCTFail("Not a shell prompt: \(text)") }
      }
      var cat = session(contents: "tim@home:~$ cat #")
      cat.processes = ["zsh", "cat"]
      let fixture = TerminalFixture([cat])
      let coordinator = enabled(fixture)
      let revision = try await read(coordinator, cat)
      if case .success = await coordinator.execute(command(cat, revision: revision)) {
        XCTFail("A foreground cat process consumed the shell command")
      }
    }

    func testInvalidateObservationsCancelsQueuedSubmission() async throws {
      let observed = session()
      let fixture = TerminalFixture([observed])
      await fixture.setSuspendSubmission()
      let coordinator = enabled(fixture)
      let revision = try await read(coordinator, observed)
      let action = Task { await coordinator.execute(command(observed, revision: revision)) }
      await fixture.waitUntilSubmitting()
      coordinator.invalidateObservations()
      if case .success = await action.value { XCTFail("Invalidated submission ran") }
      let commands = await fixture.submittedCommands()
      XCTAssertTrue(commands.isEmpty)
    }

    func testRevokingBotDuringReadPreventsSubmission() async throws {
      let observed = session()
      let fixture = TerminalFixture([observed])
      let coordinator = enabled(fixture)
      let revision = try await read(coordinator, observed)
      await fixture.setReadHook { await MainActor.run { coordinator.setEnabled(false, for: "bot-a") } }
      if case .success = await coordinator.execute(command(observed, revision: revision)) { XCTFail("Revoked access ran") }
      let commands = await fixture.submittedCommands()
      XCTAssertTrue(commands.isEmpty)
    }

    func testCommandValidationAndAppleScriptEscaping() {
      for value in ["", "  ", "ls\npwd", "ls\rpwd", "echo\tsecret", "a\u{0}b", "a\u{7f}b", "a\u{2028}b", String(repeating: "a", count: 4_001)] {
        XCTAssertFalse(MacTerminalCoordinator.isValidCommand(value), value)
      }
      XCTAssertTrue(MacTerminalCoordinator.isValidCommand("printf '%s' \"$HOME\""))
      let literal = AppleTerminalService.appleScriptLiteral("\"\\\n\u{0}")
      XCTAssertTrue(literal.contains("\\\"\\\\"))
      XCTAssertTrue(literal.contains("character id 10"))
      XCTAssertTrue(literal.contains("character id 0"))
      XCTAssertFalse(literal.contains("\n"))
    }

    func testOutputIsBoundedByEncodedJSONBytesAndListingHidesContents() async throws {
      let observed = session(contents: String(repeating: "\u{0}", count: 20_000))
      let fixture = TerminalFixture([observed])
      let coordinator = enabled(fixture)
      let outcome = await coordinator.execute(call("mac_terminal_read_session", ["sessionId": .string(observed.id), "maxCharacters": .number(20_000)]))
      guard case .success(let result) = outcome else { return XCTFail("Could not read output") }
      XCTAssertLessThan(try JSONEncoder().encode(result).count, 64_000)
      XCTAssertEqual(result.objectValue?["truncated"], .bool(true))
      let list = await coordinator.execute(call("mac_terminal_list_sessions"))
      guard case .success(let listed) = list else { return XCTFail("Could not list sessions") }
      XCTAssertNil(listed.objectValue?["sessions"]?.arrayValue?.first?.objectValue?["contents"])
      let tail = MacTerminalCoordinator.boundedTail(String(repeating: "🖥", count: 20_000), characters: 20_000)
      XCTAssertLessThanOrEqual(try JSONEncoder().encode(tail).count, 40_000)
    }

    func testGeneratedAppleScriptsCompileWithoutExecutingTerminal() {
      let observed = session(contents: "hello\n\"quoted\" \\ prompt$ ")
      for source in [AppleTerminalService.sessionScript(),
        AppleTerminalService.sessionScript(windowID: observed.windowID, tty: observed.tty, includeContents: true),
        AppleTerminalService.submissionScript(command: "printf '%s' \"$HOME\"", session: observed)]
      {
        let script = NSAppleScript(source: source)
        var details: NSDictionary?
        XCTAssertTrue(script?.compileAndReturnError(&details) == true, "\(details ?? [:])")
      }
    }
  }
#endif
