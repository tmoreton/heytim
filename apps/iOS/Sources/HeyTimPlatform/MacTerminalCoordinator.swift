#if os(macOS)
  import AppKit
  import Foundation
  import Observation

  struct MacTerminalSession: Equatable, Sendable {
    var processID: Int32
    var windowID: Int
    var tty: String
    var title: String
    var busy: Bool
    var processes: [String]
    var contents: String

    var id: String { "terminal:\(processID):\(windowID):\(tty)" }

    func hasSameState(as other: MacTerminalSession) -> Bool {
      id == other.id && contents == other.contents && busy == other.busy
        && processes == other.processes
    }
  }

  protocol MacTerminalServing: Sendable {
    func listSessions() async throws -> [MacTerminalSession]
    func readSession(id: String, mayRequestConsent: Bool) async throws -> MacTerminalSession
    func submit(command: String, to session: MacTerminalSession) async throws
  }

  /// Uses the existing Terminal tab rather than creating a separate local shell.
  /// Apple Events are sent only in response to an authorized tool request.
  struct AppleTerminalService: MacTerminalServing {
    private static let executionLock = NSLock()
    var permission = MacTerminalPermissionPreflight()
    var processIDProvider: @Sendable () -> Int32? = { Self.runningProcessID() }
    var scriptRunner: @Sendable (String, Int32, Bool) throws -> [MacTerminalSession] = {
      try Self.run($0, processID: $1, commandRequested: $2)
    }

    func listSessions() async throws -> [MacTerminalSession] {
      try await Self.inBackground { [self] in
        guard let processID = processIDProvider() else { return [] }
        let sessions = try runAuthorizedScript(
          Self.sessionScript(), processID: processID, mayRequestConsent: true)
        guard processIDProvider() == processID else {
          throw MacTerminalError(message: "Terminal restarted. List its sessions again.")
        }
        return sessions
      }
    }

    func readSession(id: String, mayRequestConsent: Bool = true) async throws -> MacTerminalSession {
      try await Self.inBackground { [self] in
        let target = try Self.target(from: id)
        guard processIDProvider() == target.processID else {
          throw MacTerminalError(message: "That Terminal session is no longer running. List sessions again.")
        }
        let sessions = try runAuthorizedScript(
          Self.sessionScript(windowID: target.windowID, tty: target.tty, includeContents: true),
          processID: target.processID, mayRequestConsent: mayRequestConsent)
        guard processIDProvider() == target.processID,
          sessions.count == 1, let session = sessions.first, session.id == id
        else {
          throw MacTerminalError(message: "That Terminal tab closed or changed. List sessions again.")
        }
        return session
      }
    }

    func submit(command: String, to session: MacTerminalSession) async throws {
      try await Self.inBackground { [self] in
        guard processIDProvider() == session.processID else {
          throw MacTerminalError(message: "Terminal restarted. Read the session again before sending a command.")
        }
        // The script compares the observed state once more immediately before
        // submitting to the exact tab. It never falls back to a new window.
        _ = try runAuthorizedScript(Self.submissionScript(command: command, session: session),
          processID: session.processID, mayRequestConsent: false, commandRequested: true)
      }
    }

    private func runAuthorizedScript(
      _ source: String, processID: Int32, mayRequestConsent: Bool, commandRequested: Bool = false
    ) throws -> [MacTerminalSession] {
      Self.executionLock.lock()
      defer { Self.executionLock.unlock() }
      try Task.checkCancellation()
      guard processIDProvider() == processID else {
        throw MacTerminalError(message: "Terminal restarted before checking permission. List sessions again.")
      }
      try permission.authorize(processID: processID, mayRequestConsent: mayRequestConsent)
      try Task.checkCancellation()
      guard processIDProvider() == processID else {
        throw MacTerminalError(message: "Terminal restarted while checking permission. List sessions again.")
      }
      return try scriptRunner(source, processID, commandRequested)
    }

    private static func inBackground<Value: Sendable>(
      _ operation: @escaping @Sendable () throws -> Value
    ) async throws -> Value {
      let task = Task.detached(priority: .userInitiated, operation: operation)
      return try await withTaskCancellationHandler {
        try Task.checkCancellation()
        return try await task.value
      } onCancel: { task.cancel() }
    }

    private static func runningProcessID() -> Int32? {
      let processes = Set(NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.Terminal")
        .filter { !$0.isTerminated }.compactMap(MacApplicationProcess.resolve))
      return processes.count == 1 ? processes.first : nil
    }

    private static func target(from id: String) throws -> (processID: Int32, windowID: Int, tty: String) {
      let parts = id.split(separator: ":", maxSplits: 3, omittingEmptySubsequences: false)
      guard parts.count == 4, parts[0] == "terminal",
        let processID = Int32(parts[1]), processID > 0,
        let windowID = Int(parts[2]), windowID > 0,
        parts[3].hasPrefix("/dev/tty"), parts[3].count <= 96,
        !parts[3].unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
      else { throw MacTerminalError(message: "The Terminal session ID is invalid. List sessions again.") }
      return (processID, windowID, String(parts[3]))
    }

    private static func run(
      _ source: String, processID: Int32, commandRequested: Bool
    ) throws -> [MacTerminalSession] {
      try Task.checkCancellation()
      guard let script = NSAppleScript(source: source) else {
        throw MacTerminalError(message: "Hey Tim could not prepare the Terminal request.")
      }
      var details: NSDictionary?
      try Task.checkCancellation()
      let result = script.executeAndReturnError(&details)
      if let details {
        throw MacTerminalError(message: MacTerminalDiagnostics.message(
          code: details[NSAppleScript.errorNumber] as? Int ?? -1,
          stage: MacTerminalDiagnostics.stage(from: details), processID: processID,
          commandRequested: commandRequested))
      }
      var sessions: [MacTerminalSession] = []
      for index in 0..<min(result.numberOfItems, 64) {
        guard let row = result.atIndex(index + 1), row.numberOfItems == 6,
          let tty = row.atIndex(2)?.stringValue,
          let title = row.atIndex(3)?.stringValue,
          let contents = row.atIndex(6)?.stringValue
        else { throw MacTerminalError(message: "Terminal returned an unreadable session. Try listing sessions again.") }
        let processRows = row.atIndex(5)
        let processes = (0..<min(processRows?.numberOfItems ?? 0, 32)).compactMap {
          processRows?.atIndex($0 + 1)?.stringValue
        }
        sessions.append(MacTerminalSession(
          processID: processID, windowID: Int(row.atIndex(1)?.int32Value ?? 0),
          tty: tty, title: title, busy: row.atIndex(4)?.booleanValue ?? false,
          processes: processes, contents: contents))
      }
      return sessions
    }
  }

  @MainActor @Observable
  final class MacTerminalCoordinator {
    static let enabledKey = "heytim.mac-terminal.enabled"
    static let enabledBotIDsKey = "heytim.mac-terminal.bot-ids"

    private struct SessionObservation {
      var session: MacTerminalSession
      var botID: String
      var revision: String
      var capturedAt: Date
    }

    var isEnabled: Bool {
      didSet {
        defaults.set(isEnabled, forKey: Self.enabledKey)
        if !isEnabled { invalidateObservations() }
      }
    }
    var enabledBotIDs: Set<String> {
      didSet {
        defaults.set(enabledBotIDs.sorted(), forKey: Self.enabledBotIDsKey)
        observations = observations.filter { enabledBotIDs.contains($0.value.botID) }
        authorizationGeneration += 1
        for submission in submissions.values where !enabledBotIDs.contains(submission.botID) {
          submission.task.cancel()
        }
        for request in reads.values where !enabledBotIDs.contains(request.botID) { request.cancel() }
      }
    }

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let terminal: any MacTerminalServing
    @ObservationIgnored private let now: @MainActor @Sendable () -> Date
    @ObservationIgnored private var observations: [String: SessionObservation] = [:]
    @ObservationIgnored private var authorizationGeneration = 0
    @ObservationIgnored private var submissions: [UUID: (botID: String, task: Task<Void, Error>)] = [:]
    @ObservationIgnored private var reads: [UUID: (botID: String, cancel: @Sendable () -> Void)] = [:]

    init(
      defaults: UserDefaults = .standard,
      terminal: any MacTerminalServing = AppleTerminalService(),
      now: @escaping @MainActor @Sendable () -> Date = { Date() }
    ) {
      self.defaults = defaults
      self.terminal = terminal
      self.now = now
      isEnabled = defaults.bool(forKey: Self.enabledKey)
      enabledBotIDs = Set(defaults.stringArray(forKey: Self.enabledBotIDsKey) ?? [])
    }

    func setEnabled(_ enabled: Bool, for botID: String) {
      guard enabledBotIDs.contains(botID) != enabled else { return }
      if enabled { enabledBotIDs.insert(botID) }
      else { enabledBotIDs.remove(botID) }
    }

    func isEnabled(for botID: String) -> Bool { isEnabled && enabledBotIDs.contains(botID) }

    func invalidateObservations() {
      observations.removeAll()
      authorizationGeneration += 1
      for submission in submissions.values { submission.task.cancel() }
      for request in reads.values { request.cancel() }
    }

    func execute(_ call: DeviceCall) async -> DeviceCallOutcome {
      guard call.toolId == "mac_terminal", isEnabled(for: call.botId) else {
        return .failure("Mac terminal access is not enabled for this bot on this Mac.")
      }
      do {
        switch call.operation {
        case "mac_terminal_list_sessions":
          guard call.arguments.isEmpty else {
            return .failure("Listing Terminal sessions does not accept arguments.")
          }
          let terminal = terminal
          let sessions = try await terminalRead(botID: call.botId) { try await terminal.listSessions() }
          guard isEnabled(for: call.botId) else { return accessRevoked }
          try Task.checkCancellation()
          var rows: [JSONValue] = []
          for session in sessions.prefix(64) {
            let candidate = rows + [metadata(session)]
            guard Self.encodedSize(.array(candidate)) <= 48_000 else { break }
            rows = candidate
          }
          return .success(.object([
            "application": .string("Terminal"),
            "sessions": .array(rows),
            "truncated": .bool(rows.count < sessions.count),
            "note": .string("These are existing tabs on your Mac. Read a session before sending a command; an SSH tab retains its existing connection."),
          ]))
        case "mac_terminal_read_session":
          guard let sessionID = validSessionID(call.arguments["sessionId"]),
            let maximum = integerArgument(call.arguments["maxCharacters"], default: 12_000, range: 1_000...20_000)
          else { return .failure("Choose a listed sessionId and maxCharacters between 1000 and 20000.") }
          let terminal = terminal
          let session = try await terminalRead(botID: call.botId) {
            try await terminal.readSession(id: sessionID, mayRequestConsent: true)
          }
          guard isEnabled(for: call.botId) else { return accessRevoked }
          try Task.checkCancellation()
          guard session.id == sessionID else {
            return .failure("The Terminal session changed. List sessions again.")
          }
          return .success(observe(session, botID: call.botId, maximum: maximum))
        case "mac_terminal_execute_command":
          return await executeCommand(call)
        default:
          return .failure("This Terminal operation is not supported by this app version.")
        }
      } catch is CancellationError {
        return .failure("The Terminal request was cancelled. Read the session before trying again.")
      } catch { return .failure(error.localizedDescription) }
    }

    private var accessRevoked: DeviceCallOutcome {
      .failure("Mac terminal access was turned off before this request completed.")
    }

    private func terminalRead<Value: Sendable>(
      botID: String, operation: @escaping @Sendable () async throws -> Value
    ) async throws -> Value {
      let task = Task {
        try Task.checkCancellation()
        let value = try await operation()
        try Task.checkCancellation()
        return value
      }
      let id = UUID()
      reads[id] = (botID, { task.cancel() })
      defer { reads.removeValue(forKey: id) }
      return try await withTaskCancellationHandler {
        try Task.checkCancellation()
        return try await task.value
      } onCancel: { task.cancel() }
    }

    private func executeCommand(_ call: DeviceCall) async -> DeviceCallOutcome {
      guard let sessionID = validSessionID(call.arguments["sessionId"]),
        let revision = call.arguments["revision"]?.stringValue,
        let command = call.arguments["command"]?.stringValue, Self.isValidCommand(command),
        let seconds = integerArgument(call.arguments["waitSeconds"], default: 1, range: 0...10)
      else {
        return .failure("A Terminal command needs a listed sessionId, fresh revision, and one nonempty line of up to 4000 characters without control characters; waitSeconds must be 0–10.")
      }
      guard let observation = observations[sessionID], observation.botID == call.botId,
        observation.revision == revision,
        (0..<120).contains(now().timeIntervalSince(observation.capturedAt))
      else { return .failure("Read this Terminal session again before sending a command. Its revision is missing, expired, or belongs to another bot.") }
      // Consume the revision before awaiting so simultaneous calls cannot reuse
      // it. Every new command requires a new observation, including after errors.
      observations.removeValue(forKey: sessionID)
      let generation = authorizationGeneration
      do {
        let terminal = terminal
        let current = try await terminalRead(botID: call.botId) {
          try await terminal.readSession(id: sessionID, mayRequestConsent: false)
        }
        guard isEnabled(for: call.botId), generation == authorizationGeneration else { return accessRevoked }
        try Task.checkCancellation()
        guard (0..<120).contains(now().timeIntervalSince(observation.capturedAt)) else {
          return .failure("The Terminal observation expired while checking this tab. Read the session again.")
        }
        guard current.hasSameState(as: observation.session) else {
          return .failure("Terminal output or the foreground process changed. Read the session again before sending a command.")
        }
        guard Self.hasShellPrompt(current) else {
          return .failure("This tab does not show a clear shell prompt. Finish any partial input or foreground program, then read the session again. Hey Tim will not send a command into a password prompt.")
        }
        let submission = Task { try await terminal.submit(command: command, to: current) }
        let submissionID = UUID()
        submissions[submissionID] = (call.botId, submission)
        defer { submissions.removeValue(forKey: submissionID) }
        try await withTaskCancellationHandler {
          try await submission.value
        } onCancel: { submission.cancel() }
      } catch {
        return .failure(error.localizedDescription)
      }
      var result: [String: JSONValue] = [
        "sessionId": .string(sessionID), "submitted": .bool(true),
        "successVerified": .bool(false),
        "note": .string("The command was submitted to this existing Terminal tab. Submission and visible output do not establish completion or a successful exit status."),
      ]
      do {
        if seconds > 0 { try await Task.sleep(for: .seconds(seconds)) }
        guard isEnabled(for: call.botId), generation == authorizationGeneration else {
          result["outputNote"] = .string("Terminal access was turned off after submission; no additional output was read.")
          return .success(.object(result))
        }
        let terminal = terminal
        let updated = try await terminalRead(botID: call.botId) {
          try await terminal.readSession(id: sessionID, mayRequestConsent: false)
        }
        guard isEnabled(for: call.botId), generation == authorizationGeneration else {
          result["outputNote"] = .string("Terminal access was turned off after submission; additional output was not shared.")
          return .success(.object(result))
        }
        try Task.checkCancellation()
        guard updated.id == sessionID else {
          result["outputNote"] = .string("The Terminal session changed after submission. List sessions again.")
          return .success(.object(result))
        }
        result["session"] = observe(updated, botID: call.botId, maximum: 12_000)
      } catch {
        result["outputNote"] = .string("The command was submitted, but output could not be read: \(error.localizedDescription)")
      }
      return .success(.object(result))
    }

    static func isValidCommand(_ value: String) -> Bool {
      !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.count <= 4_000
        && !value.unicodeScalars.contains {
          CharacterSet.controlCharacters.contains($0) || CharacterSet.newlines.contains($0)
        }
    }

    static func hasShellPrompt(_ contents: String) -> Bool {
      let finalLine = contents.components(separatedBy: .newlines)
        .last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty })?
        .trimmingCharacters(in: .whitespaces) ?? ""
      guard !finalLine.isEmpty else { return false }
      let lower = finalLine.lowercased()
      guard !["password", "passphrase", "verification code", "one-time code", "authenticity of host"]
        .contains(where: { lower.contains($0) }) else { return false }
      // A comment or quoted marker at the end of a partially entered command
      // is not a new prompt. Never send Return for a line with pending input.
      for marker in ["$ ", "% ", "# ", "❯ ", "➜ "] {
        if let range = finalLine.range(of: marker),
          !finalLine[range.upperBound...].trimmingCharacters(in: .whitespaces).isEmpty
        { return false }
      }
      return ["$", "%", "#", "❯", "➜"].contains { finalLine.hasSuffix($0) }
    }

    static func hasShellPrompt(_ session: MacTerminalSession) -> Bool {
      let interactivePrograms: Set<String> = [
        "cat", "less", "more", "man", "vi", "vim", "nvim", "nano", "pico", "emacs",
        "python", "python3", "ipython", "node", "irb", "psql", "mysql", "passwd",
      ]
      let hasForegroundProgram = session.processes.contains { process in
        let executable = process.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? ""
        let name = URL(fileURLWithPath: executable).lastPathComponent.lowercased()
        return interactivePrograms.contains(name) || name.hasPrefix("python3.")
      }
      return !hasForegroundProgram && hasShellPrompt(session.contents)
    }

    private func observe(_ session: MacTerminalSession, botID: String, maximum: Int) -> JSONValue {
      let revision = UUID().uuidString.lowercased()
      observations = observations.filter {
        now().timeIntervalSince($0.value.capturedAt) < 120
      }
      if observations.count >= 32,
        let oldest = observations.min(by: { $0.value.capturedAt < $1.value.capturedAt })?.key
      { observations.removeValue(forKey: oldest) }
      observations[session.id] = SessionObservation(
        session: session, botID: botID, revision: revision, capturedAt: now())
      var result = metadata(session).objectValue ?? [:]
      let contents = Self.boundedTail(session.contents, characters: maximum)
      result["contents"] = .string(contents)
      result["truncated"] = .bool(contents != session.contents)
      result["revision"] = .string(revision)
      result["expiresInSeconds"] = .number(120)
      result["shellPromptReady"] = .bool(Self.hasShellPrompt(session))
      return .object(result)
    }

    private func metadata(_ session: MacTerminalSession) -> JSONValue {
      .object([
        "sessionId": .string(session.id), "application": .string("Terminal"),
        "windowId": .number(Double(session.windowID)), "tty": .string(session.tty),
        "title": .string(String(session.title.prefix(240))), "busy": .bool(session.busy),
        "processes": .array(session.processes.prefix(12).map { .string(String($0.prefix(80))) }),
      ])
    }

    static func boundedTail(_ value: String, characters: Int) -> String {
      let tail = String(value.suffix(characters))
      guard encodedSize(.string(tail)) > 40_000 else { return tail }
      // Bound encoded JSON, including escaping of terminal control characters,
      // and leave room for session metadata and the result envelope.
      let scalars = Array(tail.unicodeScalars)
      var lower = 0
      var upper = scalars.count
      while lower < upper {
        let count = (lower + upper + 1) / 2
        let candidate = String(String.UnicodeScalarView(scalars.suffix(count)))
        if encodedSize(.string(candidate)) <= 40_000 { lower = count }
        else { upper = count - 1 }
      }
      return String(String.UnicodeScalarView(scalars.suffix(lower)))
    }

    private static func encodedSize(_ value: JSONValue) -> Int {
      (try? JSONEncoder().encode(value).count) ?? Int.max
    }

    private func validSessionID(_ value: JSONValue?) -> String? {
      guard let id = value?.stringValue, !id.isEmpty, id.count <= 128 else { return nil }
      return id
    }

    private func integerArgument(_ value: JSONValue?, default fallback: Int, range: ClosedRange<Int>) -> Int? {
      guard let value else { return fallback }
      guard let number = value.intValue, range.contains(number) else { return nil }
      return number
    }
  }
#endif
