import Foundation
import UserNotifications

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

extension Notification.Name {
  public static let froggyPushToken = Notification.Name("FroggyBotPushToken")
  public static let froggyPushSelection = Notification.Name("FroggyBotPushSelection")
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
    guard
      settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
    else { return }
    registerForRemoteNotifications()
  }

  @MainActor private static func registerForRemoteNotifications() {
    #if os(iOS)
      UIApplication.shared.registerForRemoteNotifications()
    #elseif os(macOS)
      NSApplication.shared.registerForRemoteNotifications()
    #endif
  }
}

public final class PushNotificationDelegate: NSObject, UNUserNotificationCenterDelegate,
  @unchecked Sendable
{
  public static let shared = PushNotificationDelegate()
  public func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification
  ) async -> UNNotificationPresentationOptions { [.banner, .sound, .badge] }

  public func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse
  ) async {
    NotificationCenter.default.post(
      name: .froggyPushSelection, object: nil,
      userInfo: response.notification.request.content.userInfo)
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
  }
#endif
