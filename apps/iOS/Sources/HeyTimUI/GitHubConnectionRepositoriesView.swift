import SwiftUI

struct GitHubConnectionRepositoriesView: View {
  let connection: Capability
  let refresh: (() -> Void)?

  var body: some View {
    Section("Connected repositories") {
      ForEach(connection.repositories ?? []) { repository in
        Text(repository.name)
      }
      if let url = URL(
        string: connection.managementUrl ?? "https://github.com/settings/installations"
      ) {
        Link(destination: url) {
          Label("Choose repositories on GitHub", systemImage: "arrow.up.right.square")
        }
      }
      if let refresh {
        Button("Refresh repository list", systemImage: "arrow.clockwise", action: refresh)
      }
      Text("Select repositories you own or administer on GitHub. Save, then return here and refresh.")
        .froggyFont(.footnote).foregroundStyle(.secondary)
    }
  }
}
