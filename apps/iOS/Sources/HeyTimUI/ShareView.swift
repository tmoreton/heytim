import SwiftUI

struct ShareView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  var showsDismissButton = true
  @State private var url: URL?
  @State private var creatingLink = false
  @State private var includeChatHistory = false
  var body: some View {
    VStack(spacing: 22) {
      Image(systemName: "person.2.badge.plus").froggyFont(size: 48, relativeTo: .title).foregroundStyle(
        FrogTheme.green)
      Text(selection.kind == .group ? "Invite someone to \(title)" : "Share a copy of \(title)")
        .froggyFont(.title2, weight: .bold)
      Text(selection.kind == .group
        ? "Anyone with this link can join the live room and see its shared conversation."
        : includeChatHistory
          ? "The recipient gets their own copy of this bot and up to 100 recent text exchanges. Attachments and private connections are not copied."
          : "The recipient gets their own copy of this bot's setup. Your conversation stays private.")
        .foregroundStyle(
        .secondary
      ).multilineTextAlignment(.center)
      if selection.kind == .bot && url == nil {
        Toggle("Include recent chat messages", isOn: $includeChatHistory)
          .toggleStyle(.switch)
          .frame(maxWidth: 360)
      }
      Text("The link expires in 30 days. You can revoke it in Settings → Shared links.")
        .froggyFont(.footnote).foregroundStyle(.secondary)
        .multilineTextAlignment(.center)
      if let url {
        Text(url.absoluteString).textSelection(.enabled).froggyFont(.caption)
        ShareLink(item: url) { Label("Share invitation", systemImage: "square.and.arrow.up") }
          .froggyGlassButton(prominent: true)
      } else {
        Button { createLink() } label: {
          if creatingLink {
            HStack(spacing: 8) {
              ProgressView()
              Text("Creating Link…")
            }
          } else {
            Label("Create Invitation Link", systemImage: "link.badge.plus")
          }
        }
        .froggyGlassButton(prominent: true)
        .controlSize(.large)
        .disabled(creatingLink)
      }
    }.padding(32).frame(maxWidth: .infinity, maxHeight: .infinity)
      .background(FrogTheme.pageBackground)
      .froggyNavigationTitle("Share")
      .toolbarTitleDisplayMode(.inline)
      .toolbar {
        if showsDismissButton {
          CloseButton { model.sheet = nil }
        }
      }
  }

  private var title: String {
    switch selection.kind {
    case .bot:
      model.bootstrap?.bots.first(where: { $0.id == selection.id })?.name ?? "Hey Tim"
    case .group:
      model.bootstrap?.groups.first(where: { $0.id == selection.id })?.name ?? "Group"
    }
  }

  private func createLink() {
    creatingLink = true
    Task {
      url = await model.share(selection, includeChatHistory: includeChatHistory)
      creatingLink = false
    }
  }
}
