#if os(macOS)
  import Foundation
  import Sparkle

  struct DesktopUpdateConfiguration: Equatable {
    let feedURL: URL?
    let publicKey: String

    init(info: [String: Any]) {
      let feed = (info["SUFeedURL"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
      let key = (info["SUPublicEDKey"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
      feedURL = feed.flatMap(URL.init(string:))
      publicKey = key
    }

    var isConfigured: Bool {
      feedURL?.scheme == "https"
        && Data(base64Encoded: publicKey)?.count == 32
        && !publicKey.contains("$(")
    }
  }

  @MainActor final class DesktopUpdateController {
    static let shared = DesktopUpdateController()
    let isConfigured: Bool
    private let controller: SPUStandardUpdaterController?

    init(bundle: Bundle = .main) {
      let configuration = DesktopUpdateConfiguration(info: bundle.infoDictionary ?? [:])
      #if DEBUG
        let process = ProcessInfo.processInfo
        let isTesting = process.arguments.contains("--ui-testing")
          || process.environment["XCTestConfigurationFilePath"] != nil
      #else
        let isTesting = false
      #endif
      // Offline fixture runs must not show or install a live Sparkle update.
      isConfigured = configuration.isConfigured && !isTesting
      controller = isConfigured
        ? SPUStandardUpdaterController(
          startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
        : nil
    }

    func checkForUpdates() {
      controller?.checkForUpdates(nil)
    }
  }
#endif
