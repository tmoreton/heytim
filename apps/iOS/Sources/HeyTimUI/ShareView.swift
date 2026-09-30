import SwiftUI

struct ShareView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  var showsDismissButton = true
  @State private var url: URL?
  @State private var creatingLink = false
  var body: some View {
    VStack(spacing: 22) {
      Image(systemName: "person.2.badge.plus").froggyFont(size: 48, relativeTo: .title).foregroundStyle(
        FrogTheme.green)
      Text("Share \(title)").froggyFont(.title2, weight: .bold)
      Text("Anyone with this link can accept the invitation before it expires.").foregroundStyle(
        .secondary
      ).multilineTextAlignment(.center)
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
        Text("The link becomes active only after you create it, and you can revoke it from Settings.")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
          .multilineTextAlignment(.center)
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
      url = await model.share(selection)
      creatingLink = false
    }
  }
}
