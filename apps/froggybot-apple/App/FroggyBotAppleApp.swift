import SwiftUI

@main
struct FroggyBotAppleApp: App {
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
          .frame(minWidth: auth.phase == .signedIn ? 1_080 : 480, minHeight: 520)
      }
      .defaultSize(width: 1120, height: 760)
      .windowResizability(.contentMinSize)
      .commands {
        CommandGroup(after: .newItem) {
          Button("New Bot") { model.sheet = .botEditor(nil) }.keyboardShortcut(
            "n", modifiers: [.command, .shift])
          Button("New Group") { model.sheet = .groupEditor(nil) }
        }
        InspectorCommands()
      }

      Settings {
        NavigationStack {
          switch auth.phase {
          case .signedIn:
            AccountView(model: model, auth: auth, showsDismissButton: false)
          case .checking:
            ProgressView("Opening FroggyBot…")
              .frame(maxWidth: .infinity, maxHeight: .infinity)
          case .signedOut, .codeSent:
            ContentUnavailableView(
              "Sign in to manage settings", systemImage: "person.crop.circle.badge.exclamationmark")
          }
        }
        .frame(minWidth: 620, idealWidth: 680, minHeight: 620, idealHeight: 720)
        .tint(FrogTheme.brand)
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
  @State private var invitation: PendingInvitation?
  @State private var connected = false

  var body: some View {
    Group {
      switch auth.phase {
      case .checking:
        ProgressView("Opening FroggyBot…").frame(maxWidth: .infinity, maxHeight: .infinity)
          .background(FrogTheme.background)
      case .signedOut, .codeSent: AuthView(auth: auth, invitation: invitation)
      case .signedIn: MainView(model: model, auth: auth)
      }
    }
    .task {
      guard !Self.isUnitTestHost else { return }
      await auth.restore()
      await connectIfNeeded()
    }
    .onChange(of: auth.phase) { _, phase in
      if phase == .signedIn {
        Task { await connectIfNeeded() }
      } else if phase == .signedOut {
        connected = false
        model.resetSession()
      }
    }
    .onOpenURL { url in
      if auth.phase == .signedIn, url.scheme == "froggybot", url.host == "app" {
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
    .onReceive(NotificationCenter.default.publisher(for: .froggyPushSelection)) { notification in
      let info = notification.userInfo ?? [:]
      if let groupId = info["groupId"] as? String {
        model.select(.init(kind: .group, id: groupId))
      } else if let botId = info["botId"] as? String {
        model.select(.init(kind: .bot, id: botId))
      }
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
      let api = try FrogBotAPI(
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

  static func invitation(from url: URL) -> PendingInvitation? {
    InvitationParser.parse(url)
  }

  private static var isUnitTestHost: Bool {
    ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
      && !ProcessInfo.processInfo.arguments.contains("--ui-testing")
  }
}
