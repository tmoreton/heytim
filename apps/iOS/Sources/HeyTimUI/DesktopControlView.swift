#if os(macOS)
  import AppKit
  import SwiftUI

  struct DesktopControlSettingsSection: View {
    @Bindable var coordinator: DesktopControlCoordinator
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
      Section {
        Toggle("Enable Mac app actions", isOn: $coordinator.isEnabled)
          .accessibilityIdentifier("settings.desktop-control.enabled")
        LabeledContent {
          Text(coordinator.permissionGranted ? "Granted" : "Not granted")
            .foregroundStyle(coordinator.permissionGranted ? Color.green : Color.secondary)
        } label: {
          Label("Accessibility", systemImage: "hand.raised")
        }
        HStack {
          if !coordinator.permissionGranted {
            Button("Request Access") { coordinator.requestAccessibilityPermission() }
            Button("Open macOS Settings") { coordinator.openAccessibilitySettings() }
          }
          Button("Refresh Status") { coordinator.refreshPermissionAfterSettings() }
        }
        .disabled(!coordinator.isEnabled)
        if coordinator.isEnabled && !coordinator.permissionGranted {
          Text("If Hey Tim is already on in macOS Accessibility settings but access is still missing, remove that entry and add this exact app copy again, then quit and reopen.")
            .foregroundStyle(.secondary)
          Button("Show This App in Finder") { coordinator.revealCurrentApplication() }
        }
        if let message = coordinator.permissionMessage {
          Text(message).foregroundStyle(.secondary)
        }
      } header: {
        Text("Mac App Actions")
      } footer: {
        Text("Turn this on, then enable Mac app actions for individual bots in their Tools list. Supported actions use Accessibility and require your approval before changing another app.")
      }
      .alert("Reopen Hey Tim?", isPresented: $coordinator.restartPrompt) {
        Button("Quit and Reopen") { coordinator.restartForAccessibility() }
        Button("Later", role: .cancel) {}
      } message: {
        Text("If you just enabled Hey Tim in macOS Accessibility settings, reopen the app so the new permission takes effect.")
      }
      .onChange(of: scenePhase) { _, phase in
        if phase == .active { coordinator.refreshPermissionAfterSettings() }
      }
      .onReceive(NotificationCenter.default.publisher(
        for: NSApplication.didBecomeActiveNotification)) { _ in
          coordinator.refreshPermissionAfterSettings()
        }
    }
  }

#endif
