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
    let summary: String
    let controls: [DesktopControlSummary]
  }

  struct DesktopActionProposal: Equatable, Sendable {
    let control: DesktopControlSummary?
    let confidence: Float
    let actionProbability: Float
    let reason: String

    var canExecute: Bool { control != nil }
  }

  @MainActor @Observable
  final class DesktopControlCoordinator {
    enum ModelState: Equatable {
      case loading
      case ready
      case failed(String)

      var title: String {
        switch self {
        case .loading: "Loading on device…"
        case .ready: "Ready"
        case .failed(let message): message
        }
      }
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
    var intent = "" {
      didSet {
        if intent != oldValue { proposal = nil }
      }
    }
    var snapshot: DesktopSnapshot?
    var proposal: DesktopActionProposal?
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
    var permissionGranted = AXIsProcessTrusted()
    var permissionRequestPending = false
    var restartPrompt = false
    var modelState: ModelState = .loading
    var isWorking = false
    var message: String?
    var permissionMessage: String?

    @ObservationIgnored private var elements: [String: AXUIElement] = [:]
    @ObservationIgnored private var laya: LayaManager?
    init() {
      refreshApplications()
      Task { await loadBundledModel() }
    }

    func prepare(intent: String) {
      self.intent = intent.trimmingCharacters(in: .whitespacesAndNewlines)
      refreshApplications()
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
      let window = elementAttribute(kAXFocusedWindowAttribute, from: root) ?? root
      let windowTitle = stringAttribute(kAXTitleAttribute, from: window) ?? "Untitled window"
      var lines: [String] = []
      var controls: [DesktopControlSummary] = []
      var resolved: [String: AXUIElement] = [:]
      var visited = 0
      walk(
        window, depth: 0, visited: &visited, lines: &lines,
        controls: &controls, resolved: &resolved)

      elements = resolved
      snapshot = DesktopSnapshot(
        application: application,
        windowTitle: Self.clean(windowTitle, limit: 100),
        summary: lines.prefix(80).joined(separator: "\n"),
        controls: Array(controls.prefix(12)))
      if controls.isEmpty {
        message = "No pressable controls were found in the focused window."
      }
    }

    func recommend() async {
      guard isEnabled else {
        message = "Enable Mac app actions in Settings before requesting a recommendation."
        return
      }
      if snapshot == nil { capture() }
      guard let snapshot else { return }
      guard !intent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        message = "Describe what you want to do first."
        return
      }
      guard let laya else {
        proposal = .init(
          control: nil, confidence: 0, actionProbability: 0,
          reason: "The local model is unavailable, so this request needs the larger model.")
        return
      }

      isWorking = true
      proposal = nil
      defer { isWorking = false }
      do {
        let candidates = Array(snapshot.controls.prefix(4))
        guard !candidates.isEmpty else {
          proposal = .init(
            control: nil, confidence: 0, actionProbability: 0,
            reason: "No pressable controls were visible, so this request needs the larger model.")
          return
        }
        let options = candidates.map {
          LayaQuestion.Choice($0.id, description: "Press \(Self.clean($0.label, limit: 48))")
        } + [LayaQuestion.Choice("use_cloud_model", description: "No safe visible control is a clear match")]
        let state = [
          "intent: \(Self.clean(intent, limit: 160))",
          "app: \(Self.clean(snapshot.application.name, limit: 48))",
          "window: \(Self.clean(snapshot.windowTitle, limit: 64))",
        ].joined(separator: "\n")
        let answer = try await laya.answer(
          state: state,
          question: .choice(
            "Choose the safe visible control that best completes the intent. Use cloud when unsure.",
            options: options))
        guard isEnabled, self.snapshot == snapshot else { return }
        let selected = candidates.first(where: { $0.id == answer.selectedLabel })
        let locallyEligible = selected != nil
          && selected?.blockedByPolicy == false
          && !answer.stateWasTruncated
          && answer.actionProbability >= 0.70
          && answer.confidence >= 0.20
        let reason: String
        if answer.selectedLabel == "use_cloud_model" {
          reason = "Laya chose the larger model because no safe visible control was a clear match."
        } else if selected?.blockedByPolicy == true {
          reason = "This control can have an external or destructive effect, so local execution is blocked."
        } else if answer.stateWasTruncated {
          reason = "The decision input did not fit the local model, so it was rejected."
        } else if !locallyEligible {
          reason = "The local confidence gate was not met, so this request needs the larger model."
        } else {
          reason = "Laya selected this visible control. Review the exact action before approving it."
        }
        proposal = .init(
          control: locallyEligible ? selected : nil,
          confidence: answer.confidence,
          actionProbability: answer.actionProbability,
          reason: reason)
      } catch {
        proposal = .init(
          control: nil, confidence: 0, actionProbability: 0,
          reason: "The local decision failed safely: \(error.localizedDescription)")
      }
    }

    /// A non-authoritative first pass for every Mac text send. A positive result
    /// only offers the local tool; the user can still send the draft to the bot.
    func shouldOfferDesktopAction(for text: String) async -> Bool {
      guard isEnabled, AXIsProcessTrusted(), let laya else { return false }
      let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmed.isEmpty else { return false }
      do {
        let answer = try await laya.answer(
          state: "user request: \(Self.clean(trimmed, limit: 180))",
          question: .choice(
            "Does this request ask to operate an app on this Mac, or should a bot answer it?",
            options: [
              .init("mac_app", description: "Operate a visible Mac application"),
              .init("bot_reply", description: "Answer in the bot conversation"),
              .init("uncertain", description: "Unclear; let the bot handle it"),
            ]))
        return Self.explicitlyTargetsMacUI(trimmed)
          && answer.selectedLabel == "mac_app"
          && !answer.stateWasTruncated
          && answer.actionProbability >= 0.85
          && answer.confidence >= 0.75
      } catch {
        return false
      }
    }

    static func explicitlyTargetsMacUI(_ text: String) -> Bool {
      let value = text.lowercased()
      return [
        "my mac", "this mac", "mac app", "desktop app", "on my screen",
        "on the screen",
      ].contains(where: value.contains)
    }

    func executeApprovedProposal() {
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
        return
      }
      NSRunningApplication(processIdentifier: application.id)?.activate()
      let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
      proposal = nil
      if result == .success {
        capture()
        message = "Approved action completed: \(control.label)."
      } else {
        message = "macOS could not press that control. Capture a fresh snapshot and try again."
      }
    }

    static func isHighImpact(label: String) -> Bool {
      let normalized = label.lowercased()
      let blocked = [
        "allow", "approve", "buy", "checkout", "confirm", "delete", "erase",
        "grant", "install", "ok", "pay", "post", "publish", "purchase",
        "remove", "send", "share", "submit", "transfer", "yes",
      ]
      return blocked.contains { normalized == $0 || normalized.contains("\($0) ") || normalized.contains(" \($0)") }
    }

    private func loadBundledModel() async {
      do {
        guard let directory = Bundle.main.resourceURL?.appendingPathComponent(
          "laya-coreml", isDirectory: true),
          FileManager.default.fileExists(
            atPath: directory.appendingPathComponent("tokenizer.json").path)
        else {
          modelState = .failed("Bundled model is missing. Reinstall Hey Tim.")
          return
        }
        laya = try await LayaManager.load(
          from: directory,
          configuration: .init(lengths: [128], precision: "e8"))
        modelState = .ready
      } catch {
        modelState = .failed(error.localizedDescription)
      }
    }

    private func walk(
      _ element: AXUIElement,
      depth: Int,
      visited: inout Int,
      lines: inout [String],
      controls: inout [DesktopControlSummary],
      resolved: inout [String: AXUIElement]
    ) {
      guard depth <= 7, visited < 180, controls.count < 12 else { return }
      visited += 1
      let role = stringAttribute(kAXRoleAttribute, from: element) ?? "element"
      let label = stringAttribute(kAXTitleAttribute, from: element)
        ?? stringAttribute(kAXDescriptionAttribute, from: element)
        ?? stringAttribute(kAXHelpAttribute, from: element)
      if let label, !label.isEmpty {
        lines.append("\(role): \(Self.clean(label, limit: 100))")
      }

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

      for child in elementArrayAttribute(kAXChildrenAttribute, from: element) {
        walk(
          child, depth: depth + 1, visited: &visited, lines: &lines,
          controls: &controls, resolved: &resolved)
      }
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
