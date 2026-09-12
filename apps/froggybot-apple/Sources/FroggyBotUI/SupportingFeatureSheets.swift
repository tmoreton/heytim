import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

struct SkillEditor: View {
  @Bindable var model: AppModel
  let id: String?
  @State private var draft = SkillDraft()
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    Form {
      TextField("Name", text: $draft.name)
      TextField("Description", text: $draft.description, axis: .vertical)
      Section("Instructions") { TextEditor(text: $draft.instructions).frame(minHeight: 180) }
      Section("Required tools") {
        ForEach(model.bootstrap?.tools ?? []) { tool in
          Toggle(
            isOn: Binding(
              get: { draft.requiredToolIds.contains(tool.id) },
              set: { enabled in
                if enabled {
                  draft.requiredToolIds.append(tool.id)
                } else {
                  draft.requiredToolIds.removeAll { $0 == tool.id }
                }
              }
            )
          ) {
            VStack(alignment: .leading) {
              Text(tool.name)
              Text(tool.description).font(.caption).foregroundStyle(.secondary)
            }
          }
        }
      }
      Picker("Visibility", selection: $draft.visibility) {
        Text("Private").tag("private")
        Text("Anyone with link").tag("link")
      }
    }
    .navigationTitle(id == nil ? "New skill" : "Edit skill").toolbar {
      CloseButton()
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") {
          Task {
            do {
              _ = try await model.api?.saveSkill(draft, id: id)
              await model.refreshBootstrap()
              dismiss()
            } catch { model.present(error) }
          }
        }.disabled(draft.name.isEmpty || draft.instructions.isEmpty)
      }
    }
    .task {
      if let id {
        do {
          if let value = try await model.api?.skill(id) { draft = SkillDraft(skill: value) }
        } catch { model.present(error) }
      }
    }
  }
}

struct ConnectionsView: View {
  @Bindable var model: AppModel
  @Environment(\.openURL) private var openURL
  @State private var connections: [Capability] = []
  var body: some View {
    List {
      Section("Available") {
        ForEach(model.bootstrap?.connectionProviders ?? []) { provider in
          HStack {
            VStack(alignment: .leading) {
              Text(provider.name).font(.headline)
              Text(provider.permissionsSummary).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Connect") { connect(provider.id) }
          }
        }
      }
      Section("Connected") {
        ForEach(connections) { item in
          HStack {
            Text(item.name)
            Spacer()
            Button("Disconnect", role: .destructive) { remove(item.id) }
          }
        }
      }
    }.navigationTitle("Connections").toolbar { CloseButton() }.task { await load() }
  }
  private func load() async {
    do { connections = try await model.api?.connections() ?? [] } catch { model.present(error) }
  }
  private func connect(_ id: String) {
    Task {
      do {
        if let url = try await model.api?.beginConnection(
          providerId: id, returnURL: URL(string: "froggybot://app")!)
        {
          openURL(url)
        }
      } catch { model.present(error) }
    }
  }
  private func remove(_ id: String) {
    Task {
      do {
        try await model.api?.deleteConnection(id)
        await load()
      } catch { model.present(error) }
    }
  }
}

struct DocumentsView: View {
  @Bindable var model: AppModel
  let botId: String
  @Environment(\.openURL) private var openURL
  @State private var documents: [BotDocument] = []
  var body: some View {
    List(documents) { document in
      Button {
        open(document)
      } label: {
        HStack {
          Image(systemName: document.kind == "image" ? "photo" : "doc")
          VStack(alignment: .leading) {
            Text(document.name)
            Text(ByteCountFormatter.string(fromByteCount: Int64(document.size), countStyle: .file))
              .font(.caption).foregroundStyle(.secondary)
          }
        }
      }
    }
    .navigationTitle("Documents").toolbar { CloseButton() }.task {
      do { documents = try await model.api?.botDocuments(botId) ?? [] } catch {
        model.present(error)
      }
    }
  }
  private func open(_ item: BotDocument) {
    Task {
      do { if let url = try await model.api?.downloadURL(fileId: item.id) { openURL(url) } } catch {
        model.present(error)
      }
    }
  }
}

struct ShareView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  @State private var url: URL?
  var body: some View {
    VStack(spacing: 22) {
      Image(systemName: "person.2.badge.plus").font(.system(size: 48)).foregroundStyle(
        FrogTheme.green)
      Text("Share \(model.title)").font(.title2.bold())
      Text("Anyone with this link can accept the invitation before it expires.").foregroundStyle(
        .secondary
      ).multilineTextAlignment(.center)
      if let url {
        Text(url.absoluteString).textSelection(.enabled).font(.caption)
        ShareLink(item: url) { Label("Share invitation", systemImage: "square.and.arrow.up") }
          .buttonStyle(.borderedProminent)
      } else {
        ProgressView()
      }
    }.padding(32).navigationTitle("Share").toolbar { CloseButton() }.task {
      await model.shareCurrent()
      url = model.lastSharedURL
    }
  }
}

struct AccountView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  @State private var links: [SharedLink] = []
  @State private var confirmDelete = false
  var body: some View {
    List {
      Section("Notifications") {
        Button("Enable reply notifications") {
          Task {
            do { try await NativeNotifications.requestAuthorization() } catch {
              model.present(error)
            }
          }
        }
      }
      Section("Shared links") {
        ForEach(links) { link in
          HStack {
            VStack(alignment: .leading) {
              Text(link.title)
              Text(link.kind.capitalized).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if let url = URL(string: link.url) { ShareLink(item: url) }
          }
        }.onDelete(perform: revoke)
      }
      Section("Data") {
        Button("Export memory") { exportMemory() }
        Button("Sign out") {
          Task {
            await model.unregisterPush()
            await auth.signOut()
          }
        }
        Button("Delete account", role: .destructive) { confirmDelete = true }
      }
      Section("About") {
        LabeledContent("App", value: "FroggyBot for Apple")
        LabeledContent("Platforms", value: "iPhone + Mac")
      }
    }.navigationTitle("Account").toolbar { CloseButton() }.task { await load() }
      .confirmationDialog("Permanently delete your FroggyBot account?", isPresented: $confirmDelete)
    {
      Button("Delete account", role: .destructive) {
        Task {
          do {
            try await model.api?.deleteAccount()
            await auth.signOut()
          } catch { model.present(error) }
        }
      }
    }
  }
  private func load() async {
    do { links = try await model.api?.shares() ?? [] } catch { model.present(error) }
  }
  private func revoke(at offsets: IndexSet) {
    for index in offsets {
      let token = links[index].token
      Task {
        do {
          try await model.api?.revokeShare(token)
          await load()
        } catch { model.present(error) }
      }
    }
  }
  private func exportMemory() {
    Task {
      do {
        if let url = try await model.api?.exportMemory() {
          #if os(iOS)
            await UIApplication.shared.open(url)
          #else
            NSWorkspace.shared.open(url)
          #endif
        }
      } catch { model.present(error) }
    }
  }
}
