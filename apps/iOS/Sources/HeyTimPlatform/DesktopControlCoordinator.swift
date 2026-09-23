#if os(macOS)
  import AppKit
  import ApplicationServices
  import FluidUse
  import Foundation
  import Observation

  struct DesktopApplication: Identifiable, Hashable, Sendable {
    let id: pid_t
    let name: String
    let bundleIdentifier: String?
  }

  struct DesktopControlSummary: Identifiable, Equatable, Sendable {
    let id: String
    let role: String
    let label: String
    let blockedByPolicy: Bool
  }

  struct DesktopSnapshot: Equatable, Sendable {
    let application: DesktopApplication
    let windowTitle: String
    let capturedAt: Date
    let controls: [DesktopControlSummary]
  }

  struct DesktopActionProposal: Equatable, Sendable {
    let control: DesktopControlSummary?
    let reason: String

    var canExecute: Bool { control != nil }
  }

  @MainActor @Observable
  final class DesktopControlCoordinator {
    enum ChatPreparation {
      case automaticAction
      case proposal
      case clarification(String)
      case unavailable
    }

    var applications: [DesktopApplication] = []
    var selectedApplicationID: pid_t? {
      didSet {
        if selectedApplicationID != oldValue {
          snapshot = nil
          proposal = nil
          elements = [:]
        }
      }
    }
    var snapshot: DesktopSnapshot?
    var proposal: DesktopActionProposal?
    var pendingNoteText: String?
    var isEnabled = UserDefaults.standard.bool(forKey: "heytim.desktop-control.enabled") {
      didSet {
        UserDefaults.standard.set(isEnabled, forKey: "heytim.desktop-control.enabled")
        if !isEnabled {
          snapshot = nil
          proposal = nil
          elements = [:]
          message = "Mac app actions are off."
        }
      }
    }
    var enabledBotIDs = Set(UserDefaults.standard.stringArray(forKey: "heytim.desktop-control.bot-ids") ?? []) {
      didSet {
        UserDefaults.standard.set(enabledBotIDs.sorted(), forKey: "heytim.desktop-control.bot-ids")
      }
    }
    var alwaysAllowedBotIDs = Set(UserDefaults.standard.stringArray(
      forKey: "heytim.desktop-control.always-allowed-bot-ids") ?? []) {
      didSet {
        UserDefaults.standard.set(
          alwaysAllowedBotIDs.sorted(), forKey: "heytim.desktop-control.always-allowed-bot-ids")
      }
    }
    func isEnabled(for botID: String) -> Bool {
      isEnabled && enabledBotIDs.contains(botID)
    }
    func isAlwaysAllowed(for botID: String) -> Bool {
      isEnabled(for: botID) && alwaysAllowedBotIDs.contains(botID)
    }
    func allowAlways(for botID: String) {
      guard isEnabled(for: botID) else { return }
      alwaysAllowedBotIDs.insert(botID)
    }
    func setEnabled(_ enabled: Bool, for botID: String) {
      if enabled { enabledBotIDs.insert(botID) }
      else {
        enabledBotIDs.remove(botID)
        alwaysAllowedBotIDs.remove(botID)
      }
    }
    var permissionGranted = AXIsProcessTrusted()
    var permissionRequestPending = false
    var restartPrompt = false
    var message: String?
    var permissionMessage: String?

    @ObservationIgnored private var elements: [String: AXUIElement] = [:]
    @ObservationIgnored private var layaLoading: Task<LayaManager?, Never>?
    init() {
      refreshApplications()
    }

    func prepare(intent: String) {
      proposal = nil
      pendingNoteText = nil
      refreshApplications()
    }

    var proposedActionDescription: String? {
      guard let control = proposal?.control,
        let application = applications.first(where: { $0.id == selectedApplicationID })
      else { return nil }
      if let pendingNoteText {
        return "Create a note in Apple Notes containing: \(pendingNoteText)"
      }
      return "Press “\(control.label)” in \(application.name)"
    }

    func prepareForChat(intent: String) async -> ChatPreparation {
      let isNotesRequest = Self.noteCreationCandidate(intent)
      prepare(intent: intent)
      guard permissionGranted else { return .unavailable }
      let noteText = isNotesRequest ? Self.noteContent(from: intent) : nil
      if isNotesRequest && noteText == nil {
        return .clarification("What should the note say? Try “Add a note saying Hello World.”")
      }
      let application: DesktopApplication?
      if isNotesRequest {
        application = await appleNotesApplication()
      } else {
        application = Self.visibleControlRequest(intent).flatMap { request in
          applications.first { $0.name.localizedCaseInsensitiveCompare(request.app) == .orderedSame }
        }
      }
      guard let application else {
        return isNotesRequest
          ? .clarification("I couldn’t open Apple Notes. Open it and try again.")
          : .clarification("I couldn’t find that running Mac app. Open it and try again.")
      }
      selectedApplicationID = application.id
      if isNotesRequest {
        capture()
        let matchingControls = snapshot?.controls.filter {
            $0.label.localizedCaseInsensitiveContains("New Note") && !$0.blockedByPolicy
          } ?? []
        guard matchingControls.count == 1, let control = matchingControls.first
        else {
          return .clarification("I couldn’t find a New Note control in Apple Notes. Bring its window forward and try again.")
        }
        pendingNoteText = noteText
        proposal = .init(control: control, reason: "Review the exact note before it is created.")
        return Self.canAutoExecute(
          intent: intent, control: control, application: application, noteText: noteText)
          ? .automaticAction : .proposal
      }
      capture()
      guard let request = Self.visibleControlRequest(intent) else { return .unavailable }
      let matches = snapshot?.controls.filter {
        $0.label.localizedCaseInsensitiveCompare(request.control) == .orderedSame
          && !$0.blockedByPolicy
      } ?? []
      if matches.count == 1, let control = matches.first {
        proposal = .init(control: control, reason: "Review this exact visible control before it is pressed.")
        if Self.canAutoExecute(
          intent: intent, control: control, application: application, noteText: nil)
        {
          return .automaticAction
        }
      } else if matches.isEmpty, let captured = snapshot,
        let control = await layaCandidate(for: request.control, in: captured),
        isEnabled, permissionGranted, snapshot == captured
      {
        proposal = .init(control: control, reason: "Laya matched this visible control. Review the exact action before it is pressed.")
      } else {
        return .clarification("I couldn’t find one matching, safe control in that app’s focused window. Bring the window forward and try again.")
      }
      return proposal?.canExecute == true ? .proposal : .unavailable
    }

    private func appleNotesApplication() async -> DesktopApplication? {
      if let running = applications.first(where: { $0.bundleIdentifier == "com.apple.Notes" }) {
        return running
      }
      guard let url = NSWorkspace.shared.urlForApplication(
        withBundleIdentifier: "com.apple.Notes")
      else { return nil }
      let launched = await withCheckedContinuation { continuation in
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        NSWorkspace.shared.openApplication(at: url, configuration: configuration) { application, error in
          continuation.resume(returning: application != nil && error == nil)
        }
      }
      guard launched else { return nil }
      for _ in 0..<5 {
        refreshApplications()
        if let running = applications.first(where: { $0.bundleIdentifier == "com.apple.Notes" }) {
          return running
        }
        try? await Task.sleep(for: .milliseconds(200))
      }
      return nil
    }

    func requestAccessibilityPermission() {
      if AXIsProcessTrusted() {
        permissionGranted = true
        permissionRequestPending = false
        permissionMessage = "Accessibility access is ready."
        return
      }
      permissionRequestPending = true
      permissionGranted = AXIsProcessTrustedWithOptions(
        ["AXTrustedCheckOptionPrompt": true] as CFDictionary)
      permissionMessage = permissionGranted
        ? "Accessibility access is ready."
        : "Approve this copy of Hey Tim in System Settings, then return to the app."
      if !permissionGranted { openAccessibilitySettings() }
    }

    func openAccessibilitySettings() {
      guard let url = URL(
        string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
      else { return }
      NSWorkspace.shared.open(url)
    }

    func revealCurrentApplication() {
      NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
    }

    func refreshPermissionAfterSettings() {
      permissionGranted = AXIsProcessTrusted()
      guard permissionRequestPending else { return }
      permissionRequestPending = false
      restartPrompt = true
      permissionMessage = permissionGranted
        ? "Accessibility access was granted. Reopen Hey Tim to apply the change."
        : "If you enabled Hey Tim in System Settings, quit and reopen it to apply access."
    }

    func restartForAccessibility() {
      let configuration = NSWorkspace.OpenConfiguration()
      configuration.createsNewApplicationInstance = true
      configuration.activates = true
      NSWorkspace.shared.openApplication(
        at: Bundle.main.bundleURL, configuration: configuration
      ) { _, error in
        Task { @MainActor in
          if let error {
            self.permissionMessage = "Could not reopen Hey Tim: \(error.localizedDescription)"
          } else {
            NSApplication.shared.terminate(nil)
          }
        }
      }
    }

    func refreshApplications() {
      permissionGranted = AXIsProcessTrusted()
      let currentPID = ProcessInfo.processInfo.processIdentifier
      applications = NSWorkspace.shared.runningApplications.compactMap { application in
        guard application.processIdentifier != currentPID,
          application.activationPolicy == .regular,
          !application.isTerminated,
          let name = application.localizedName
        else { return nil }
        return DesktopApplication(
          id: application.processIdentifier, name: name,
          bundleIdentifier: application.bundleIdentifier)
      }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }

      if !applications.contains(where: { $0.id == selectedApplicationID }) {
        let frontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier
        selectedApplicationID = applications.first(where: { $0.id == frontmost })?.id
      }
    }

    func capture() {
      proposal = nil
      message = nil
      guard isEnabled else {
        message = "Enable Mac app actions in Settings before inspecting another app."
        return
      }
      permissionGranted = AXIsProcessTrusted()
      guard permissionGranted else {
        message = "Accessibility access is required before Hey Tim can inspect another app."
        return
      }
      guard let application = applications.first(where: { $0.id == selectedApplicationID }) else {
        message = "Choose a running application first."
        return
      }

      let root = AXUIElementCreateApplication(application.id)
      AXUIElementSetMessagingTimeout(root, 1.0)
      let window = activeWindow(in: root)
      let windowTitle = stringAttribute(kAXTitleAttribute, from: window) ?? "Untitled window"
      var controls: [DesktopControlSummary] = []
      var resolved: [String: AXUIElement] = [:]
      var visited = 0
      walk(
        window, depth: 0, visited: &visited,
        controls: &controls, resolved: &resolved)

      elements = resolved
      snapshot = DesktopSnapshot(
        application: application,
        windowTitle: Self.clean(windowTitle, limit: 100),
        capturedAt: Date(),
        controls: Array(controls.prefix(60)))
      if controls.isEmpty {
        message = "No pressable controls were found in the focused window."
      }
    }

    /// Only well-scoped imperative requests can take the local action path.
    /// Questions, negation, and ambiguous requests stay in the ordinary bot flow.
    static func shouldOfferDesktopAction(for text: String) -> Bool {
      noteCreationCandidate(text) || visibleControlRequest(text) != nil
    }

    static func visibleControlRequest(_ text: String) -> (control: String, app: String)? {
      let pattern = #"^\s*(?:(?:please|can you|could you)\s+)?(?:click|press)\s+(?:the\s+)?(.{1,80}?)\s+in\s+([\p{L}\p{N} .-]{1,60}?)(?:\s+on\s+(?:my|this)\s+Mac)?\s*[.!]?\s*$"#
      guard let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else {
        return nil
      }
      let range = NSRange(text.startIndex..<text.endIndex, in: text)
      guard let match = regex.firstMatch(in: text, range: range),
        let controlRange = Range(match.range(at: 1), in: text),
        let appRange = Range(match.range(at: 2), in: text)
      else { return nil }
      let control = text[controlRange].trimmingCharacters(in: .whitespacesAndNewlines)
      let app = text[appRange].trimmingCharacters(in: .whitespacesAndNewlines)
      guard !control.isEmpty, !app.isEmpty else { return nil }
      return (control, app)
    }

    static func targetsAppleNotes(_ text: String) -> Bool {
      ["apple notes", "notes app", "in notes", "to notes"].contains(where: text.contains)
    }

    static func noteCreationCandidate(_ text: String) -> Bool {
      text.range(
        of: #"^\s*(?:(?:please|can you|could you)\s+)?(?:add|create|make|write|put|start)\b[^\n.!?]{0,80}\bnotes?\b"#,
        options: [.regularExpression, .caseInsensitive]) != nil
    }

    static func noteContent(from text: String) -> String? {
      for marker in ["that says ", "saying ", "to say ", "with text ", "containing ", "note: "] {
        guard let range = text.range(of: marker, options: .caseInsensitive) else { continue }
        let content = text[range.upperBound...]
          .trimmingCharacters(in: .whitespacesAndNewlines)
          .trimmingCharacters(in: CharacterSet(charactersIn: "\"“”'"))
        if !content.isEmpty && content.count <= 1_000 { return content }
      }
      return nil
    }

    /// A model score never authorizes an action. Automatic execution requires
    /// an exact, unique UI match for a narrow low-impact request instead.
    static func canAutoExecute(
      intent: String, control: DesktopControlSummary,
      application: DesktopApplication, noteText: String?
    ) -> Bool {
      guard control.role == (kAXButtonRole as String),
        !control.blockedByPolicy, !isHighImpact(label: control.label)
      else { return false }
      if let noteText {
        return application.bundleIdentifier == "com.apple.Notes"
          && control.label.localizedCaseInsensitiveCompare("New Note") == .orderedSame
          && noteCreationCandidate(intent)
          && noteContent(from: intent) == noteText
      }
      guard let request = visibleControlRequest(intent),
        request.app.localizedCaseInsensitiveCompare(application.name) == .orderedSame,
        request.control.localizedCaseInsensitiveCompare(control.label) == .orderedSame
      else { return false }
      let label = control.label.lowercased()
      return ["next", "previous", "back", "forward", "expand", "collapse"].contains(label)
        || ["show ", "view ", "expand ", "collapse "].contains { label.hasPrefix($0) }
    }

    private func localModel() async -> LayaManager? {
      if let layaLoading { return await layaLoading.value }
      let task = Task<LayaManager?, Never> {
        guard let directory = Bundle.main.resourceURL?.appendingPathComponent(
          "laya-coreml", isDirectory: true),
          FileManager.default.fileExists(
            atPath: directory.appendingPathComponent("tokenizer.json").path)
        else { return nil }
        return try? await LayaManager.load(
          from: directory, configuration: .init(lengths: [128], precision: "e8"))
      }
      layaLoading = task
      return await task.value
    }

    func homeAssistantHint(for request: String) async -> HomeAssistantRouteHint? {
      let text = request.trimmingCharacters(in: .whitespacesAndNewlines)
      let lower = text.lowercased()
      guard text.count <= 180, !text.contains("\n"),
        lower.hasPrefix("turn ") || lower.hasPrefix("please turn ") || lower.hasPrefix("is "),
        let model = await localModel()
      else { return nil }
      let options = [
        LayaQuestion.Choice("turn_on", description: "Turn on one named home device"),
        LayaQuestion.Choice("turn_off", description: "Turn off one named home device"),
        LayaQuestion.Choice("read_state", description: "Check whether one named home device is on"),
        LayaQuestion.Choice("main_model", description: "Anything else or uncertain")
      ]
      let question = LayaQuestion.choice(
        "Which Home Assistant action does this request ask for? Choose main_model if unclear.",
        options: options)
      guard let answer = try? await model.answer(state: "request: \(text)", question: question),
        answer.selectedLabel != "main_model", answer.tokenCount < answer.bucketLength,
        !answer.stateWasTruncated,
        answer.confidence >= (answer.selectedLabel == "read_state" ? 0.20 : 0.85),
        answer.actionProbability >= 0.95
      else { return nil }
      return HomeAssistantRouteHint(
        selectedLabel: answer.selectedLabel,
        confidence: Double(answer.confidence),
        actionProbability: Double(answer.actionProbability), truncated: false)
    }

    private func layaCandidate(
      for requestedControl: String, in captured: DesktopSnapshot
    ) async -> DesktopControlSummary? {
      let candidates = Self.layaCandidates(
        for: requestedControl, from: captured.controls)
      guard !candidates.isEmpty, let model = await localModel() else { return nil }
      let options = candidates.map {
        LayaQuestion.Choice($0.id, description: Self.clean($0.label, limit: 36))
      } + [LayaQuestion.Choice("main_model", description: "No clear safe match")]
      let question = LayaQuestion.choice(
        "Which visible control matches the requested click? Choose main_model if unclear.",
        options: options)
      guard let answer = try? await model.answer(
        state: "request: \(Self.clean(requestedControl, limit: 72))",
        question: question),
        !answer.stateWasTruncated,
        answer.actionProbability >= 0.85,
        answer.confidence >= 0.80,
        answer.tokenCount < answer.bucketLength
      else { return nil }
      return candidates.first { $0.id == answer.selectedLabel }
    }

    static func layaCandidates(
      for requestedControl: String, from controls: [DesktopControlSummary]
    ) -> [DesktopControlSummary] {
      let requestedWords = Set(requestedControl.lowercased().split(whereSeparator: {
        !$0.isLetter && !$0.isNumber
      }).map(String.init).filter { $0.count >= 3 })
      guard !requestedWords.isEmpty else { return [] }
      let candidates = controls.filter { control in
        guard !control.blockedByPolicy else { return false }
        let labelWords = Set(control.label.lowercased().split(whereSeparator: {
          !$0.isLetter && !$0.isNumber
        }).map(String.init))
        return !requestedWords.isDisjoint(with: labelWords)
      }
      // A short, complete candidate list avoids silently truncating the model's
      // 128-token input or hiding another matching control from the user.
      return (1...4).contains(candidates.count) ? candidates : []
    }

    func executePreparedAction() async -> String {
      guard isEnabled, AXIsProcessTrusted(),
        let control = proposal?.control, !control.blockedByPolicy,
        let element = elements[control.id],
        (stringAttribute(kAXTitleAttribute, from: element)
          ?? stringAttribute(kAXDescriptionAttribute, from: element)) == control.label,
        let application = applications.first(where: { $0.id == selectedApplicationID }),
        NSRunningApplication(processIdentifier: application.id) != nil
      else {
        proposal = nil
        message = "The app or control changed. Capture a fresh snapshot before trying again."
        return message ?? "Mac app action was not completed."
      }
      var elementPID: pid_t = 0
      guard let captured = snapshot,
        Date().timeIntervalSince(captured.capturedAt) < 60,
        AXUIElementGetPid(element, &elementPID) == .success,
        elementPID == application.id,
        boolAttribute(kAXEnabledAttribute, from: element) != false,
        actionNames(element).contains(kAXPressAction as String),
        !Self.isHighImpact(label: control.label)
      else {
        proposal = nil
        pendingNoteText = nil
        return "The control changed or the review expired. Ask again for a fresh action."
      }
      let root = AXUIElementCreateApplication(application.id)
      let focusedWindow = activeWindow(in: root)
      let currentWindowTitle = Self.clean(
        stringAttribute(kAXTitleAttribute, from: focusedWindow) ?? "Untitled window",
        limit: 100)
      guard snapshot?.application.id == application.id,
        snapshot?.windowTitle == currentWindowTitle
      else {
        proposal = nil
        pendingNoteText = nil
        return "The target window changed. Ask again to review a fresh action."
      }
      let noteText = pendingNoteText
      if noteText != nil && application.bundleIdentifier != "com.apple.Notes" {
        proposal = nil
        pendingNoteText = nil
        return "The target app changed. The note was not created."
      }
      NSRunningApplication(processIdentifier: application.id)?.activate()
      let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
      proposal = nil
      pendingNoteText = nil
      guard result == .success else {
        message = "macOS could not press that control. Capture a fresh snapshot and try again."
        return message ?? "Mac app action was not completed."
      }
      if let noteText {
        for _ in 0..<5 {
          try? await Task.sleep(for: .milliseconds(180))
          let root = AXUIElementCreateApplication(application.id)
          let window = activeWindow(in: root)
          if let body = findNotesBody(in: window, depth: 0) {
            var settable = DarwinBoolean(false)
            if AXUIElementIsAttributeSettable(body, kAXValueAttribute as CFString, &settable) == .success,
              settable.boolValue,
              AXUIElementSetAttributeValue(body, kAXValueAttribute as CFString, noteText as CFTypeRef) == .success,
              stringAttribute(kAXValueAttribute, from: body)?.hasPrefix(noteText) == true
            {
              message = "Created the note in Apple Notes."
              return message ?? "Created the note."
            }
          }
        }
        message = "Opened a new note, but macOS did not allow Hey Tim to enter its text. Check Apple Notes before retrying."
        return message ?? "The note text could not be entered."
      }
      message = "Mac app action completed: \(control.label)."
      return message ?? "Mac app action completed."
    }

    private func findNotesBody(in element: AXUIElement, depth: Int) -> AXUIElement? {
      guard depth < 8 else { return nil }
      let role = stringAttribute(kAXRoleAttribute, from: element)
      let label = stringAttribute(kAXDescriptionAttribute, from: element)
        ?? stringAttribute(kAXTitleAttribute, from: element)
      if role == (kAXTextAreaRole as String), label == "Note Body Text View" { return element }
      for child in elementArrayAttribute(kAXChildrenAttribute, from: element) {
        if let match = findNotesBody(in: child, depth: depth + 1) { return match }
      }
      return nil
    }

    static func isHighImpact(label: String) -> Bool {
      let words = Set(label.lowercased().components(
        separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty })
      let blocked: Set<String> = [
        "allow", "approve", "buy", "checkout", "confirm", "delete", "erase",
        "grant", "install", "ok", "pay", "post", "publish", "purchase",
        "remove", "reply", "reset", "save", "send", "share", "submit",
        "transfer", "yes",
      ]
      return !words.isDisjoint(with: blocked)
    }

    private func walk(
      _ element: AXUIElement,
      depth: Int,
      visited: inout Int,
      controls: inout [DesktopControlSummary],
      resolved: inout [String: AXUIElement]
    ) {
      guard depth <= 7, visited < 180, controls.count < 60 else { return }
      visited += 1
      let role = stringAttribute(kAXRoleAttribute, from: element) ?? "element"
      // Secure fields are never included in the model's candidate tree.
      guard role != "AXSecureTextField", boolAttribute("AXVisible", from: element) != false else {
        return
      }
      let label = stringAttribute(kAXTitleAttribute, from: element)
        ?? stringAttribute(kAXDescriptionAttribute, from: element)
        ?? stringAttribute(kAXHelpAttribute, from: element)

      if role == (kAXButtonRole as String),
        boolAttribute(kAXEnabledAttribute, from: element) != false,
        let label, !label.isEmpty,
        actionNames(element).contains(kAXPressAction as String)
      {
        let id = "control_\(controls.count + 1)"
        let summary = DesktopControlSummary(
          id: id, role: role, label: Self.clean(label, limit: 100),
          blockedByPolicy: Self.isHighImpact(label: label))
        controls.append(summary)
        resolved[id] = element
      }

      let children = elementArrayAttribute(kAXChildrenAttribute, from: element)
      // Large document/list subtrees can exhaust the bounded walk before a
      // window's toolbar. Give visible toolbar actions first consideration.
      let ordered = children.filter { stringAttribute(kAXRoleAttribute, from: $0) == "AXToolbar" }
        + children.filter { stringAttribute(kAXRoleAttribute, from: $0) != "AXToolbar" }
      for child in ordered {
        walk(
          child, depth: depth + 1, visited: &visited,
          controls: &controls, resolved: &resolved)
      }
    }

    private func activeWindow(in application: AXUIElement) -> AXUIElement {
      elementAttribute(kAXFocusedWindowAttribute, from: application)
        ?? elementArrayAttribute(kAXWindowsAttribute, from: application).first
        ?? application
    }

    private func stringAttribute(_ name: String, from element: AXUIElement) -> String? {
      var value: CFTypeRef?
      guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
      }
      return value as? String
    }

    private func boolAttribute(_ name: String, from element: AXUIElement) -> Bool? {
      var value: CFTypeRef?
      guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
      }
      return value as? Bool
    }

    private func elementAttribute(_ name: String, from element: AXUIElement) -> AXUIElement? {
      var value: CFTypeRef?
      guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success,
        let value
      else { return nil }
      return (value as! AXUIElement)
    }

    private func elementArrayAttribute(_ name: String, from element: AXUIElement) -> [AXUIElement] {
      var value: CFTypeRef?
      guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return []
      }
      return value as? [AXUIElement] ?? []
    }

    private func actionNames(_ element: AXUIElement) -> [String] {
      var names: CFArray?
      guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
      return names as? [String] ?? []
    }

    private static func clean(_ value: String, limit: Int) -> String {
      let collapsed = value
        .components(separatedBy: .whitespacesAndNewlines)
        .filter { !$0.isEmpty }
        .joined(separator: " ")
      return String(collapsed.prefix(limit))
    }
  }
#endif
