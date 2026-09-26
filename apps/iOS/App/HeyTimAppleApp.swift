import SwiftUI

@main
struct HeyTimAppleApp: App {
  #if os(iOS)
    @UIApplicationDelegateAdaptor(FroggyAppDelegate.self) private var appDelegate
  #elseif os(macOS)
    @NSApplicationDelegateAdaptor(FroggyAppDelegate.self) private var appDelegate
  #endif

  private let configuration: AppConfiguration?
  private let configurationError: String?
  @State private var auth: AuthSession?
  @State private var model: AppModel
  @State private var deviceTools = AppleDeviceToolCoordinator()
  #if os(iOS)
    @State private var appleHealth = AppleHealthCoordinator()
  #endif
  #if os(macOS)
    @State private var desktopControl = DesktopControlCoordinator()
    private let updateController = DesktopUpdateController.shared
  #endif

  init() {
    do {
      let value = try AppConfiguration.load()
      configuration = value
      configurationError = nil
      _auth = State(initialValue: AuthSession(configuration: value))
    } catch {
      configuration = nil
      configurationError = error.localizedDescription
      _auth = State(initialValue: nil)
    }
    #if DEBUG
      let demoMode = ProcessInfo.processInfo.arguments.contains("--ui-testing")
    #else
      let demoMode = false
    #endif
    _model = State(initialValue: AppModel(demoMode: demoMode))
  }

  var body: some Scene {
    #if os(macOS)
      WindowGroup {
        Group {
          if let configuration, let auth {
            AppRoot(configuration: configuration, auth: auth, model: model)
              .frame(minWidth: auth.phase == .signedIn ? 1_160 : 900, minHeight: 620)
          } else {
            configurationFailure
          }
        }
        .environment(deviceTools)
        .environment(desktopControl)
      }
      .defaultSize(width: 1200, height: 760)
      .windowStyle(.hiddenTitleBar)
      .windowResizability(.contentMinSize)
      .commands {
        CommandGroup(after: .appInfo) {
          Button("Check for Updates…") { updateController.checkForUpdates() }
            .disabled(!updateController.isConfigured)
        }
        CommandGroup(replacing: .appSettings) {
          Button("Settings…") { model.sheet = .account }
            .keyboardShortcut(",", modifiers: .command)
            .disabled(auth?.phase != .signedIn)
        }
        CommandGroup(after: .newItem) {
          Button("New Bot") { model.sheet = .botEditor(nil) }.keyboardShortcut(
            "n", modifiers: [.command, .shift])
          Button("New Group") { model.sheet = .groupEditor(nil) }
        }
      }
    #else
      WindowGroup {
        Group {
          if let configuration, let auth {
            AppRoot(configuration: configuration, auth: auth, model: model)
          } else {
            configurationFailure
          }
        }
        .environment(deviceTools)
        .environment(appleHealth)
        .frame(minWidth: 360, minHeight: 520)
      }
    #endif
  }

  private var configurationFailure: some View {
    ContentUnavailableView {
      Label("Hey Tim couldn’t start", systemImage: "exclamationmark.triangle")
    } description: {
      Text(configurationError ?? "The app configuration is unavailable.")
    }
    .accessibilityIdentifier("app.configuration-error")
  }
}

private struct AppRoot: View {
  let configuration: AppConfiguration
  @Bindable var auth: AuthSession
  @Bindable var model: AppModel
  @AppStorage(FroggyPreferenceKeys.appearance) private var storedAppearance =
    FroggyAppearancePreference.system.rawValue
  @AppStorage(FroggyPreferenceKeys.textSize) private var storedTextSize =
    FroggyTextSizePreference.platformDefaultRawValue
  @Environment(\.dynamicTypeSize) private var systemTextSize
  @Environment(\.scenePhase) private var scenePhase
  @Environment(AppleDeviceToolCoordinator.self) private var deviceTools
  #if os(iOS)
    @Environment(AppleHealthCoordinator.self) private var appleHealth
  #elseif os(macOS)
    @Environment(DesktopControlCoordinator.self) private var desktopControl
  #endif
  @State private var invitation: PendingInvitation?
  @State private var connected = false
  @State private var pendingPushSelection: PushSelection?

  var body: some View {
    Group {
      switch auth.phase {
      case .checking:
        ProgressView("Opening Hey Tim…").frame(maxWidth: .infinity, maxHeight: .infinity)
          .background(FrogTheme.background)
      case .signedOut, .codeSent: AuthView(auth: auth, invitation: invitation)
      case .signedIn: MainView(model: model, auth: auth)
      }
    }
    .froggyTextSize(textSize, systemSize: systemTextSize)
    .preferredColorScheme(appearance.colorScheme)
    .task {
      guard !Self.isUnitTestHost else { return }
      await auth.restore()
      capturePendingPushSelection()
      await connectIfNeeded()
      await openPendingPushSelectionIfReady()
    }
    .onChange(of: auth.phase) { _, phase in
      if phase == .signedIn {
        Task {
          capturePendingPushSelection()
          await connectIfNeeded()
          await openPendingPushSelectionIfReady()
        }
      } else if phase == .signedOut {
        connected = false
        pendingPushSelection = nil
        deviceTools.disconnect()
        model.resetSession()
      }
    }
    .onChange(of: scenePhase) { _, phase in
      #if os(iOS)
        // iOS device tools are intentionally foreground-only. macOS must keep
        // polling while another app is frontmost so a multi-step computer-use
        // turn can inspect, act, and verify that app.
        deviceTools.setActive(phase == .active)
      #endif
      guard phase == .active, auth.phase == .signedIn, connected else { return }
      Task {
        _ = await model.refreshBootstrap()
        deviceTools.refreshNow()
      }
    }
    .onOpenURL { url in
      let billingWebReturn = ["heytim.ai", "www.heytim.ai"].contains(url.host ?? "")
        && url.path == "/billing"
      let billingAppReturn = url.scheme == "heytim" && url.host == "app"
        && URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
          .contains(where: { $0.name == "billing" }) == true
      if auth.phase == .signedIn, billingWebReturn || billingAppReturn {
        NotificationCenter.default.post(name: .heyTimBillingDidReturn, object: nil)
      } else if auth.phase == .signedIn, ConnectionAuthorizationCallback(url: url) != nil {
        Task { await model.handleConnectionCallback(url) }
      } else if auth.phase == .signedIn, url.scheme == "heytim", url.host == "app" {
        Task { await model.refreshBootstrap() }
      } else if auth.phase == .signedIn {
        model.handle(url: url)
      } else {
        invitation = Self.invitation(from: url)
      }
    }
    .onReceive(NotificationCenter.default.publisher(for: .froggyPushToken)) { notification in
      guard let token = notification.object as? Data, auth.phase == .signedIn else { return }
      #if os(iOS)
        let platform = "ios"
      #else
        let platform = "macos"
      #endif
      Task { await model.registerPush(token, platform: platform) }
    }
    .onReceive(NotificationCenter.default.publisher(for: .froggyPushRegistrationFailure)) {
      notification in
      let message = notification.object as? String ?? "Apple could not register this device."
      model.reportPushRegistrationFailure(message)
    }
    .onReceive(NotificationCenter.default.publisher(for: .froggyPushSelection)) { notification in
      guard let selection = notification.object as? PushSelection else { return }
      _ = PushNotificationDelegate.shared.consumePendingSelection(matching: selection)
      pendingPushSelection = selection
      Task { await openPendingPushSelectionIfReady() }
    }
  }

  private func capturePendingPushSelection() {
    guard let selection = PushNotificationDelegate.shared.consumePendingSelection() else { return }
    pendingPushSelection = selection
  }

  private func openPendingPushSelectionIfReady() async {
    guard auth.phase == .signedIn, model.bootstrap != nil, let selection = pendingPushSelection
    else { return }
    pendingPushSelection = nil
    if let groupId = selection.groupId {
      await model.openConversationFromNotification(.init(kind: .group, id: groupId))
    } else if let botId = selection.botId {
      await model.openConversationFromNotification(.init(kind: .bot, id: botId))
    }
  }

  private func connectIfNeeded() async {
    guard auth.phase == .signedIn, !connected else { return }
    // UI automation uses deterministic local fixtures and must never call the
    // live service with its synthetic account credentials.
    if Self.isUITesting {
      connected = true
      return
    }
    do {
      let authSession = auth.sessionIdentifier
      let api = try HeyTimAPI(
        configuration: configuration,
        onSessionExpired: { token in
          await auth.expire(ifUsing: token, session: authSession)
        }
      ) { try await auth.idToken(forSession: authSession) }
      model.connect(api)
      connected = true
      await model.load()
      guard auth.phase == .signedIn, auth.sessionIdentifier == authSession else { return }
      #if os(iOS)
        let health = appleHealth
        deviceTools.connect(
          api: api,
          registration: { Self.healthRegistration(health) },
          execute: { call in await health.execute(call) })
      #elseif os(macOS)
        let desktop = desktopControl
        deviceTools.connect(
          api: api,
          registration: { Self.macRegistration(desktop) },
          execute: { call in await desktop.execute(call) })
      #endif
      await NativeNotifications.registerIfAuthorized()
      if let invitation {
        model.deepLinkInvite = (invitation.kind, invitation.token)
        await model.acceptPendingInvite()
        self.invitation = nil
      }
    } catch { model.present(error) }
  }

  private var appearance: FroggyAppearancePreference {
    FroggyAppearancePreference(rawValue: storedAppearance) ?? .system
  }

  private var textSize: FroggyTextSizePreference {
    FroggyTextSizePreference(rawValue: storedTextSize) ?? .system
  }

  private static var appVersion: String {
    let version = Bundle.main.object(
      forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
    let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
      ?? "unknown"
    return "\(version) (\(build))"
  }

  #if os(iOS)
    @MainActor private static func healthRegistration(
      _ health: AppleHealthCoordinator
    ) -> DeviceCapabilityRegistration {
      let tools = health.isAvailable
        ? [DeviceToolCapability(
          id: "apple_health",
          operations: GeneratedDeviceCapabilities.operationsByTool["apple_health"] ?? [])]
        : []
      return DeviceCapabilityRegistration(
        platform: "ios", appVersion: appVersion, tools: tools,
        botGrants: health.enabledBotIDs.sorted().map {
          DeviceBotGrant(botId: $0, toolIds: ["apple_health"])
        })
    }
  #elseif os(macOS)
    @MainActor private static func macRegistration(
      _ desktop: DesktopControlCoordinator
    ) -> DeviceCapabilityRegistration {
      let available = desktop.isEnabled && desktop.permissionGranted && !desktop.isPaused
      let tools = available
        ? [DeviceToolCapability(
          id: "mac_computer",
          operations: GeneratedDeviceCapabilities.operationsByTool["mac_computer"] ?? [])]
        : []
      return DeviceCapabilityRegistration(
        platform: "macos", appVersion: appVersion, tools: tools,
        botGrants: available
          ? desktop.enabledBotIDs.sorted().map {
            DeviceBotGrant(botId: $0, toolIds: ["mac_computer"])
          }
          : [])
    }
  #endif

  static func invitation(from url: URL) -> PendingInvitation? {
    InvitationParser.parse(url)
  }

  private static var isUnitTestHost: Bool {
    ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
      && !isUITesting
  }

  private static var isUITesting: Bool {
    #if DEBUG
      ProcessInfo.processInfo.arguments.contains("--ui-testing")
    #else
      false
    #endif
  }
}
