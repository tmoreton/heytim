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
    WindowGroup {
      AppRoot(configuration: configuration, auth: auth, model: model)
        .frame(minWidth: 360, minHeight: 520)
        .preferredColorScheme(.light)
    }
    #if os(macOS)
      .defaultSize(width: 1120, height: 760)
      .commands {
        CommandGroup(after: .newItem) {
          Button("New Bot") { model.sheet = .botEditor(nil) }.keyboardShortcut(
            "n", modifiers: [.command, .shift])
          Button("New Group") { model.sheet = .groupEditor(nil) }
        }
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
      await auth.restore()
      await connectIfNeeded()
    }
    .onChange(of: auth.phase) { _, phase in
      if phase == .signedIn {
        Task { await connectIfNeeded() }
      } else if phase == .signedOut {
        connected = false
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
    do {
      let api = try FrogBotAPI(configuration: configuration) { try await auth.idToken() }
      model.connect(api)
      connected = true
      await model.load()
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
}
