#if os(macOS)
  import AppKit
  import ApplicationServices
  import Foundation

  enum DesktopAXCaptureError: LocalizedError {
    case read(attribute: String, code: AXError)
    case unexpectedType(attribute: String)
    case noWindow

    var errorDescription: String? {
      switch self {
      case .read(let attribute, let code):
        return "macOS could not read \(attribute) (AX error \(code.rawValue)). Try a fresh observation."
      case .unexpectedType(let attribute):
        return "macOS returned an unexpected value for \(attribute). Try a fresh observation."
      case .noWindow:
        return "The app has no accessible window to inspect. Open a window and try again."
      }
    }
  }

  /// Only cosmetic control-label .failure may be omitted; window, identity, tree and safety reads stay strict.
  /// Injection keeps capture tests independent of running apps and macOS permissions.
  @MainActor struct DesktopAXReader {
    var copyAttribute: (AXUIElement, String) -> (AXError, CFTypeRef?)
    var copyActions: (AXUIElement) -> (AXError, CFArray?)
    var isSettable: (AXUIElement, String) -> (AXError, Bool)

    static let live = DesktopAXReader(
      copyAttribute: { element, name in
        var value: CFTypeRef?
        let error = AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return (error, value)
      },
      copyActions: { element in
        var names: CFArray?
        let error = AXUIElementCopyActionNames(element, &names)
        return (error, names)
      },
      isSettable: { element, name in
        var value = DarwinBoolean(false)
        let error = AXUIElementIsAttributeSettable(element, name as CFString, &value)
        return (error, value.boolValue)
      })

    func attribute(_ name: String, from element: AXUIElement) throws -> CFTypeRef? {
      let (error, value) = copyAttribute(element, name)
      if error == .noValue || error == .attributeUnsupported { return nil }
      guard error == .success else { throw DesktopAXCaptureError.read(attribute: name, code: error) }
      return value
    }

    func string(_ name: String, from element: AXUIElement) throws -> String? {
      guard let value = try attribute(name, from: element) else { return nil }
      guard let string = value as? String else {
        throw DesktopAXCaptureError.unexpectedType(attribute: name)
      }
      return string
    }

    /// A failed cosmetic label must not hide readable text or become an action label.
    /// Stale elements, permission/messaging failures and malformed values still fail capture.
    func controlLabel(on element: AXUIElement) throws -> (text: String?, incomplete: Bool) {
      var incomplete = false
      for name in [kAXTitleAttribute as String, kAXDescriptionAttribute as String, kAXHelpAttribute as String] {
        do {
          if let text = try string(name, from: element) { return (text, incomplete) }
        } catch DesktopAXCaptureError.read(_, let code) where code == .failure {
          incomplete = true
        }
      }
      return (nil, incomplete)
    }

    func bool(_ name: String, from element: AXUIElement) throws -> Bool? {
      guard let value = try attribute(name, from: element) else { return nil }
      guard let bool = value as? Bool else {
        throw DesktopAXCaptureError.unexpectedType(attribute: name)
      }
      return bool
    }

    func element(_ name: String, from parent: AXUIElement) throws -> AXUIElement? {
      guard let value = try attribute(name, from: parent) else { return nil }
      guard CFGetTypeID(value) == AXUIElementGetTypeID() else {
        throw DesktopAXCaptureError.unexpectedType(attribute: name)
      }
      return (value as! AXUIElement)
    }

    func elements(_ name: String, from parent: AXUIElement) throws -> [AXUIElement] {
      guard let value = try attribute(name, from: parent) else { return [] }
      guard CFGetTypeID(value) == CFArrayGetTypeID(), let elements = value as? [AXUIElement] else {
        throw DesktopAXCaptureError.unexpectedType(attribute: name)
      }
      return elements
    }

    func actions(on element: AXUIElement) throws -> [String] {
      let (error, value) = copyActions(element)
      if error == .noValue || error == .attributeUnsupported { return [] }
      guard error == .success else {
        throw DesktopAXCaptureError.read(attribute: "AXActions", code: error)
      }
      guard let value else { return [] }
      guard let actions = value as? [String] else {
        throw DesktopAXCaptureError.unexpectedType(attribute: "AXActions")
      }
      return actions
    }

    func editable(_ name: String, on element: AXUIElement) throws -> Bool {
      let (error, value) = isSettable(element, name)
      if error == .noValue || error == .attributeUnsupported { return false }
      guard error == .success else {
        throw DesktopAXCaptureError.read(attribute: "\(name) settable", code: error)
      }
      return value
    }

    func window(in application: AXUIElement) throws -> AXUIElement {
      var firstError: Error?
      for name in [kAXFocusedWindowAttribute as String, kAXMainWindowAttribute as String] {
        do {
          if let candidate = try element(name, from: application),
            try string(kAXRoleAttribute, from: candidate) == kAXWindowRole as String
          { return candidate }
        } catch { firstError = firstError ?? error }
      }
      do {
        for candidate in try elements(kAXWindowsAttribute, from: application) {
          if try string(kAXRoleAttribute, from: candidate) == kAXWindowRole as String {
            return candidate
          }
        }
      } catch { firstError = firstError ?? error }
      throw firstError ?? DesktopAXCaptureError.noWindow
    }

    func windowTitle(_ window: AXUIElement) throws -> String {
      try string(kAXTitleAttribute, from: window) ?? "Untitled window"
    }
  }

  extension DesktopControlCoordinator {
    static func readAccessibility(
      application: DesktopApplication, root: AXUIElement, reader: DesktopAXReader = .live
    ) throws -> (snapshot: DesktopSnapshot, elements: [String: AXUIElement]) {
      let window = try reader.window(in: root)
      let title = try reader.windowTitle(window)
      var controls: [DesktopControlSummary] = []
      var resolved: [String: AXUIElement] = [:]
      var visited = 0
      try walkAccessibility(
        window, reader: reader, depth: 0, visited: &visited,
        controls: &controls, resolved: &resolved)
      return (DesktopSnapshot(
        revision: UUID().uuidString.lowercased(), application: application,
        windowTitle: clean(title, limit: 100), capturedAt: Date(), controls: controls), resolved)
    }

    private static func walkAccessibility(
      _ element: AXUIElement,
      reader: DesktopAXReader,
      depth: Int,
      visited: inout Int,
      controls: inout [DesktopControlSummary],
      resolved: inout [String: AXUIElement]
    ) throws {
      guard depth <= 7, visited < 180, controls.count < 60 else { return }
      visited += 1
      guard let role = try reader.string(kAXRoleAttribute, from: element) else {
        throw DesktopAXCaptureError.read(attribute: kAXRoleAttribute, code: .noValue)
      }
      // Secure fields are never included in the model's candidate tree.
      guard role != "AXSecureTextField", try reader.bool("AXVisible", from: element) != false else {
        return
      }
      let editable = try [kAXTextFieldRole as String, kAXTextAreaRole as String].contains(role)
        && reader.editable(kAXValueAttribute, on: element)
      let semanticActions = semanticActions(try reader.actions(on: element))
      let scrollable = ["AXScrollArea", "AXTable", "AXList", "AXOutline", "AXWebArea"].contains(role)
      if (editable || !semanticActions.isEmpty || scrollable),
        try reader.bool(kAXEnabledAttribute, from: element) != false
      {
        let label = try reader.controlLabel(on: element)
        let readableLabel = label.text?.isEmpty == false ? label.text : nil
        if editable || (!label.incomplete && (readableLabel != nil || scrollable)) {
          let resolvedLabel = readableLabel ?? friendlyRoleName(role)
          let id = "control_\(controls.count + 1)"
          let value = try reader.attribute(kAXValueAttribute, from: element)
          let valueText = (value as? String) ?? (value as? NSNumber)?.stringValue
          controls.append(DesktopControlSummary(
            id: id, role: role, label: clean(resolvedLabel, limit: 100),
            blockedByPolicy: !editable && isHighImpact(label: resolvedLabel), editable: editable,
            value: valueText.map { clean($0, limit: 500) },
            supportedActions: (readableLabel == nil || label.incomplete ? [] : semanticActions)
              + (scrollable && !label.incomplete ? ["scroll"] : [])))
          resolved[id] = element
        }
      }
      let children = try reader.elements(kAXChildrenAttribute, from: element)
      // Large document/list subtrees must not crowd out the window toolbar.
      let ordered = try children.filter { try reader.string(kAXRoleAttribute, from: $0) == "AXToolbar" }
        + children.filter { try reader.string(kAXRoleAttribute, from: $0) != "AXToolbar" }
      for child in ordered {
        try walkAccessibility(
          child, reader: reader, depth: depth + 1, visited: &visited,
          controls: &controls, resolved: &resolved)
      }
    }
  }
#endif
