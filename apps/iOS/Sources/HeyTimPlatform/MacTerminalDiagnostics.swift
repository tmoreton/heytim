#if os(macOS)
  import ApplicationServices
  import Foundation

  struct MacTerminalError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
  }

  struct MacTerminalPermissionPreflight: Sendable {
    var status: @Sendable (Int32, Bool) -> Int32 = { processID, askUserIfNeeded in
      let target = NSAppleEventDescriptor(processIdentifier: processID)
      guard let address = target.aeDesc else { return Int32(paramErr) }
      return withExtendedLifetime(target) {
        AEDeterminePermissionToAutomateTarget(
          address, AEEventClass(kAECoreSuite), AEEventID(kAEGetData), askUserIfNeeded)
      }
    }

    func authorize(processID: Int32, mayRequestConsent: Bool) throws {
      try Task.checkCancellation()
      var stage = MacTerminalStage.permissionCheck
      var code = status(processID, false)
      try Task.checkCancellation()
      if code == Int32(errAEEventWouldRequireUserConsent), mayRequestConsent {
        // Only an authorized list/read can request normal macOS consent. This
        // API sends no Apple event and may wait for the user; keep it off-main
        // and outside the metadata script's eight-second event timeout.
        stage = .permissionRequest
        code = status(processID, true)
      }
      try Task.checkCancellation()
      guard code == noErr else {
        throw MacTerminalError(message: MacTerminalDiagnostics.message(
          code: Int(code), stage: stage, processID: processID))
      }
    }
  }

  enum MacTerminalStage: String, CaseIterable, Sendable {
    case permissionCheck = "permission-check", permissionRequest = "permission-request"
    case windows, tabs, windowID = "window-id", tty, title, windowTitle = "window-title"
    case busy, processes, contents, sessionCheck = "session-check", command = "command-submit"
    case script
  }

  enum MacTerminalDiagnostics {
    static let stagePrefix = "HT_TERMINAL_STAGE:"

    static func stage(from details: NSDictionary) -> MacTerminalStage {
      guard let message = details[NSAppleScript.errorMessage] as? String,
        let range = message.range(of: stagePrefix, options: .backwards),
        let stage = MacTerminalStage(rawValue:
          String(message[range.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines))
      else { return .script }
      return stage
    }

    static func message(
      code: Int, stage: MacTerminalStage, processID: Int32, commandRequested: Bool? = nil
    ) -> String {
      let text: String
      switch code {
      case -1743:
        text = "Terminal Automation permission is denied. Allow Hey Tim to control Terminal in macOS System Settings → Privacy & Security → Automation, then read the session again."
      case -1744:
        text = "Terminal Automation consent is still needed. Read or list sessions to complete the macOS permission request before sending a command."
      case -600:
        text = "The observed Terminal process is no longer running. List sessions again."
      case -1712 where stage == .permissionCheck || stage == .permissionRequest:
        text = "macOS did not complete the Terminal Automation permission check. Check System Settings → Privacy & Security → Automation before trying again."
      case -1712 where stage == .command || (stage == .script && commandRequested != false):
        text = "Terminal did not confirm command submission in time. It may have been submitted; read the session before trying again."
      case -1712:
        text = "Terminal did not respond in time while inspecting the existing session. No command was submitted by this operation."
      case -2700:
        text = "The observed Terminal session changed or closed. Read the session again before sending a command."
      default:
        text = "The Terminal request could not be completed."
      }
      // Only trusted constants and numeric diagnostics cross the device bridge.
      // Never expose the raw AppleScript error, which can contain tab contents.
      return text + " [stage=\(stage.rawValue), code=\(code), pid=\(processID)]"
    }

    static func annotate(_ body: String) -> String {
      """
      set requestStage to "session-check"
      try
        \(body)
      on error number errorCode
        error ("\(stagePrefix)" & requestStage) number errorCode
      end try
      """
    }
  }

  extension AppleTerminalService {
    static func appleScriptLiteral(_ value: String) -> String {
      // AppleScript has no JSON-style Unicode escapes. Construct control
      // characters explicitly instead of letting data change the script source.
      var pieces: [String] = []
      var text = ""
      func flush() {
        guard !text.isEmpty else { return }
        pieces.append("\"" + text.replacingOccurrences(of: "\\", with: "\\\\")
          .replacingOccurrences(of: "\"", with: "\\\"") + "\"")
        text = ""
      }
      for scalar in value.unicodeScalars {
        if CharacterSet.controlCharacters.contains(scalar)
          || CharacterSet.newlines.contains(scalar)
        {
          flush()
          pieces.append("(character id \(scalar.value))")
        } else { text.unicodeScalars.append(scalar) }
      }
      flush()
      return pieces.isEmpty ? "\"\"" : "(" + pieces.joined(separator: " & ") + ")"
    }

    static func sessionScript(
      windowID: Int? = nil, tty: String? = nil, includeContents: Bool = false
    ) -> String {
      let windowFilter = windowID.map { "if tabWindowID is \($0) then" } ?? ""
      let ttyFilter = tty.map { "if tabTTY is \(appleScriptLiteral($0)) then" } ?? ""
      let contents = includeContents
        ? "my boundedContents(contents of terminalTab as text)" : "\"\""
      return tailHandler + "\n" + MacTerminalDiagnostics.annotate("""
        with timeout of 8 seconds
          tell application id "com.apple.Terminal"
            if not running then return {}
            set resultRows to {}
            set requestStage to "windows"
            repeat with terminalWindow in windows
              set requestStage to "window-id"
              set tabWindowID to id of terminalWindow
              \(windowFilter)
              set requestStage to "tabs"
              repeat with terminalTab in tabs of terminalWindow
                set requestStage to "tty"
                set tabTTY to tty of terminalTab as text
                \(ttyFilter)
                set requestStage to "title"
                set tabTitle to custom title of terminalTab as text
                if tabTitle is "" then
                  set requestStage to "window-title"
                  set tabTitle to name of terminalWindow as text
                end if
                set requestStage to "busy"
                set tabBusy to busy of terminalTab
                set requestStage to "processes"
                set tabProcesses to processes of terminalTab
                set requestStage to "contents"
                set tabContents to \(contents)
                set end of resultRows to {tabWindowID, tabTTY, tabTitle, tabBusy, tabProcesses, tabContents}
                if (count resultRows) is greater than or equal to 64 then return resultRows
                \(tty == nil ? "" : "end if")
              end repeat
              \(windowID == nil ? "" : "end if")
            end repeat
            return resultRows
          end tell
        end timeout
        """)
    }

    static func submissionScript(command: String, session: MacTerminalSession) -> String {
      let processList = "{" + session.processes.map(appleScriptLiteral).joined(separator: ", ") + "}"
      return tailHandler + "\n" + MacTerminalDiagnostics.annotate("""
        with timeout of 8 seconds
          tell application id "com.apple.Terminal"
            if not running then error "The observed Terminal app closed." number -2700
            if not (exists window id \(session.windowID)) then error "The observed Terminal window closed." number -2700
            set requestStage to "tabs"
            repeat with terminalTab in tabs of window id \(session.windowID)
              set requestStage to "tty"
              if (tty of terminalTab as text) is \(appleScriptLiteral(session.tty)) then
                set requestStage to "contents"
                if (my boundedContents(contents of terminalTab as text)) is not \(appleScriptLiteral(session.contents)) then error "Terminal output changed." number -2700
                set requestStage to "busy"
                if (busy of terminalTab) is not \(session.busy ? "true" : "false") then error "Terminal process changed." number -2700
                set requestStage to "processes"
                if (processes of terminalTab) is not \(processList) then error "Terminal process changed." number -2700
                set requestStage to "command-submit"
                do script \(appleScriptLiteral(command)) in terminalTab
                return {}
              end if
            end repeat
            error "The observed Terminal tab closed or changed." number -2700
          end tell
        end timeout
        """)
    }

    private static var tailHandler: String {
      """
      on boundedContents(valueText)
        if (count characters of valueText) is greater than 20000 then
          return text -20000 thru -1 of valueText
        end if
        return valueText
      end boundedContents
      """
    }
  }
#endif
