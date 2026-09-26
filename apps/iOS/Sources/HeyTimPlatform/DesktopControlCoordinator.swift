#if os(macOS)
  import AppKit
  import ApplicationServices
  import Foundation
  import Observation
  import ScreenCaptureKit
  import Vision

  private let desktopAXObserverCallback: AXObserverCallback = {
    _, _, _, context in
    guard let context else { return }
    let waiter = Unmanaged<DesktopAXChangeWaiter>.fromOpaque(context)
      .takeUnretainedValue()
    Task { @MainActor in waiter.signal() }
  }

  private final class DesktopEventMonitor: @unchecked Sendable {
    let token: Any?

    init(token: Any?) {
      self.token = token
    }

    deinit {
      if let token { NSEvent.removeMonitor(token) }
    }
  }

  @MainActor
  private final class DesktopAXChangeWaiter: @unchecked Sendable {
    private var observer: AXObserver?
    private var continuation: CheckedContinuation<Bool, Never>?
    private var timeoutTask: Task<Void, Never>?

    func wait(pid: pid_t, elements: [AXUIElement], seconds: Int) async -> Bool {
      var created: AXObserver?
      guard AXObserverCreate(pid, desktopAXObserverCallback, &created) == .success,
        let created
      else { return false }
      observer = created
      let notifications = [
        kAXFocusedWindowChangedNotification as String,
        kAXWindowCreatedNotification as String,
        kAXUIElementDestroyedNotification as String,
        kAXValueChangedNotification as String,
        kAXTitleChangedNotification as String,
        kAXSelectedChildrenChangedNotification as String,
      ]
      var registered = false
      for element in elements {
        for notification in notifications {
          registered = AXObserverAddNotification(
            created, element, notification as CFString,
            Unmanaged.passUnretained(self).toOpaque()) == .success || registered
        }
      }
      guard registered else {
        observer = nil
        return false
      }
      CFRunLoopAddSource(
        CFRunLoopGetMain(), AXObserverGetRunLoopSource(created), .defaultMode)
      return await withCheckedContinuation { continuation in
        self.continuation = continuation
        timeoutTask = Task { [weak self] in
          try? await Task.sleep(for: .seconds(seconds))
          self?.finish(changed: false)
        }
      }
    }

    func signal() {
      finish(changed: true)
    }

    private func finish(changed: Bool) {
      guard let continuation else { return }
      self.continuation = nil
      timeoutTask?.cancel()
      timeoutTask = nil
      if let observer {
        CFRunLoopRemoveSource(
          CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
      }
      self.observer = nil
      continuation.resume(returning: changed)
    }
  }

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
    let editable: Bool
    let value: String?
    let source: String
    let supportedActions: [String]

    init(
      id: String, role: String, label: String, blockedByPolicy: Bool,
      editable: Bool = false, value: String? = nil, source: String = "accessibility",
      supportedActions: [String] = []
    ) {
      self.id = id
      self.role = role
      self.label = label
      self.blockedByPolicy = blockedByPolicy
      self.editable = editable
      self.value = value
      self.source = source
      self.supportedActions = supportedActions
    }
  }

  struct DesktopSnapshot: Equatable, Sendable {
    let revision: String
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
    static let enabledKey = "heytim.desktop-control.enabled"
    static let enabledBotIDsKey = "heytim.desktop-control.bot-ids"
    static let pausedKey = "heytim.desktop-control.paused"

    private struct OCRTarget {
      let label: String
      let normalizedBounds: CGRect
      let windowID: CGWindowID
      let windowFrame: CGRect
    }
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
          ocrTargets = [:]
        }
      }
    }
    var snapshot: DesktopSnapshot?
    var proposal: DesktopActionProposal?
    var pendingNoteText: String?
    var isEnabled = UserDefaults.standard.bool(forKey: enabledKey) {
      didSet {
        UserDefaults.standard.set(isEnabled, forKey: Self.enabledKey)
        if !isEnabled {
          snapshot = nil
          proposal = nil
          elements = [:]
          ocrTargets = [:]
          message = "Mac app actions are off."
        }
      }
    }
    var isPaused = UserDefaults.standard.bool(forKey: pausedKey) {
      didSet {
        UserDefaults.standard.set(isPaused, forKey: Self.pausedKey)
        if isPaused {
          snapshot = nil
          proposal = nil
          elements = [:]
          ocrTargets = [:]
        }
      }
    }
    private(set) var takeoverMessage: String?
    var enabledBotIDs = Set(UserDefaults.standard.stringArray(forKey: enabledBotIDsKey) ?? []) {
      didSet {
        UserDefaults.standard.set(enabledBotIDs.sorted(), forKey: Self.enabledBotIDsKey)
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
    func revokeAlways(for botID: String) {
      alwaysAllowedBotIDs.remove(botID)
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
    @ObservationIgnored private var ocrTargets: [String: OCRTarget] = [:]
    @ObservationIgnored private var ocrMessage: String?
    @ObservationIgnored private var globalInputMonitor: DesktopEventMonitor?
    @ObservationIgnored private var automationArmedUntil: Date?
    @ObservationIgnored private var isSynthesizingInput = false
    init() {
      refreshApplications()
      globalInputMonitor = DesktopEventMonitor(token: NSEvent.addGlobalMonitorForEvents(
        matching: [
          .leftMouseDown, .rightMouseDown, .otherMouseDown, .mouseMoved,
          .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .keyDown, .scrollWheel,
        ]
      ) { [weak self] _ in
        Task { @MainActor in self?.recordHumanInput() }
      })
    }

    func pauseComputerUse(reason: String = "Mac computer use is paused.") {
      isPaused = true
      automationArmedUntil = nil
      takeoverMessage = reason
      message = reason
    }

    func resumeComputerUse() {
      isPaused = false
      takeoverMessage = nil
      message = "Mac computer use is ready."
    }

    private func recordHumanInput() {
      guard Self.shouldPauseForHumanInput(
        isPaused: isPaused, isSynthesizing: isSynthesizingInput,
        armedUntil: automationArmedUntil, now: Date())
      else { return }
      pauseComputerUse(
        reason: "Paused because you used the keyboard, mouse, or trackpad during an active computer-use session."
      )
    }

    private func armTakeoverMonitoring() {
      automationArmedUntil = Date().addingTimeInterval(60)
    }

    static func shouldPauseForHumanInput(
      isPaused: Bool, isSynthesizing: Bool, armedUntil: Date?, now: Date
    ) -> Bool {
      !isPaused && !isSynthesizing && armedUntil.map { $0 > now } == true
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
      guard !isPaused else {
        message = takeoverMessage ?? "Resume Mac computer use before inspecting another app."
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
      ocrTargets = [:]
      ocrMessage = nil
      snapshot = DesktopSnapshot(
        revision: UUID().uuidString.lowercased(),
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

    /// Automatic execution requires an exact, unique UI match for a narrow low-impact request.
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

    var screenRecordingGranted: Bool { CGPreflightScreenCaptureAccess() }

    func requestScreenRecordingPermission() {
      _ = CGRequestScreenCaptureAccess()
    }

    func execute(_ call: DeviceCall) async -> DeviceCallOutcome {
      guard call.toolId == "mac_computer", isEnabled(for: call.botId) else {
        return .failure("Mac app actions are not enabled for this bot on this Mac.")
      }
      guard !isPaused else {
        return .failure(
          takeoverMessage
            ?? "Mac computer use is paused on this Mac. Resume it in Hey Tim before trying again.")
      }
      guard isEnabled, AXIsProcessTrusted() else {
        return .failure("Hey Tim needs Accessibility access before it can use Mac app actions.")
      }
      switch call.operation {
      case "mac_computer_observe":
        return await observe(
          applicationHint: call.arguments["application"]?.stringValue,
          includeOCR: call.arguments["include_ocr"]?.boolValue == true)
      case "mac_computer_act_on_element":
        guard let revision = call.arguments["snapshot_revision"]?.stringValue,
          let targetID = call.arguments["target_id"]?.stringValue
        else { return .failure("The Mac action is missing its snapshot revision or target.") }
        return await performAction(
          call.arguments["action"]?.stringValue ?? "press",
          targetID: targetID, revision: revision)
      case "mac_computer_type_into_element":
        guard let revision = call.arguments["snapshot_revision"]?.stringValue,
          let targetID = call.arguments["target_id"]?.stringValue,
          let text = call.arguments["text"]?.stringValue
        else { return .failure("The Mac typing action is missing required input.") }
        return await type(text, into: targetID, revision: revision)
      case "mac_computer_wait_for_state":
        guard let revision = call.arguments["snapshot_revision"]?.stringValue else {
          return .failure("The Mac wait action is missing its snapshot revision.")
        }
        let seconds = min(max(call.arguments["seconds"]?.intValue ?? 1, 1), 10)
        return await waitForState(revision: revision, seconds: seconds)
      case "mac_computer_scroll":
        guard let revision = call.arguments["snapshot_revision"]?.stringValue,
          let targetID = call.arguments["target_id"]?.stringValue,
          let direction = call.arguments["direction"]?.stringValue
        else { return .failure("The Mac scroll action is missing required input.") }
        return await scroll(
          targetID: targetID, revision: revision, direction: direction,
          amount: call.arguments["amount"]?.stringValue ?? "line")
      default:
        return .failure("This Mac operation is not supported by this app version.")
      }
    }

    private func observe(applicationHint: String?, includeOCR: Bool) async -> DeviceCallOutcome {
      refreshApplications()
      let application: DesktopApplication?
      if let hint = applicationHint?.trimmingCharacters(in: .whitespacesAndNewlines),
        !hint.isEmpty
      {
        let matches = applications.filter {
          $0.name.localizedCaseInsensitiveCompare(hint) == .orderedSame
            || $0.bundleIdentifier?.localizedCaseInsensitiveCompare(hint) == .orderedSame
        }
        guard matches.count == 1 else {
          return .failure(
            matches.isEmpty
              ? "That Mac app is not currently running."
              : "More than one running Mac app matched that name.")
        }
        application = matches.first
      } else {
        let frontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier
        application = applications.first { $0.id == frontmost }
          ?? applications.first { $0.id == selectedApplicationID }
      }
      guard let application else {
        return .failure("No eligible running Mac app is available to inspect.")
      }
      selectedApplicationID = application.id
      capture()
      guard snapshot != nil else {
        return .failure(message ?? "The focused Mac window could not be inspected.")
      }
      if includeOCR { await appendLocalOCR() }
      armTakeoverMonitoring()
      return .success(snapshotValue())
    }

    private func performAction(
      _ requestedAction: String, targetID: String, revision: String
    ) async -> DeviceCallOutcome {
      guard let captured = validatedSnapshot(revision: revision),
        let control = captured.controls.first(where: { $0.id == targetID })
      else {
        return .failure("The Mac window changed or this snapshot expired. Observe it again.")
      }
      guard !control.blockedByPolicy, !Self.isHighImpact(label: control.label) else {
        return .failure("Hey Tim blocks this consequential control on the device.")
      }
      guard let accessibilityAction = Self.accessibilityAction(
        requestedAction, supportedActions: control.supportedActions)
      else {
        return .failure("That semantic action is not supported by this control.")
      }
      let succeeded: Bool
      if let element = elements[targetID] {
        var processID: pid_t = 0
        let currentLabel = stringAttribute(kAXTitleAttribute, from: element)
          ?? stringAttribute(kAXDescriptionAttribute, from: element)
          ?? stringAttribute(kAXHelpAttribute, from: element)
        guard currentLabel.map({ Self.clean($0, limit: 100) }) == control.label,
          AXUIElementGetPid(element, &processID) == .success,
          processID == captured.application.id,
          boolAttribute(kAXEnabledAttribute, from: element) != false,
          actionNames(element).contains(accessibilityAction)
        else {
          return .failure("The target control changed. Observe the window again.")
        }
        NSRunningApplication(processIdentifier: processID)?.activate()
        succeeded = AXUIElementPerformAction(element, accessibilityAction as CFString) == .success
      } else if let target = ocrTargets[targetID] {
        guard requestedAction == "press" else {
          return .failure("Local OCR targets only support a press action.")
        }
        succeeded = await pressOCRTarget(target, application: captured.application)
      } else {
        return .failure("The requested Mac target is no longer available.")
      }
      guard succeeded else {
        return .failure("macOS could not activate that control. Observe the window again.")
      }
      try? await Task.sleep(for: .milliseconds(350))
      capture()
      armTakeoverMonitoring()
      var result = snapshotValue().objectValue ?? [:]
      result["actionPerformed"] = .string(requestedAction)
      result["targetLabel"] = .string(control.label)
      result["verifiedAfterAction"] = .bool(snapshot != nil)
      return .success(.object(result))
    }

    private func type(_ text: String, into targetID: String, revision: String) async
      -> DeviceCallOutcome
    {
      guard text.count <= 4_000,
        let captured = validatedSnapshot(revision: revision),
        let control = captured.controls.first(where: { $0.id == targetID }),
        control.editable,
        let element = elements[targetID]
      else {
        return .failure("The editable Mac target changed or this snapshot expired.")
      }
      var processID: pid_t = 0
      guard AXUIElementGetPid(element, &processID) == .success,
        processID == captured.application.id,
        stringAttribute(kAXRoleAttribute, from: element) != "AXSecureTextField",
        attributeIsSettable(kAXValueAttribute, on: element)
      else {
        return .failure("That field is secure, read-only, or no longer in the captured window.")
      }
      NSRunningApplication(processIdentifier: processID)?.activate()
      guard AXUIElementSetAttributeValue(
        element, kAXValueAttribute as CFString, text as CFTypeRef) == .success,
        stringAttribute(kAXValueAttribute, from: element) == text
      else {
        return .failure("macOS did not confirm the new field value.")
      }
      try? await Task.sleep(for: .milliseconds(200))
      capture()
      armTakeoverMonitoring()
      var result = snapshotValue().objectValue ?? [:]
      result["actionPerformed"] = .string("typed")
      result["targetLabel"] = .string(control.label)
      result["verifiedAfterAction"] = .bool(true)
      return .success(.object(result))
    }

    private func scroll(
      targetID: String, revision: String, direction: String, amount: String
    ) async -> DeviceCallOutcome {
      guard ["up", "down", "left", "right"].contains(direction),
        ["line", "page"].contains(amount),
        let captured = validatedSnapshot(revision: revision),
        let control = captured.controls.first(where: { $0.id == targetID }),
        control.supportedActions.contains("scroll"),
        let element = elements[targetID]
      else {
        return .failure("The scroll target changed, is invalid, or this snapshot expired.")
      }
      var processID: pid_t = 0
      guard AXUIElementGetPid(element, &processID) == .success,
        processID == captured.application.id,
        let targetPoint = center(of: element)
      else { return .failure("The scroll target is no longer in the captured window.") }

      NSRunningApplication(processIdentifier: processID)?.activate()
      let semanticAction = "AXScroll\(direction.capitalized)By\(amount.capitalized)"
      let succeeded: Bool
      if actionNames(element).contains(semanticAction) {
        succeeded = AXUIElementPerformAction(element, semanticAction as CFString) == .success
      } else {
        guard let deltas = Self.scrollDeltas(direction: direction, amount: amount) else {
          return .failure("The requested scroll direction or amount is invalid.")
        }
        guard let event = CGEvent(
          scrollWheelEvent2Source: nil, units: .line, wheelCount: 2,
          wheel1: deltas.vertical, wheel2: deltas.horizontal, wheel3: 0)
        else { return .failure("macOS could not create a bounded scroll event.") }
        event.location = targetPoint
        isSynthesizingInput = true
        event.post(tap: .cghidEventTap)
        try? await Task.sleep(for: .milliseconds(250))
        isSynthesizingInput = false
        succeeded = true
      }
      guard succeeded else {
        return .failure("macOS could not scroll that container. Observe the window again.")
      }
      try? await Task.sleep(for: .milliseconds(250))
      capture()
      armTakeoverMonitoring()
      var result = snapshotValue().objectValue ?? [:]
      result["actionPerformed"] = .string("scroll_\(direction)")
      result["amount"] = .string(amount)
      result["targetLabel"] = .string(control.label)
      result["verifiedAfterAction"] = .bool(snapshot != nil)
      return .success(.object(result))
    }

    private func waitForState(revision: String, seconds: Int) async -> DeviceCallOutcome {
      guard let captured = validatedSnapshot(revision: revision) else {
        return .failure("The Mac window changed or this snapshot expired. Observe it again.")
      }
      let root = AXUIElementCreateApplication(captured.application.id)
      let changed = await DesktopAXChangeWaiter().wait(
        pid: captured.application.id,
        elements: [root, activeWindow(in: root)],
        seconds: seconds)
      refreshApplications()
      guard applications.contains(where: { $0.id == captured.application.id }) else {
        return .failure("The observed Mac app closed while waiting.")
      }
      selectedApplicationID = captured.application.id
      capture()
      armTakeoverMonitoring()
      guard snapshot != nil else {
        return .failure(message ?? "The Mac window could not be observed after waiting.")
      }
      var result = snapshotValue().objectValue ?? [:]
      result["stateChanged"] = .bool(changed)
      result["waitMode"] = .string("accessibility_notifications")
      return .success(.object(result))
    }

    private func validatedSnapshot(revision: String) -> DesktopSnapshot? {
      guard let captured = snapshot, captured.revision == revision,
        Date().timeIntervalSince(captured.capturedAt) < 60,
        selectedApplicationID == captured.application.id,
        NSRunningApplication(processIdentifier: captured.application.id) != nil
      else { return nil }
      let root = AXUIElementCreateApplication(captured.application.id)
      let currentTitle = Self.clean(
        stringAttribute(kAXTitleAttribute, from: activeWindow(in: root)) ?? "Untitled window",
        limit: 100)
      return currentTitle == captured.windowTitle ? captured : nil
    }

    private func snapshotValue() -> JSONValue {
      guard let snapshot else { return .object(["available": .bool(false)]) }
      let controls = snapshot.controls.map { control in
        JSONValue.object([
          "id": .string(control.id),
          "role": .string(control.role),
          "label": .string(control.label),
          "blockedByPolicy": .bool(control.blockedByPolicy),
          "editable": .bool(control.editable),
          "value": control.value.map(JSONValue.string) ?? .null,
          "source": .string(control.source),
          "supportedActions": .array(control.supportedActions.map(JSONValue.string)),
        ])
      }
      var value: [String: JSONValue] = [
        "application": .string(snapshot.application.name),
        "bundleIdentifier": snapshot.application.bundleIdentifier.map(JSONValue.string) ?? .null,
        "windowTitle": .string(snapshot.windowTitle),
        "snapshotRevision": .string(snapshot.revision),
        "expiresInSeconds": .number(60),
        "controls": .array(controls),
      ]
      if let ocrMessage { value["ocrNote"] = .string(ocrMessage) }
      return .object(value)
    }

    private func appendLocalOCR() async {
      guard screenRecordingGranted else {
        ocrMessage = "Local OCR is unavailable until Screen Recording access is granted."
        return
      }
      guard let captured = snapshot else { return }
      do {
        let content = try await SCShareableContent.excludingDesktopWindows(
          false, onScreenWindowsOnly: true)
        guard let window = content.windows.first(where: {
          $0.owningApplication?.processID == captured.application.id
            && ($0.title == captured.windowTitle || captured.windowTitle == "Untitled window")
        }) ?? content.windows.first(where: {
          $0.owningApplication?.processID == captured.application.id
        }) else {
          ocrMessage = "Local OCR could not find the captured app window."
          return
        }
        let observations = try await recognizedText(in: window)
        var controls = captured.controls
        for observation in observations.prefix(40) {
          let label = Self.clean(observation.text, limit: 100)
          guard !label.isEmpty else { continue }
          let id = "ocr_\(controls.count + 1)"
          controls.append(DesktopControlSummary(
            id: id, role: "OCRText", label: label,
            blockedByPolicy: Self.isHighImpact(label: label), source: "local_ocr",
            supportedActions: ["press"]))
          ocrTargets[id] = OCRTarget(
            label: label, normalizedBounds: observation.bounds,
            windowID: window.windowID, windowFrame: window.frame)
        }
        snapshot = DesktopSnapshot(
          revision: captured.revision, application: captured.application,
          windowTitle: captured.windowTitle, capturedAt: captured.capturedAt,
          controls: controls)
        ocrMessage = observations.isEmpty
          ? "Local OCR found no additional visible text."
          : "OCR ran locally; no screenshot was uploaded or retained."
      } catch {
        ocrMessage = "Local OCR was unavailable: \(error.localizedDescription)"
      }
    }

    private func pressOCRTarget(_ target: OCRTarget, application: DesktopApplication) async
      -> Bool
    {
      guard screenRecordingGranted else { return false }
      do {
        let content = try await SCShareableContent.excludingDesktopWindows(
          false, onScreenWindowsOnly: true)
        guard let window = content.windows.first(where: {
          $0.windowID == target.windowID
            && $0.owningApplication?.processID == application.id
        }) else { return false }
        let matches = try await recognizedText(in: window).filter {
          Self.clean($0.text, limit: 100) == target.label
            && Self.overlap($0.bounds, target.normalizedBounds) > 0.7
        }
        guard matches.count == 1, let match = matches.first else { return false }
        let point = CGPoint(
          x: window.frame.minX + match.bounds.midX * window.frame.width,
          y: window.frame.minY + (1 - match.bounds.midY) * window.frame.height)
        NSRunningApplication(processIdentifier: application.id)?.activate()
        guard let down = CGEvent(
          mouseEventSource: nil, mouseType: .leftMouseDown,
          mouseCursorPosition: point, mouseButton: .left),
          let up = CGEvent(
            mouseEventSource: nil, mouseType: .leftMouseUp,
            mouseCursorPosition: point, mouseButton: .left)
        else { return false }
        isSynthesizingInput = true
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        try? await Task.sleep(for: .milliseconds(250))
        isSynthesizingInput = false
        return true
      } catch {
        return false
      }
    }

    private func recognizedText(in window: SCWindow) async throws
      -> [(text: String, bounds: CGRect)]
    {
      let configuration = SCStreamConfiguration()
      configuration.width = max(Int(window.frame.width * 2), 1)
      configuration.height = max(Int(window.frame.height * 2), 1)
      configuration.showsCursor = false
      let image = try await SCScreenshotManager.captureImage(
        contentFilter: SCContentFilter(desktopIndependentWindow: window),
        configuration: configuration)
      let request = VNRecognizeTextRequest()
      request.recognitionLevel = .accurate
      request.usesLanguageCorrection = true
      try VNImageRequestHandler(cgImage: image).perform([request])
      return (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first?.string else { return nil }
        return (text, observation.boundingBox)
      }
    }

    private static func overlap(_ left: CGRect, _ right: CGRect) -> CGFloat {
      let intersection = left.intersection(right)
      guard !intersection.isNull else { return 0 }
      let denominator = max(left.width * left.height, right.width * right.height)
      return denominator > 0 ? intersection.width * intersection.height / denominator : 0
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
        "allow", "approve", "buy", "checkout", "confirm", "credential", "credentials",
        "delete", "erase", "grant", "install", "ok", "password", "pay", "post",
        "publish", "purchase", "secret", "token",
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

      let editable = [kAXTextFieldRole as String, kAXTextAreaRole as String].contains(role)
        && attributeIsSettable(kAXValueAttribute, on: element)
      let availableActions = actionNames(element)
      let semanticActions = Self.semanticActions(availableActions)
      let scrollableRoles: Set<String> = [
        "AXScrollArea", "AXTable", "AXList", "AXOutline", "AXWebArea",
      ]
      let scrollable = scrollableRoles.contains(role)
      if (editable || !semanticActions.isEmpty || scrollable),
        boolAttribute(kAXEnabledAttribute, from: element) != false,
        let resolvedLabel = label?.isEmpty == false ? label : Self.friendlyRoleName(role)
      {
        let id = "control_\(controls.count + 1)"
        let summary = DesktopControlSummary(
          id: id, role: role, label: Self.clean(resolvedLabel, limit: 100),
          blockedByPolicy: !editable && Self.isHighImpact(label: resolvedLabel),
          editable: editable,
          value: valueDescription(kAXValueAttribute, from: element).map {
            Self.clean($0, limit: 500)
          },
          supportedActions: semanticActions + (scrollable ? ["scroll"] : []))
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

    private func valueDescription(_ name: String, from element: AXUIElement) -> String? {
      var value: CFTypeRef?
      guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success,
        let value
      else { return nil }
      if let string = value as? String { return string }
      if let number = value as? NSNumber { return number.stringValue }
      return nil
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

    private func attributeIsSettable(_ name: String, on element: AXUIElement) -> Bool {
      var value = DarwinBoolean(false)
      return AXUIElementIsAttributeSettable(element, name as CFString, &value) == .success
        && value.boolValue
    }

    private func center(of element: AXUIElement) -> CGPoint? {
      var positionValue: CFTypeRef?
      var sizeValue: CFTypeRef?
      guard AXUIElementCopyAttributeValue(
        element, kAXPositionAttribute as CFString, &positionValue) == .success,
        AXUIElementCopyAttributeValue(
          element, kAXSizeAttribute as CFString, &sizeValue) == .success,
        let positionValue, let sizeValue,
        CFGetTypeID(positionValue) == AXValueGetTypeID(),
        CFGetTypeID(sizeValue) == AXValueGetTypeID()
      else { return nil }
      var position = CGPoint.zero
      var size = CGSize.zero
      guard AXValueGetValue(positionValue as! AXValue, .cgPoint, &position),
        AXValueGetValue(sizeValue as! AXValue, .cgSize, &size),
        size.width > 0, size.height > 0
      else { return nil }
      return CGPoint(x: position.x + size.width / 2, y: position.y + size.height / 2)
    }

    static func accessibilityAction(
      _ requested: String, supportedActions: [String]
    ) -> String? {
      let mapping = [
        "press": kAXPressAction as String,
        "increment": kAXIncrementAction as String,
        "decrement": kAXDecrementAction as String,
        "show_menu": kAXShowMenuAction as String,
      ]
      guard let action = mapping[requested], supportedActions.contains(requested) else {
        return nil
      }
      return action
    }

    static func scrollDeltas(
      direction: String, amount: String
    ) -> (vertical: Int32, horizontal: Int32)? {
      guard ["line", "page"].contains(amount) else { return nil }
      let magnitude: Int32 = amount == "page" ? 12 : 3
      switch direction {
      case "up": return (magnitude, 0)
      case "down": return (-magnitude, 0)
      case "left": return (0, magnitude)
      case "right": return (0, -magnitude)
      default: return nil
      }
    }

    private static func semanticActions(_ actions: [String]) -> [String] {
      let mapping = [
        (kAXPressAction as String, "press"),
        (kAXIncrementAction as String, "increment"),
        (kAXDecrementAction as String, "decrement"),
        (kAXShowMenuAction as String, "show_menu"),
      ]
      return mapping.compactMap { actions.contains($0.0) ? $0.1 : nil }
    }

    private static func friendlyRoleName(_ role: String) -> String {
      let stripped = role.hasPrefix("AX") ? String(role.dropFirst(2)) : role
      return stripped.replacingOccurrences(
        of: "([a-z])([A-Z])", with: "$1 $2", options: .regularExpression)
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
