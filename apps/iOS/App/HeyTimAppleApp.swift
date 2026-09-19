import SwiftUI

@main
struct HeyTimAppleApp: App {
  #if os(iOS)
    @UIApplicationDelegateAdaptor(FroggyAppDelegate.self) private var appDelegate
  #elseif os(macOS)
    @NSApplicationDelegateAdaptor(FroggyAppDelegate.self) private var appDelegate
  #endif

  private let configuration: AppConfiguration
  @State private var auth: AuthSession
  @State private var model: AppModel

  init() {
    let value = try! AppConfiguration.load()
    configuration = value
    _auth = State(initialValue: AuthSession(configuration: value))
    _model = State(
      initialValue: AppModel(demoMode: ProcessInfo.processInfo.arguments.contains("--ui-testing")))
  }

  var body: some Scene {
    #if os(macOS)
      WindowGroup {
        AppRoot(configuration: configuration, auth: auth, model: model)
          .frame(minWidth: auth.phase == .signedIn ? 1_160 : 900, minHeight: 620)
      }
      .defaultSize(width: 1200, height: 760)
      .windowStyle(.hiddenTitleBar)
      .windowResizability(.contentMinSize)
      .commands {
        CommandGroup(replacing: .appSettings) {
          Button("Settings…") { model.sheet = .account }
            .keyboardShortcut(",", modifiers: .command)
            .disabled(auth.phase != .signedIn)
        }
        CommandGroup(after: .newItem) {
          Button("New Bot") { model.sheet = .botEditor(nil) }.keyboardShortcut(
            "n", modifiers: [.command, .shift])
          Button("New Group") { model.sheet = .groupEditor(nil) }
        }
      }
    #else
      WindowGroup {
        AppRoot(configuration: configuration, auth: auth, model: model)
          .frame(minWidth: 360, minHeight: 520)
      }
    #endif
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
        model.resetSession()
      }
    }
    .onOpenURL { url in
      if auth.phase == .signedIn, ConnectionAuthorizationCallback(url: url) != nil {
        Task { await model.handleConnectionCallback(url) }
      } else if auth.phase == .signedIn, ["heytim", "heytim"].contains(url.scheme ?? ""), url.host == "app" {
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
    if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
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

  static func invitation(from url: URL) -> PendingInvitation? {
    InvitationParser.parse(url)
  }

  private static var isUnitTestHost: Bool {
    ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
      && !ProcessInfo.processInfo.arguments.contains("--ui-testing")
  }
}
