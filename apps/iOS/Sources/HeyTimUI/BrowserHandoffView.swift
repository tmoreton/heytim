import SwiftUI
import WebKit

struct BrowserHandoffView: View {
  @Bindable var model: AppModel
  let botId: String
  let groupId: String?
  var showsDismissButton = true
  @State private var state: BrowserState?
  @State private var address = ""
  @State private var loading = false
  @State private var refreshing = false
  @State private var loadError: String?
  @State private var navigationError: String?

  var body: some View {
    VStack(spacing: 0) {
      VStack(alignment: .trailing, spacing: 10) {
        HStack(spacing: 8) {
          TextField("https://example.com", text: $address)
            .textFieldStyle(.roundedBorder)
            .accessibilityLabel("Website address")
            #if os(iOS)
              .textInputAutocapitalization(.never)
              .keyboardType(.URL)
            #endif
            .autocorrectionDisabled()
            .disabled(isBusy)
            .onSubmit { open() }
          Button("Open") { open() }
            .froggyGlassButton(prominent: true)
            .disabled(isBusy)
        }
        if let navigationError {
          Text(navigationError)
            .froggyFont(.footnote)
            .foregroundStyle(FrogTheme.danger)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        if state?.status == "human_control" {
          Button("Reconnect Live View", systemImage: "arrow.clockwise") { reconnect() }
            .disabled(isBusy)
          Button("Return Control", systemImage: "arrow.uturn.backward") {
            resume(rememberLogin: false)
          }
            .froggyGlassButton()
            .disabled(isBusy)
          Button("Save Login and Return Control") { resume(rememberLogin: true) }
            .disabled(isBusy)
        }
      }
      .padding()
      Divider()
      if refreshing && state == nil {
        ProgressView("Loading secure browser…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if let loadError, state == nil {
        ContentUnavailableView {
          Label("Couldn’t Load Browser", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await refresh() } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if let raw = state?.liveViewUrl, let url = URL(string: raw) {
        BrowserWebView(signedURL: url, viewport: state?.viewport) { message in
          navigationError = message
        }
      } else {
        ContentUnavailableView {
          Label(state?.status == "expired" ? "Session expired" : "Browser is ready",
            systemImage: "globe")
        } description: {
          Text(state?.contextLabel
            ?? "Open a website when a bot asks you to sign in or complete a private step.")
        } actions: {
          if state?.status == "human_control" {
            Button("Show Browser") { reconnect() }
          }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    .froggyNavigationTitle("Secure Browser")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      ToolbarItem(placement: .primaryAction) {
        Menu {
          Button("Refresh", systemImage: "arrow.clockwise") {
            if state?.status == "human_control" { reconnect() }
            else { Task { await refresh() } }
          }
          .disabled(isBusy)
          Divider()
          Button("Disconnect browser", role: .destructive) { close() }.disabled(
            state?.status == "closed" || isBusy)
          Button("Forget saved login", role: .destructive) { forget() }.disabled(
            state?.hasSavedLogin != true || isBusy)
        } label: {
          Image(systemName: "ellipsis.circle")
        }
      }
    }
    .task { await refresh() }
  }

  private var isBusy: Bool { loading || refreshing }

  private func refresh() async {
    refreshing = true
    defer { refreshing = false }
    guard let api = model.api else {
      loadError = nil
      return
    }
    do {
      state = try await api.browserState(botId: botId, groupId: groupId)
      loadError = nil
    } catch {
      if state == nil {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
  }
  private func open() {
    let url: URL?
    do {
      url = try BrowserAddress.normalizedURL(address)
      navigationError = nil
    } catch {
      navigationError = error.localizedDescription
      return
    }
    loading = true
    Task {
      defer { loading = false }
      do {
        #if os(iOS)
          let display = "mobile"
        #else
          let display = "desktop"
        #endif
        state = try await model.api?.openBrowser(
          botId: botId, groupId: groupId, url: url, display: display)
        if let url { address = url.absoluteString }
      } catch { navigationError = error.localizedDescription }
    }
  }
  private func reconnect() {
    loading = true
    Task {
      defer { loading = false }
      do {
        state = try await model.api?.openBrowser(botId: botId, groupId: groupId)
        navigationError = nil
      } catch { navigationError = error.localizedDescription }
    }
  }
  private func resume(rememberLogin: Bool) {
    loading = true
    Task {
      defer { loading = false }
      do {
        state = try await model.api?.resumeBrowser(
          botId: botId, groupId: groupId, rememberLogin: rememberLogin)
      } catch {
        model.present(error)
      }
    }
  }
  private func close() {
    Task {
      do {
        try await model.api?.closeBrowser(botId: botId, groupId: groupId)
        await refresh()
      } catch { model.present(error) }
    }
  }
  private func forget() {
    Task {
      do {
        try await model.api?.forgetBrowserLogin(botId: botId)
        await refresh()
      } catch { model.present(error) }
    }
  }
}

enum BrowserAddress {
  static func normalizedURL(_ input: String) throws -> URL? {
    let value = input.trimmingCharacters(in: .whitespacesAndNewlines)
    if value.isEmpty { return nil }
    let candidate = value.contains("://") ? value : "https://\(value)"
    guard let components = URLComponents(string: candidate),
      let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme),
      let host = components.host, host.contains("."),
      components.user == nil, components.password == nil,
      let url = components.url
    else {
      throw APIError.configuration("Enter a valid website address, such as google.com.")
    }
    return url
  }
}

private enum BrowserViewerPage {
  static let url = URL(string: "https://heytim.ai/browser-viewer/")!
}

private final class BrowserViewerCoordinator: NSObject, WKNavigationDelegate {
  var signedURL: URL
  var viewport: BrowserViewport?
  var onError: (String) -> Void
  private var loaded = false
  private var injectedURL: URL?

  init(signedURL: URL, viewport: BrowserViewport?, onError: @escaping (String) -> Void) {
    self.signedURL = signedURL
    self.viewport = viewport
    self.onError = onError
  }

  func update(_ view: WKWebView, signedURL: URL, viewport: BrowserViewport?) {
    self.signedURL = signedURL
    self.viewport = viewport
    if loaded { injectSession(into: view) }
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    loaded = true
    injectSession(into: webView)
  }

  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
    withError error: Error
  ) {
    onError("Couldn’t load the live browser. Check your connection and try Show Browser again.")
  }

  func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction
  ) async -> WKNavigationActionPolicy {
    guard navigationAction.targetFrame?.isMainFrame == true else {
      return .allow
    }
    guard let url = navigationAction.request.url else { return .cancel }
    if url.scheme == "about" { return .allow }
    return url.scheme == "https"
      && ["heytim.ai", "www.heytim.ai"].contains(url.host ?? "")
      && url.path == "/browser-viewer/" ? .allow : .cancel
  }

  private func injectSession(into view: WKWebView) {
    guard injectedURL != signedURL,
      let data = try? JSONEncoder().encode(signedURL.absoluteString),
      let quotedURL = String(data: data, encoding: .utf8)
    else { return }
    let width = viewport?.width ?? 1920
    let height = viewport?.height ?? 1080
    injectedURL = signedURL
    view.evaluateJavaScript("window.heytimSetBrowserSession(\(quotedURL), \(width), \(height))") {
      [weak self] _, error in
      if error != nil {
        self?.injectedURL = nil
        self?.onError("Couldn’t connect to the live browser. Refresh the browser session and try again.")
      }
    }
  }
}

#if os(iOS)
  private struct BrowserWebView: UIViewRepresentable {
    let signedURL: URL
    let viewport: BrowserViewport?
    let onError: (String) -> Void
    func makeCoordinator() -> BrowserViewerCoordinator {
      BrowserViewerCoordinator(signedURL: signedURL, viewport: viewport, onError: onError)
    }
    func makeUIView(context: Context) -> WKWebView {
      let config = WKWebViewConfiguration()
      config.websiteDataStore = .nonPersistent()
      let view = WKWebView(frame: .zero, configuration: config)
      view.navigationDelegate = context.coordinator
      view.load(URLRequest(url: BrowserViewerPage.url))
      return view
    }
    func updateUIView(_ view: WKWebView, context: Context) {
      context.coordinator.update(view, signedURL: signedURL, viewport: viewport)
    }
  }
#elseif os(macOS)
  private struct BrowserWebView: NSViewRepresentable {
    let signedURL: URL
    let viewport: BrowserViewport?
    let onError: (String) -> Void
    func makeCoordinator() -> BrowserViewerCoordinator {
      BrowserViewerCoordinator(signedURL: signedURL, viewport: viewport, onError: onError)
    }
    func makeNSView(context: Context) -> WKWebView {
      let config = WKWebViewConfiguration()
      config.websiteDataStore = .nonPersistent()
      let view = WKWebView(frame: .zero, configuration: config)
      view.navigationDelegate = context.coordinator
      view.load(URLRequest(url: BrowserViewerPage.url))
      return view
    }
    func updateNSView(_ view: WKWebView, context: Context) {
      context.coordinator.update(view, signedURL: signedURL, viewport: viewport)
    }
  }
#endif
