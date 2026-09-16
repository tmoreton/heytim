import Foundation
import UserNotifications

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

extension Notification.Name {
  public static let froggyPushToken = Notification.Name("FroggyBotPushToken")
  public static let froggyPushRegistrationFailure = Notification.Name(
    "FroggyBotPushRegistrationFailure")
  public static let froggyPushSelection = Notification.Name("FroggyBotPushSelection")
}

public struct PushSelection: Equatable, Sendable {
  public let botId: String?
  public let groupId: String?

  public init?(userInfo: [AnyHashable: Any]) {
    let botId = (userInfo["botId"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    let groupId = (userInfo["groupId"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    guard botId != nil || groupId != nil else { return nil }
    self.botId = botId
    self.groupId = groupId
  }
}

private final class NotificationResponseCompletion: @unchecked Sendable {
  private let action: () -> Void

  init(_ action: @escaping () -> Void) {
    self.action = action
  }

  func callAsFunction() {
    action()
  }
}

public enum NativeNotifications {
  @MainActor public static func requestAuthorization() async throws {
    let center = UNUserNotificationCenter.current()
    center.delegate = PushNotificationDelegate.shared
    let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
    guard granted else { return }
    registerForRemoteNotifications()
  }

  @MainActor public static func registerIfAuthorized() async {
    let settings = await UNUserNotificationCenter.current().notificationSettings()
    #if os(iOS)
      let canRegister = settings.authorizationStatus == .authorized
        || settings.authorizationStatus == .provisional
        || settings.authorizationStatus == .ephemeral
    #else
      let canRegister = settings.authorizationStatus == .authorized
        || settings.authorizationStatus == .provisional
    #endif
    guard canRegister else { return }
    registerForRemoteNotifications()
  }

  @MainActor private static func registerForRemoteNotifications() {
    #if os(iOS)
      UIApplication.shared.registerForRemoteNotifications()
    #elseif os(macOS)
      NSApplication.shared.registerForRemoteNotifications()
    #endif
  }

  @MainActor public static func openSystemSettings() {
    #if os(iOS)
      guard let url = URL(string: UIApplication.openNotificationSettingsURLString) else { return }
      UIApplication.shared.open(url)
    #elseif os(macOS)
      guard
        let url = URL(
          string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension")
      else { return }
      NSWorkspace.shared.open(url)
    #endif
  }
}

public final class PushNotificationDelegate: NSObject, UNUserNotificationCenterDelegate,
  @unchecked Sendable
{
  public static let shared = PushNotificationDelegate()
  @MainActor private var pendingSelection: PushSelection?

  public func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    completionHandler([.banner, .sound, .badge])
  }

  public func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse,
    withCompletionHandler completionHandler: @escaping () -> Void
  ) {
    handleResponse(
      userInfo: response.notification.request.content.userInfo,
      completionHandler: completionHandler)
  }

  func handleResponse(
    userInfo: [AnyHashable: Any],
    completionHandler: @escaping () -> Void
  ) {
    let selection = PushSelection(userInfo: userInfo)
    let completion = NotificationResponseCompletion(completionHandler)
    DispatchQueue.main.async { [self] in
      // UIKit continues foreground state restoration when this returns. Complete
      // on the main queue, then navigate on the next run-loop turn so SwiftUI
      // does not mutate navigation while UIKit is archiving the scene state.
      completion()
      guard let selection else { return }
      pendingSelection = selection
      DispatchQueue.main.async { [self] in
        guard pendingSelection == selection else { return }
        NotificationCenter.default.post(name: .froggyPushSelection, object: selection)
      }
    }
  }

  @MainActor public func consumePendingSelection(
    matching selection: PushSelection? = nil
  ) -> PushSelection? {
    guard selection == nil || pendingSelection == selection else { return nil }
    defer { pendingSelection = nil }
    return pendingSelection
  }
}

#if os(iOS)
  public final class FroggyAppDelegate: NSObject, UIApplicationDelegate {
    public func application(
      _ application: UIApplication,
      didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
      UNUserNotificationCenter.current().delegate = PushNotificationDelegate.shared
      return true
    }
    public func application(
      _ application: UIApplication,
      didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
      NotificationCenter.default.post(name: .froggyPushToken, object: deviceToken)
    }
    public func application(
      _ application: UIApplication,
      didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
      NotificationCenter.default.post(
        name: .froggyPushRegistrationFailure, object: error.localizedDescription)
    }
  }
#elseif os(macOS)
  public final class FroggyAppDelegate: NSObject, NSApplicationDelegate {
    public func applicationDidFinishLaunching(_ notification: Notification) {
      UNUserNotificationCenter.current().delegate = PushNotificationDelegate.shared
    }
    public func application(
      _ application: NSApplication,
      didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
      NotificationCenter.default.post(name: .froggyPushToken, object: deviceToken)
    }
    public func application(
      _ application: NSApplication,
      didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
      NotificationCenter.default.post(
        name: .froggyPushRegistrationFailure, object: error.localizedDescription)
    }
  }
#endif
