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

  var body: some View {
    VStack(spacing: 0) {
      VStack(alignment: .trailing, spacing: 10) {
        HStack(spacing: 8) {
          TextField("https://example.com", text: $address)
            .textFieldStyle(.roundedBorder)
            .accessibilityLabel("Website address")
            .disabled(isBusy)
            .onSubmit { open() }
          Button("Open") { open() }
            .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
            .disabled(isBusy)
        }
        if state?.status == "human_control" {
          Button("Return Control", systemImage: "arrow.uturn.backward") { resume() }
            .froggyGlassButton(tint: FrogTheme.accent)
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
        BrowserWebView(url: url)
      } else {
        ContentUnavailableView(
          state?.status == "expired" ? "Session expired" : "Browser is ready",
          systemImage: "globe",
          description: Text(
            state?.contextLabel
              ?? "Open a website when a bot asks you to sign in or complete a private step.")
        )
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
            Task { await refresh() }
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
          botId: botId, groupId: groupId, url: URL(string: address), display: display)
      } catch { model.present(error) }
    }
  }
  private func resume() {
    loading = true
    Task {
      defer { loading = false }
      do { state = try await model.api?.resumeBrowser(botId: botId, groupId: groupId) } catch {
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

#if os(iOS)
  private struct BrowserWebView: UIViewRepresentable {
    let url: URL
    func makeUIView(context: Context) -> WKWebView { WKWebView() }
    func updateUIView(_ view: WKWebView, context: Context) {
      if view.url != url { view.load(URLRequest(url: url)) }
    }
  }
#elseif os(macOS)
  private struct BrowserWebView: NSViewRepresentable {
    let url: URL
    func makeNSView(context: Context) -> WKWebView { WKWebView() }
    func updateNSView(_ view: WKWebView, context: Context) {
      if view.url != url { view.load(URLRequest(url: url)) }
    }
  }
#endif
