#if os(macOS)
  import AppKit
  import SwiftUI

  struct DesktopControlSettingsSection: View {
    @Bindable var coordinator: DesktopControlCoordinator
    @Environment(AppleDeviceToolCoordinator.self) private var deviceTools
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
      Section {
        Toggle("Enable Mac app actions", isOn: $coordinator.isEnabled)
          .accessibilityIdentifier("settings.desktop-control.enabled")
        LabeledContent {
          Text(coordinator.isPaused ? "Paused" : "Ready")
            .foregroundStyle(coordinator.isPaused ? FrogTheme.muted : FrogTheme.text)
        } label: {
          Label("Computer use", systemImage: coordinator.isPaused ? "pause.circle" : "play.circle")
        }
        if coordinator.isPaused {
          Button("Resume Computer Use") {
            coordinator.resumeComputerUse()
            deviceTools.refreshNow()
          }
          .accessibilityIdentifier("settings.desktop-control.resume")
        } else {
          Button("Pause Computer Use") {
            coordinator.pauseComputerUse()
            deviceTools.refreshNow()
          }
          .disabled(!coordinator.isEnabled)
          .accessibilityIdentifier("settings.desktop-control.pause")
        }
        if let takeoverMessage = coordinator.takeoverMessage {
          Text(takeoverMessage).foregroundStyle(.secondary)
        }
        LabeledContent {
          Text(coordinator.permissionGranted ? "Granted" : "Not granted")
            .foregroundStyle(coordinator.permissionGranted ? FrogTheme.text : FrogTheme.muted)
        } label: {
          Label("Accessibility", systemImage: "hand.raised")
        }
        LabeledContent {
          Text(coordinator.screenRecordingGranted ? "Granted" : "Optional")
            .foregroundStyle(coordinator.screenRecordingGranted ? FrogTheme.text : FrogTheme.muted)
        } label: {
          Label("Local OCR", systemImage: "text.viewfinder")
        }
        HStack {
          if !coordinator.permissionGranted {
            Button("Request Access") { coordinator.requestAccessibilityPermission() }
            Button("Open macOS Settings") { coordinator.openAccessibilitySettings() }
          }
          Button("Refresh Status") { coordinator.refreshPermissionAfterSettings() }
        }
        .disabled(!coordinator.isEnabled)
        if coordinator.isEnabled && !coordinator.screenRecordingGranted {
          Button("Allow Local OCR") { coordinator.requestScreenRecordingPermission() }
          Text("Screen Recording access lets Hey Tim recognize unlabeled text locally. Screenshots are neither uploaded nor retained.")
            .foregroundStyle(.secondary)
        }
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
        Text("Turn this on, then enable Mac app actions for individual bots in their Tools list. Keyboard, mouse, or trackpad input during an active session pauses computer use immediately. Consequential controls stay blocked.")
      }
      .alert("Reopen Hey Tim?", isPresented: $coordinator.restartPrompt) {
        Button("Quit and Reopen") { coordinator.restartForAccessibility() }
        Button("Later", role: .cancel) {}
      } message: {
        Text("If you just enabled Hey Tim in macOS Accessibility settings, reopen the app so the new permission takes effect.")
      }
      .onChange(of: scenePhase) { _, phase in
        if phase == .active {
          coordinator.refreshPermissionAfterSettings()
          deviceTools.refreshNow()
        }
      }
      .onChange(of: coordinator.isEnabled) { _, _ in
        deviceTools.refreshNow()
      }
      .onReceive(NotificationCenter.default.publisher(
        for: NSApplication.didBecomeActiveNotification)) { _ in
          coordinator.refreshPermissionAfterSettings()
        }
    }
  }

#endif

#if os(iOS)
  import SwiftUI

  struct AppleHealthSettingsSection: View {
    @Bindable var coordinator: AppleHealthCoordinator
    @State private var overview: AppleHealthCoordinator.LocalOverview?
    @State private var loading = false

    var body: some View {
      Section {
        LabeledContent {
          Text(coordinator.permissionRequested ? "Requested" : "Not requested")
            .foregroundStyle(coordinator.permissionRequested ? FrogTheme.text : FrogTheme.muted)
        } label: {
          Label("Health access", systemImage: "heart.text.square")
        }
        Button {
          Task {
            loading = true
            overview = await coordinator.localOverview()
            loading = false
          }
        } label: {
          if loading {
            Label("Reading Apple Health…", systemImage: "heart.text.square")
          } else {
            Label("View Health Summary", systemImage: "heart.text.square")
          }
        }
        .disabled(!coordinator.isAvailable || loading)
        .accessibilityIdentifier("settings.apple-health.local-summary")
        if loading { ProgressView() }
        if let overview {
          LabeledContent("Steps · last 7 days") {
            Text(overview.stepCount.map(String.init) ?? "No data")
          }
          LabeledContent("Days with step data", value: String(overview.stepDays))
          LabeledContent("Workouts · last 30 days", value: String(overview.workoutCount))
          LabeledContent("Runs · last 90 days", value: String(overview.runningCount))
          LabeledContent("Running distance · last 90 days") {
            Text(String(format: "%.1f km", overview.runningKilometers))
          }
          Text("These summaries are calculated and displayed on this iPhone. They are not sent to HeyTim or an AI provider.")
            .froggyFont(.footnote).foregroundStyle(.secondary)
        }
        if let error = coordinator.errorMessage {
          Text(error).foregroundStyle(FrogTheme.danger)
        }
      } header: {
        Text("Apple Health")
      } footer: {
        Text("Apple’s permission sheet controls which read-only data this iPhone can use. Health summaries stay on this device; bots cannot access them.")
      }
    }
  }
#endif
