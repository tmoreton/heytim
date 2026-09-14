import SwiftUI
import WebKit

struct BrowserHandoffView: View {
  @Bindable var model: AppModel
  let botId: String
  let groupId: String?
  @State private var state: BrowserState?
  @State private var address = ""
  @State private var loading = false

  var body: some View {
    VStack(spacing: 0) {
      HStack {
        TextField("https://example.com", text: $address).textFieldStyle(.roundedBorder).onSubmit {
          open()
        }
        Button("Open") { open() }
          .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
          .disabled(loading)
        if state?.status == "human_control" { Button("Return control") { resume() } }
      }.padding()
      Divider()
      if let raw = state?.liveViewUrl, let url = URL(string: raw) {
        BrowserWebView(url: url)
      } else {
        ContentUnavailableView(
          state?.status == "expired" ? "Session expired" : "Browser is ready",
          systemImage: "globe",
          description: Text(
            state?.contextLabel
              ?? "Open a website when a bot asks you to sign in or complete a private step.")
        )
      }
    }
    .navigationTitle("Secure browser handoff")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      CloseButton { model.sheet = nil }
      ToolbarItem(placement: .primaryAction) {
        Menu {
          Button("Disconnect browser", role: .destructive) { close() }.disabled(
            state?.status == "closed")
          Button("Forget saved login", role: .destructive) { forget() }.disabled(
            state?.hasSavedLogin != true)
        } label: {
          Image(systemName: "ellipsis.circle")
        }
      }
    }
    .task { await refresh() }
  }

  private func refresh() async {
    guard let api = model.api else { return }
    do { state = try await api.browserState(botId: botId, groupId: groupId) } catch {
      model.present(error)
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
