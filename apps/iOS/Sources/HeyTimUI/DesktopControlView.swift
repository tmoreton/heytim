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
        LabeledContent("Local model", value: coordinator.modelState.title)
        if let message = coordinator.permissionMessage {
          Text(message).foregroundStyle(.secondary)
        }
      } header: {
        Text("Mac App Actions")
      } footer: {
        Text("With Accessibility access granted, Laya checks text-only Mac chat drafts before they go to a bot. You can open Mac app actions from any conversation; every button press needs your approval.")
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

  struct DesktopActionCard: View {
    @Bindable var coordinator: DesktopControlCoordinator
    let onSendToBot: () -> Void
    let onOpenSettings: () -> Void
    let onClose: () -> Void

    var body: some View {
      VStack(alignment: .leading, spacing: 16) {
        header
        if !coordinator.isEnabled || !coordinator.permissionGranted {
          Label(
            coordinator.isEnabled
              ? "Enable Accessibility access in Settings before using Mac app actions."
              : "Enable Mac app actions in Settings before using this tool.",
            systemImage: "hand.raised")
            .foregroundStyle(.secondary)
          Button("Open Settings") { onOpenSettings() }
        }
        target
        capturedControls
        if let proposal = coordinator.proposal { proposalCard(proposal) }
        if let message = coordinator.message {
          Text(message).foregroundStyle(.secondary).textSelection(.enabled)
        }
        HStack {
          Button("Dismiss") { onClose() }
          Spacer()
          Button("Send to Bot Instead") { onSendToBot() }
        }
      }
      .padding(18)
      .frame(maxWidth: 720, alignment: .leading)
      .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 16))
      .overlay(RoundedRectangle(cornerRadius: 16).stroke(FrogTheme.border))
    }

    private var header: some View {
      VStack(alignment: .leading, spacing: 6) {
        Text("Mac App Action").froggyFont(.title, weight: .bold)
        Text("Laya can suggest a visible button. Review the exact action before Hey Tim presses it.")
          .foregroundStyle(.secondary)
      }
    }

    private var target: some View {
      GroupBox("Choose a visible action") {
        VStack(alignment: .leading, spacing: 12) {
          Picker("Application", selection: $coordinator.selectedApplicationID) {
            Text("Choose an app").tag(pid_t?.none)
            ForEach(coordinator.applications) { application in
              Text(application.name).tag(pid_t?.some(application.id))
            }
          }
          HStack {
            TextField("What should Hey Tim do?", text: $coordinator.intent)
              .textFieldStyle(.roundedBorder)
            Button("Capture") { coordinator.capture() }
              .disabled(!coordinator.isEnabled || !coordinator.permissionGranted)
            Button("Recommend") { Task { await coordinator.recommend() } }
              .buttonStyle(.borderedProminent)
              .disabled(!coordinator.isEnabled || !coordinator.permissionGranted || coordinator.isWorking || coordinator.modelState != .ready)
          }
        }.padding(8)
      }
    }

    @ViewBuilder private var capturedControls: some View {
      if let snapshot = coordinator.snapshot {
        GroupBox("Captured from \(snapshot.application.name) — \(snapshot.windowTitle)") {
          VStack(alignment: .leading, spacing: 8) {
            if snapshot.controls.isEmpty {
              Text("No pressable controls found.").foregroundStyle(.secondary)
            } else {
              ForEach(snapshot.controls) { control in
                HStack {
                  Image(systemName: control.blockedByPolicy ? "exclamationmark.shield" : "button.programmable")
                  Text(control.label)
                  Spacer()
                  Text(control.blockedByPolicy ? "Cloud review required" : "Eligible for preview")
                    .font(.caption).foregroundStyle(.secondary)
                }
              }
            }
            DisclosureGroup("Semantic snapshot") {
              Text(snapshot.summary)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 6)
            }
          }.padding(8)
        }
      }
    }

    private func proposalCard(_ proposal: DesktopActionProposal) -> some View {
      GroupBox("Decision preview") {
        VStack(alignment: .leading, spacing: 10) {
          if let control = proposal.control {
            Text("Press “\(control.label)” in \(coordinator.snapshot?.application.name ?? "the selected app")")
              .fontWeight(.semibold)
          } else {
            Label("Needs larger-model review", systemImage: "arrow.up.right.circle")
              .fontWeight(.semibold)
            Text("Nothing has been sent to the cloud or executed. You can use the conversation to ask for help.")
              .font(.caption).foregroundStyle(.secondary)
          }
          Text(proposal.reason).foregroundStyle(.secondary)
          Text("Decision confidence \(proposal.confidence, format: .percent.precision(.fractionLength(0))) · local-action score \(proposal.actionProbability, format: .percent.precision(.fractionLength(0)))")
            .font(.caption).foregroundStyle(.secondary)
          if proposal.canExecute {
            Button("Approve and press this control") {
              coordinator.executeApprovedProposal()
            }
            .buttonStyle(.borderedProminent)
            .disabled(!coordinator.isEnabled)
          }
        }.padding(8)
      }
    }
  }
#endif
