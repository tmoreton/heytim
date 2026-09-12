import ExpoModulesCore
import UIKit

/// Removes the redundant native Mac title bar when the iOS app runs in
/// Designed-for-iPad mode. iPhone and iPad windows are left untouched.
public final class FroggyBotWindowChromeSubscriber: ExpoAppDelegateSubscriber {
  private var macWindowObserver: NSObjectProtocol?

  public func applicationDidBecomeActive(_ application: UIApplication) {
    guard ProcessInfo.processInfo.isiOSAppOnMac else { return }

    installMacWindowObserver()
    styleMacWindows(for: application)

    // The native host window can be replaced after UIKit reports the app as
    // active. Repeat after that handoff so the React Native background, rather
    // than the default white title-bar material, fills the traffic-light area.
    DispatchQueue.main.async { [weak self, weak application] in
      guard let application else { return }
      self?.styleMacWindows(for: application)
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self, weak application] in
      guard let application else { return }
      self?.styleMacWindows(for: application)
    }
  }

  deinit {
    if let macWindowObserver {
      NotificationCenter.default.removeObserver(macWindowObserver)
    }
  }

  private func installMacWindowObserver() {
    guard macWindowObserver == nil else { return }
    macWindowObserver = NotificationCenter.default.addObserver(
      forName: Notification.Name("NSWindowDidBecomeKeyNotification"),
      object: nil,
      queue: .main
    ) { [weak self] notification in
      guard let window = notification.object as? NSObject else { return }
      self?.expandContentBehindMacWindowControls(in: window)
    }
  }

  private func styleMacWindows(for application: UIApplication) {
    application.connectedScenes
      .compactMap { $0 as? UIWindowScene }
      .forEach(hideUIKitTitlebar)
    macWindows().forEach(expandContentBehindMacWindowControls)
  }

  private func hideUIKitTitlebar(in scene: UIWindowScene) {
    let titlebarSelector = NSSelectorFromString("titlebar")
    guard scene.responds(to: titlebarSelector),
          let titlebar = scene.perform(titlebarSelector)?.takeUnretainedValue() as? NSObject
    else {
      return
    }

    setValue(1, forKey: "titleVisibility", on: titlebar)
    setValue(nil, forKey: "toolbar", on: titlebar)
    setValue(1, forKey: "separatorStyle", on: titlebar)
  }

  private func macWindows() -> [NSObject] {
    let sharedApplicationSelector = NSSelectorFromString("sharedApplication")
    guard let applicationClass = NSClassFromString("NSApplication") as? NSObject.Type,
          applicationClass.responds(to: sharedApplicationSelector),
          let macApplication = applicationClass.perform(sharedApplicationSelector)?.takeUnretainedValue() as? NSObject
    else {
      return []
    }

    let windowsSelector = NSSelectorFromString("windows")
    guard macApplication.responds(to: windowsSelector),
          let value = macApplication.perform(windowsSelector)?.takeUnretainedValue()
    else {
      return []
    }
    if let windows = value as? [NSObject] {
      return windows
    }
    if let windows = value as? NSArray {
      return windows.compactMap { $0 as? NSObject }
    }
    return []
  }

  private func expandContentBehindMacWindowControls(in macWindow: NSObject) {
    setValue(true, forKey: "titlebarAppearsTransparent", on: macWindow)
    setValue(1, forKey: "titleVisibility", on: macWindow)
    setValue(nil, forKey: "toolbar", on: macWindow)

    guard let currentStyleMask = macWindow.value(forKey: "styleMask") as? NSNumber else { return }
    let fullSizeContentViewMask: UInt = 1 << 15
    setValue(
      currentStyleMask.uintValue | fullSizeContentViewMask,
      forKey: "styleMask",
      on: macWindow
    )
  }

  private func setValue(_ value: Any?, forKey key: String, on object: NSObject) {
    let setterName = "set\(key.prefix(1).uppercased())\(key.dropFirst()):"
    guard object.responds(to: NSSelectorFromString(setterName)) else { return }
    object.setValue(value, forKey: key)
  }
}
