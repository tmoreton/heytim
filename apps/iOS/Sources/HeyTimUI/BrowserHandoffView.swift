import SwiftUI
import WebKit

struct BrowserHandoffView: View {
  @Bindable var model: AppModel
  let botId: String
  let groupId: String?
  var showsDismissButton = true
  var isEmbedded = false
  @State private var state: BrowserState?
  @State private var address = ""
  @State private var loading = false
  @State private var refreshing = false
  @State private var loadError: String?
  @State private var navigationError: String?
  @State private var viewerRevision = 0

  var body: some View {
    Group {
      if isEmbedded {
        browserContent
      } else {
        browserContent
          .froggyNavigationTitle("Secure Browser")
          .toolbarTitleDisplayMode(.inline)
          .toolbar {
            if showsDismissButton { CloseButton { model.sheet = nil } }
            ToolbarItem(placement: .primaryAction) { browserMenu }
          }
      }
    }
    .task { await refresh() }
    .onChange(of: model.browserStates[botId]) { _, summary in
      guard var summary else {
        state = nil
        return
      }
      if summary.status == state?.status {
        summary.liveViewUrl = state?.liveViewUrl
        summary.liveViewExpiresAt = state?.liveViewExpiresAt
      }
      state = summary
    }
  }

  private var browserContent: some View {
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
          if isEmbedded { browserMenu }
        }
        if let navigationError {
          Text(navigationError)
            .froggyFont(.footnote)
            .foregroundStyle(FrogTheme.danger)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        if state?.status == "human_control" {
          Button("Reconnect Live View", systemImage: "arrow.clockwise") { reconnect() }
            .froggyGlassButton()
            .disabled(isBusy)
          Button("Resume Bot", systemImage: "arrow.uturn.backward") {
            resume(rememberLogin: false)
          }
            .froggyGlassButton()
            .disabled(isBusy)
          Button("Save Login and Resume Bot") { resume(rememberLogin: true) }
            .froggyGlassButton()
            .disabled(isBusy)
        }
        if state?.profileSavePending == true {
          Label("Saving your login securely…", systemImage: "lock.shield")
            .froggyFont(.footnote)
          Button("Continue Saving Login") { resume(rememberLogin: true) }
            .froggyGlassButton()
            .disabled(isBusy)
            .accessibilityIdentifier("browser.continue-saving")
        }
        if loading { ProgressView("Updating browser…").controlSize(.small) }
        if state?.requiresHandoff == true || model.blockedBrowserBotIDs.contains(botId) {
          if state?.status == "expired" {
            Button("Reopen Browser", systemImage: "arrow.clockwise") { reconnect() }
              .froggyGlassButton()
              .disabled(isBusy)
          }
          Button("End Browser Handoff") { close() }
            .froggyGlassButton()
            .disabled(isBusy || operationInProgress)
            .accessibilityIdentifier("browser.end-handoff")
          Text("Ends this browser session without sending a message. Saved logins are kept.")
            .froggyFont(.caption)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
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
        BrowserWebView(signedURL: url, viewport: state?.viewport, onReconnect: reconnect) { message in
          navigationError = message
        }
        .id(viewerRevision)
      } else {
        ContentUnavailableView {
          Label(statusTitle, systemImage: "globe")
        } description: {
          Text(state?.contextLabel
            ?? "Open a website when a bot asks you to sign in or complete a private step.")
        } actions: {
          if state?.status == "human_control" {
            Button("Show Browser") { reconnect() }
              .froggyGlassButton(prominent: true)
          }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
  }

  private var browserMenu: some View {
    Menu {
      Button("Refresh", systemImage: "arrow.clockwise") {
        if state?.status == "human_control" { reconnect() }
        else { Task { await refresh() } }
      }
      .disabled(isBusy)
      Divider()
      Button("End Browser Handoff") { close() }.disabled(
        state?.status == "closed" || isBusy || operationInProgress)
      Button("Forget saved login", role: .destructive) { forget() }.disabled(
        state?.hasSavedLogin != true || isBusy)
    } label: {
      Image(systemName: "ellipsis.circle")
    }
  }

  private var isBusy: Bool {
    loading || refreshing || model.closingBrowserBotIDs.contains(botId)
      || model.busyBrowserBotIDs.contains(botId)
  }
  private var operationInProgress: Bool {
    state?.profileSavePending != true
      && ["opening", "resuming"].contains(state?.status ?? "")
      && state?.recoveryRequired == false
  }
  private var statusTitle: String {
    switch state?.status {
    case "expired": "Browser session expired"
    case "opening": "Opening browser"
    case "resuming": state?.recoveryRequired == true ? "Browser handoff needs attention" : "Returning control"
    case "closed": "Browser is closed"
    default: "Browser is ready"
    }
  }

  private func apply(_ value: BrowserState?) {
    state = value
    if value?.liveViewUrl != nil { viewerRevision &+= 1 }
    if let value { model.updateBrowserState(value) }
  }

  private func refresh() async {
    refreshing = true
    defer { refreshing = false }
    guard let api = model.api else {
      state = model.browserStates[botId]
      loadError = nil
      return
    }
    let session = model.sessionGeneration
    do {
      guard groupId == nil else { throw APIError.configuration("Browser handoffs are private to a bot’s direct chat.") }
      let value = try await model.fetchBrowserState(botId: botId)
      guard model.sessionIsCurrent(session, api: api) else { return }
      if let value { state = value }
      loadError = nil
    } catch {
      guard model.sessionIsCurrent(session, api: api) else { return }
      if state == nil {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
  }
  private func finishOperation(session: UInt, releasesLease: Bool = true) {
    loading = false
    if releasesLease && model.sessionGeneration == session {
      model.busyBrowserBotIDs.remove(botId)
    }
  }
  private func open() {
    guard let api = model.api else { return }
    let session = model.sessionGeneration
    let url: URL?
    do {
      url = try BrowserAddress.normalizedURL(address)
      navigationError = nil
    } catch {
      navigationError = error.localizedDescription
      return
    }
    guard model.beginBrowserOperation(botId: botId) else { return }
    loading = true
    Task {
      defer { finishOperation(session: session) }
      do {
        #if os(iOS)
          let display = "mobile"
        #else
          let display = "desktop"
        #endif
        let value = try await api.openBrowser(
          botId: botId, groupId: groupId, url: url, display: display)
        guard model.sessionIsCurrent(session, api: api) else { return }
        apply(value)
        if let url { address = url.absoluteString }
      } catch {
        if model.sessionIsCurrent(session, api: api) {
          navigationError = error.localizedDescription
          if let latest = try? await model.fetchBrowserState(botId: botId) { state = latest }
        }
      }
    }
  }
  private func reconnect() {
    guard let api = model.api else { return }
    let session = model.sessionGeneration
    guard model.beginBrowserOperation(botId: botId) else { return }
    loading = true
    Task {
      defer { finishOperation(session: session) }
      do {
        let value = try await api.openBrowser(botId: botId, groupId: groupId)
        guard model.sessionIsCurrent(session, api: api) else { return }
        apply(value)
        navigationError = nil
      } catch {
        if model.sessionIsCurrent(session, api: api) {
          navigationError = error.localizedDescription
          if let latest = try? await model.fetchBrowserState(botId: botId) { state = latest }
        }
      }
    }
  }
  private func resume(rememberLogin: Bool) {
    guard let api = model.api, !isBusy else { return }
    let session = model.sessionGeneration
    loading = true
    navigationError = nil
    // Disconnect the human viewer before enabling the bot's automation stream.
    state?.liveViewUrl = nil
    state?.liveViewExpiresAt = nil
    Task {
      defer { finishOperation(session: session, releasesLease: false) }
      do {
        guard model.sessionIsCurrent(session, api: api) else { return }
        guard groupId == nil else {
          throw APIError.configuration("Browser handoffs are private to a bot’s direct chat.")
        }
        let value = try await model.resumeBrowserHandoff(
          botId: botId, rememberLogin: rememberLogin)
        guard model.sessionIsCurrent(session, api: api) else { return }
        apply(value)
      } catch {
        if model.sessionIsCurrent(session, api: api), !(error is CancellationError) {
          navigationError = error.localizedDescription
          if let latest = try? await model.fetchBrowserState(botId: botId) { state = latest }
        }
      }
    }
  }
  private func close() {
    guard groupId == nil else { return }
    Task {
      if await model.endBrowserHandoff(botId: botId) {
        state = model.browserStates[botId]
        navigationError = nil
      }
    }
  }
  private func forget() {
    guard let api = model.api, groupId == nil else { return }
    let session = model.sessionGeneration
    guard model.beginBrowserOperation(botId: botId) else { return }
    loading = true
    Task {
      defer { finishOperation(session: session) }
      do {
        try await api.forgetBrowserLogin(botId: botId)
        guard model.sessionIsCurrent(session, api: api) else { return }
        await refresh()
      } catch {
        if model.sessionIsCurrent(session, api: api) { model.present(error) }
      }
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

private final class BrowserViewerCoordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
  var signedURL: URL
  var viewport: BrowserViewport?
  var onReconnect: () -> Void
  var onError: (String?) -> Void
  private var loaded = false
  private var detached = false
  private var injectedURL: URL?

  init(signedURL: URL, viewport: BrowserViewport?, onReconnect: @escaping () -> Void,
    onError: @escaping (String?) -> Void
  ) {
    self.signedURL = signedURL
    self.viewport = viewport
    self.onReconnect = onReconnect
    self.onError = onError
  }

  func update(_ view: WKWebView, signedURL: URL, viewport: BrowserViewport?) {
    self.signedURL = signedURL
    self.viewport = viewport
    if loaded { injectSession(into: view) }
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    guard !detached else { return }
    loaded = true
    injectSession(into: webView)
  }

  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
    withError error: Error
  ) {
    guard !detached else { return }
    loaded = false
    injectedURL = nil
    onError("Couldn’t load the live browser. Check your connection and choose Reconnect Live View.")
  }

  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
    guard !detached else { return }
    loaded = false
    injectedURL = nil
    onError("The live browser connection was interrupted. Choose Reconnect Live View.")
  }

  func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
    guard !detached else { return }
    loaded = false
    injectedURL = nil
    onError("The live browser stopped responding. Choose Reconnect Live View.")
  }

  func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
    guard !detached, message.frameInfo.isMainFrame,
      message.frameInfo.securityOrigin.protocol == "https",
      ["heytim.ai", "www.heytim.ai"].contains(message.frameInfo.securityOrigin.host),
      let body = message.body as? [String: String] else { return }
    if body["action"] == "reconnect" {
      onReconnect()
      return
    }
    guard let phase = body["state"] else { return }
    switch phase {
    case "connecting", "connected": onError(nil)
    case "failed", "disconnected", "timeout":
      onError("The live browser could not stay connected. Choose Reconnect Live View to try again.")
    default: break
    }
  }

  func detach(_ view: WKWebView) {
    detached = true
    view.configuration.userContentController.removeScriptMessageHandler(forName: "heytimBrowserStatus")
    view.navigationDelegate = nil
    view.stopLoading()
    view.loadHTMLString("", baseURL: nil)
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
      if error != nil, self?.detached == false {
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
    let onReconnect: () -> Void
    let onError: (String?) -> Void
    func makeCoordinator() -> BrowserViewerCoordinator {
      BrowserViewerCoordinator(signedURL: signedURL, viewport: viewport,
        onReconnect: onReconnect, onError: onError)
    }
    func makeUIView(context: Context) -> WKWebView {
      let config = WKWebViewConfiguration()
      config.websiteDataStore = .nonPersistent()
      config.userContentController.add(context.coordinator, name: "heytimBrowserStatus")
      let view = WKWebView(frame: .zero, configuration: config)
      view.navigationDelegate = context.coordinator
      view.load(URLRequest(url: BrowserViewerPage.url))
      return view
    }
    func updateUIView(_ view: WKWebView, context: Context) {
      context.coordinator.update(view, signedURL: signedURL, viewport: viewport)
    }
    static func dismantleUIView(_ view: WKWebView, coordinator: BrowserViewerCoordinator) {
      coordinator.detach(view)
    }
  }
#elseif os(macOS)
  private struct BrowserWebView: NSViewRepresentable {
    let signedURL: URL
    let viewport: BrowserViewport?
    let onReconnect: () -> Void
    let onError: (String?) -> Void
    func makeCoordinator() -> BrowserViewerCoordinator {
      BrowserViewerCoordinator(signedURL: signedURL, viewport: viewport,
        onReconnect: onReconnect, onError: onError)
    }
    func makeNSView(context: Context) -> WKWebView {
      let config = WKWebViewConfiguration()
      config.websiteDataStore = .nonPersistent()
      config.userContentController.add(context.coordinator, name: "heytimBrowserStatus")
      let view = WKWebView(frame: .zero, configuration: config)
      view.navigationDelegate = context.coordinator
      view.load(URLRequest(url: BrowserViewerPage.url))
      return view
    }
    func updateNSView(_ view: WKWebView, context: Context) {
      context.coordinator.update(view, signedURL: signedURL, viewport: viewport)
    }
    static func dismantleNSView(_ view: WKWebView, coordinator: BrowserViewerCoordinator) {
      coordinator.detach(view)
    }
  }
#endif
