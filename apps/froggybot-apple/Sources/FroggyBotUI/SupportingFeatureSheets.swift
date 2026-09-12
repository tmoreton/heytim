import SwiftUI
import UserNotifications

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
    .froggyListSurface()
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
    }.froggyListSurface().navigationTitle("Connections").toolbar { CloseButton() }.task { await load() }
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
    .froggyListSurface()
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
          .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
      } else {
        ProgressView()
      }
    }.padding(32).frame(maxWidth: .infinity, maxHeight: .infinity)
      .background(FrogTheme.pageBackground)
      .navigationTitle("Share").toolbar { CloseButton() }.task {
      await model.shareCurrent()
      url = model.lastSharedURL
    }
  }
}

struct AccountView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  @State private var links: [SharedLink] = []
  @State private var loadingLinks = true
  @State private var busyLinkToken: String?
  @State private var notificationsEnabled = false
  @State private var confirmDelete = false
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    Form {
      Section("Manage") {
        NavigationLink {
          MemoriesView(model: model, groupId: nil)
        } label: {
          Label("Memory", systemImage: "brain.head.profile")
        }
        NavigationLink {
          SkillsView(model: model)
        } label: {
          Label("Skills & tools", systemImage: "sparkles")
        }
        NavigationLink {
          ConnectionsView(model: model)
        } label: {
          Label("Connections", systemImage: "link")
        }
      }

      Section {
        LabeledContent {
          Text(notificationsEnabled ? "On" : "Off")
            .foregroundStyle(notificationsEnabled ? FrogTheme.brand : .secondary)
        } label: {
          Label("Reply notifications", systemImage: "bell.badge")
        }
        if !notificationsEnabled {
          Button("Enable Notifications") { enableNotifications() }
        }
      } header: {
        Text("Notifications")
      } footer: {
        Text("Get an alert when a FroggyBot finishes a reply or scheduled task.")
      }

      Section("Active shared links") {
        if loadingLinks {
          HStack {
            Spacer()
            ProgressView()
            Spacer()
          }
        } else if links.isEmpty {
          Label("No active shared links", systemImage: "link.badge.plus")
            .foregroundStyle(.secondary)
        } else {
          ForEach(links) { link in
            HStack(spacing: 12) {
              Label {
                VStack(alignment: .leading, spacing: 2) {
                  Text(link.title).lineLimit(1)
                  Text("\(shareKind(link.kind)) · expires \(shareExpiration(link.expiresAt))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
              } icon: {
                Image(systemName: shareIcon(link.kind))
              }
              Spacer()
              if let url = URL(string: link.url) {
                ShareLink(item: url) {
                  Label("Share", systemImage: "square.and.arrow.up").labelStyle(.iconOnly)
                }
              }
              Button("Revoke", role: .destructive) { revoke(link) }
                .disabled(busyLinkToken != nil)
            }
          }
        }
      }

      Section("Data & privacy") {
        Button { exportMemory() } label: {
          Label("Export Memory", systemImage: "square.and.arrow.down")
        }
      }

      Section {
        Button { signOut() } label: {
          Label("Log Out", systemImage: "rectangle.portrait.and.arrow.right")
        }
      }

      Section {
        Button("Delete Account", systemImage: "trash", role: .destructive) {
          confirmDelete = true
        }
      } footer: {
        Text(
          "Permanently deletes your bots, chats, owned groups, schedules, skills, invitations, and shared links."
        )
      }

      Section("About") {
        LabeledContent("App", value: "FroggyBot for Apple")
        LabeledContent("Platforms", value: "iPhone + Mac")
      }
    }
    .formStyle(.grouped)
    .scrollContentBackground(.hidden)
    .background(FrogTheme.pageBackground)
    .foregroundStyle(FrogTheme.text)
    .navigationTitle("Settings")
    .toolbar {
      ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
    }
    .task { await load() }
    .confirmationDialog(
      "Permanently delete your FroggyBot account?", isPresented: $confirmDelete,
      titleVisibility: .visible
    ) {
      Button("Delete account", role: .destructive) {
        Task {
          do {
            try await model.api?.deleteAccount()
            await auth.signOut()
          } catch { model.present(error) }
        }
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text(
        "This cannot be undone. Shared links will stop working and owned groups will be deleted for every member."
      )
    }
  }

  private func load() async {
    async let notificationLoad: Void = refreshNotificationStatus()
    do {
      links = try await model.api?.shares() ?? []
    } catch {
      model.present(error)
    }
    loadingLinks = false
    _ = await notificationLoad
  }

  private func enableNotifications() {
    Task {
      do {
        try await NativeNotifications.requestAuthorization()
        await refreshNotificationStatus()
      } catch {
        model.present(error)
      }
    }
  }

  private func refreshNotificationStatus() async {
    let settings = await UNUserNotificationCenter.current().notificationSettings()
    notificationsEnabled =
      settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
  }

  private func revoke(_ link: SharedLink) {
    busyLinkToken = link.token
    Task {
      do {
        try await model.api?.revokeShare(link.token)
        links.removeAll { $0.token == link.token }
      } catch {
        model.present(error)
      }
      busyLinkToken = nil
    }
  }

  private func signOut() {
    Task {
      await model.unregisterPush()
      await auth.signOut()
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

  private func shareIcon(_ kind: String) -> String {
    switch kind {
    case "bot": "bubble.left.and.sparkles"
    case "group": "person.3"
    case "skill": "sparkles"
    default: "bubble.left.and.bubble.right"
    }
  }

  private func shareKind(_ kind: String) -> String {
    switch kind {
    case "bot": "Bot setup"
    case "group": "Group invite"
    case "skill": "Skill"
    default: "Conversation"
    }
  }

  private func shareExpiration(_ timestamp: Int) -> String {
    Date(timeIntervalSince1970: TimeInterval(timestamp)).formatted(
      .dateTime.month(.abbreviated).day().year())
  }
}
