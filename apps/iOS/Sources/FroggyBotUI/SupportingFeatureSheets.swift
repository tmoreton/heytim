import SwiftUI
import AuthenticationServices
import Observation
import QuickLook
import UniformTypeIdentifiers
import UserNotifications

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

enum WebAuthenticationOutcome: Equatable, Sendable {
  case callback(URL)
  case cancelled
  case failed(String)
}

@MainActor @Observable
final class WebAuthenticationController: NSObject,
  ASWebAuthenticationPresentationContextProviding
{
  private var session: ASWebAuthenticationSession?
  var outcome: WebAuthenticationOutcome?
  var isRunning = false

  func start(url: URL) {
    outcome = nil
    isRunning = true
    let session = ASWebAuthenticationSession(
      url: url, callbackURLScheme: "froggybot"
    ) { @Sendable [weak self] callbackURL, error in
      self?.finish(callbackURL: callbackURL, error: error)
    }
    session.presentationContextProvider = self
    session.prefersEphemeralWebBrowserSession = false
    self.session = session
    if !session.start() {
      self.session = nil
      isRunning = false
      outcome = .failed("The sign-in window could not be opened.")
    }
  }

  // AuthenticationServices completes on a SafariLaunchAgent XPC queue on macOS.
  // Keep this boundary nonisolated, then cross to the main actor for UI state.
  nonisolated func finish(callbackURL: URL?, error: Error?) {
    let nextOutcome: WebAuthenticationOutcome
    if let callbackURL {
      nextOutcome = .callback(callbackURL)
    } else if let authenticationError = error as? ASWebAuthenticationSessionError,
      authenticationError.code == .canceledLogin
    {
      nextOutcome = .cancelled
    } else {
      nextOutcome = .failed(error?.localizedDescription ?? "The sign-in window could not be opened.")
    }
    Task { @MainActor [weak self] in
      self?.session = nil
      self?.isRunning = false
      self?.outcome = nextOutcome
    }
  }

  func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
    #if os(iOS)
      return UIApplication.shared.connectedScenes
        .compactMap { $0 as? UIWindowScene }
        .flatMap(\.windows)
        .first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    #else
      return NSApplication.shared.keyWindow ?? ASPresentationAnchor()
    #endif
  }
}

struct SkillEditor: View {
  @Bindable var model: AppModel
  let id: String?
  var showsDismissButton = true
  @State private var draft = SkillDraft()
  @State private var loading = false
  @State private var saving = false
  @State private var loadError: String?
  @Environment(\.dismiss) private var dismiss

  private var nameIssue: String? {
    if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Enter a skill name."
    }
    if draft.name.count > model.constraints.skillNameMaxLength {
      return "Keep the name under \(model.constraints.skillNameMaxLength) characters."
    }
    return nil
  }

  private var descriptionIssue: String? {
    draft.description.count > model.constraints.skillDescriptionMaxLength
      ? "The description is longer than the supported limit." : nil
  }

  private var instructionsIssue: String? {
    if draft.instructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Add instructions so the bot knows when and how to use this skill."
    }
    if draft.instructions.count > model.constraints.skillInstructionsMaxLength {
      return "The instructions are longer than the supported limit."
    }
    return nil
  }

  private var canSave: Bool {
    nameIssue == nil && descriptionIssue == nil && instructionsIssue == nil && !loading && !saving
  }

  var body: some View {
    Group {
      if loading {
        ProgressView("Loading skill…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if let loadError {
        ContentUnavailableView {
          Label("Couldn’t Load Skill", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      } else {
        Form {
          Section {
            TextField("Name", text: $draft.name)
            TextField("Description", text: $draft.description, axis: .vertical)
          } header: {
            Text("Overview")
          } footer: {
            VStack(alignment: .leading, spacing: 4) {
              Text(nameIssue ?? descriptionIssue ?? "Use a clear name and a short description people can scan quickly.")
              Text("\(draft.description.count.formatted()) / \(model.constraints.skillDescriptionMaxLength.formatted())")
                .monospacedDigit()
            }
            .foregroundStyle(
              nameIssue == nil && descriptionIssue == nil ? Color.secondary : Color.red)
          }

          Section {
            GuidedTextEditor(
              title: "Skill instructions",
              prompt: "Explain when to use this skill, the steps to follow, and what a good result looks like.",
              text: $draft.instructions,
              minHeight: 180)
          } header: {
            Text("Instructions")
          } footer: {
            HStack(alignment: .firstTextBaseline) {
              Text(instructionsIssue ?? "These instructions guide the bot whenever the skill is active.")
              Spacer(minLength: 12)
              Text(
                "\(draft.instructions.count.formatted()) / \(model.constraints.skillInstructionsMaxLength.formatted())"
              )
              .monospacedDigit()
            }
            .foregroundStyle(instructionsIssue == nil ? Color.secondary : Color.red)
          }

          Section {
            let tools = model.bootstrap?.tools ?? []
            ForEach(tools) { tool in
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
                VStack(alignment: .leading, spacing: 3) {
                  Text(tool.name)
                  Text(tool.description).froggyFont(.caption).foregroundStyle(.secondary)
                }
              }
            }
            if tools.isEmpty {
              Text("No tools are available.").foregroundStyle(.secondary)
            }
          } header: {
            Text("Required Tools")
          } footer: {
            Text("Selected tools are enabled whenever a bot uses this skill.")
          }

          Section {
            Picker("Visibility", selection: $draft.visibility) {
              Text("Private").tag("private")
              Text("Anyone with link").tag("link")
            }
          } footer: {
            Text(
              draft.visibility == "link"
                ? "People with a share link can add a copy of this skill."
                : "Only you can use this skill."
            )
          }
        }
        .formStyle(.grouped)
        .froggyListSurface()
      }
    }
    .background(FrogTheme.pageBackground)
    .froggyNavigationTitle(id == nil ? "New skill" : "Edit skill")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton()
      }
      if loadError == nil && !loading {
        ToolbarItem(placement: .confirmationAction) {
          Button {
            save()
          } label: {
            if saving {
              Label { Text("Saving…") } icon: { ProgressView().controlSize(.small) }
            } else {
              Text("Save")
            }
          }
          .disabled(!canSave)
        }
      }
    }
    .task { await load() }
  }

  private func load() async {
    guard let id else { return }
    loading = true
    defer { loading = false }
    do {
      draft = SkillDraft(skill: try await model.requireAPI().skill(id))
      loadError = nil
    } catch {
      loadError = error.localizedDescription
    }
  }

  private func save() {
    saving = true
    Task {
      defer { saving = false }
      do {
        _ = try await model.requireAPI().saveSkill(draft, id: id)
        await model.refreshBootstrap()
        dismiss()
      } catch {
        model.present(error)
      }
    }
  }
}

struct ConnectionsView: View {
  @Bindable var model: AppModel
  var showsDismissButton = true
  @State private var connections: [Capability] = []
  @State private var loading = true
  @State private var loadError: String?
  @State private var connectingProviderID: String?
  @State private var disconnectCandidate: Capability?
  @State private var successMessage: String?
  @State private var webAuthentication = WebAuthenticationController()

  private var providers: [ConnectionProvider] { model.bootstrap?.connectionProviders ?? [] }

  var body: some View {
    List {
      if let loadError {
        Section {
          ContentUnavailableView {
            Label("Couldn’t Load Accounts", systemImage: "wifi.exclamationmark")
          } description: {
            Text(loadError)
          } actions: {
            Button("Try Again") { Task { await load() } }
          }
        }
      } else {
        Section("Accounts") {
          ForEach(connectionProviderFamilies(providers)) { family in
            if family.grouped {
              connectionFamily(family)
            } else if let provider = family.providers.first {
              providerAccessRow(provider)
            }
          }
          if providers.isEmpty && !loading {
            Text("No account providers are available.").foregroundStyle(.secondary)
          }
        }
      }
    }
    .froggyListSurface()
    #if os(macOS)
      .froggyNavigationTitle("Connected Accounts")
    #else
      .navigationTitle("")
    #endif
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
    }
    .overlay { if loading { ProgressView() } }
    .refreshable { await load() }
    .task { await load() }
    .onChange(of: webAuthentication.outcome) { _, outcome in
      guard let outcome else { return }
      switch outcome {
      case .callback(let url):
        Task {
          if let callback = await model.handleConnectionCallback(url),
            callback.status == .connected
          {
            successMessage = "\(providerName(callback.providerID)) is now connected."
            await load()
          }
          connectingProviderID = nil
        }
      case .cancelled:
        connectingProviderID = nil
      case .failed(let message):
        connectingProviderID = nil
        model.present(APIError.configuration(message))
      }
      webAuthentication.outcome = nil
    }
    .alert(
      "Account Connected",
      isPresented: Binding(
        get: { successMessage != nil }, set: { if !$0 { successMessage = nil } })
    ) {
      Button("OK") { successMessage = nil }
    } message: {
      Text(successMessage ?? "")
    }
    .confirmationDialog(
      "Disconnect \(disconnectCandidate?.name ?? "this account")?",
      isPresented: Binding(
        get: { disconnectCandidate != nil }, set: { if !$0 { disconnectCandidate = nil } }),
      titleVisibility: .visible
    ) {
      if let disconnectCandidate {
        Button("Disconnect", role: .destructive) { remove(disconnectCandidate) }
      }
      Button("Cancel", role: .cancel) { disconnectCandidate = nil }
    } message: {
      Text("Bots using this account will lose access. FroggyBot will revoke supported OAuth access and schedule its stored credential for deletion.")
    }
  }

  private func load() async {
    loading = true
    defer { loading = false }
    do {
      connections = try await model.requireAPI().connections()
      loadError = nil
    } catch {
      loadError = error.localizedDescription
    }
  }

  private func connect(_ id: String) {
    connectingProviderID = id
    Task {
      do {
        var callback = URLComponents()
        callback.scheme = "froggybot"
        callback.host = "app"
        callback.queryItems = [URLQueryItem(name: "connection", value: id)]
        guard let returnURL = callback.url else { throw APIError.invalidResponse }
        let url = try await model.requireAPI().beginConnection(
          providerId: id, returnURL: returnURL)
        webAuthentication.start(url: url)
      } catch {
        connectingProviderID = nil
        model.present(error)
      }
    }
  }

  private func remove(_ connection: Capability) {
    disconnectCandidate = nil
    Task {
      do {
        try await model.requireAPI().deleteConnection(connection.id)
        await model.refreshBootstrap()
        await load()
      } catch { model.present(error) }
    }
  }

  private func connection(for providerID: String) -> Capability? {
    connections.first { $0.provider == providerID }
  }

  private func providerName(_ id: String) -> String {
    providers.first(where: { $0.id == id })?.name ?? "Account"
  }

  @ViewBuilder
  private func providerAccessRow(_ provider: ConnectionProvider, nested: Bool = false) -> some View {
    if let connection = connection(for: provider.id) {
      NavigationLink {
        ConnectionDetailView(
          connection: connection, provider: provider,
          reconnect: { connect(provider.id) },
          disconnect: { disconnectCandidate = connection })
      } label: {
        connectionRow(
          connection, provider: provider,
          displayName: nested ? provider.name : nil)
      }
    } else {
      HStack(spacing: 12) {
        ProviderLogoView(provider: provider)
        VStack(alignment: .leading, spacing: 3) {
          Text(provider.name).froggyFont(.headline)
          Text(provider.description).froggyFont(.caption).foregroundStyle(.secondary)
          Text(provider.permissionsSummary).froggyFont(.caption2).foregroundStyle(.tertiary)
        }
        Spacer()
        if connectingProviderID == provider.id {
          ProgressView()
            .controlSize(.small)
            .accessibilityLabel("Connecting \(provider.name)")
        } else {
          Button(provider.connectLabel) {
            connect(provider.id)
          }
          .disabled(connectingProviderID != nil || webAuthentication.isRunning)
        }
      }
    }
  }

  private func connectionFamily(_ family: ConnectionProviderFamily) -> some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .top, spacing: 12) {
        ProviderLogoView(providerID: family.logoProviderId, iconText: family.iconText)
        VStack(alignment: .leading, spacing: 4) {
          HStack(spacing: 8) {
            Text(family.name).froggyFont(.headline)
            if family.includedSummary != nil {
              Text("Included")
                .froggyFont(.caption2, weight: .bold)
                .foregroundStyle(FrogTheme.accent)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(FrogTheme.accent.opacity(0.12), in: Capsule())
            }
          }
          Text(family.description).froggyFont(.caption).foregroundStyle(.secondary)
          if let includedSummary = family.includedSummary {
            Text(includedSummary).froggyFont(.caption2).foregroundStyle(.tertiary)
          }
        }
      }
      ForEach(family.providers) { provider in
        Divider()
        providerAccessRow(provider, nested: true)
      }
    }
    .padding(.vertical, 4)
  }

  private func connectionRow(
    _ connection: Capability, provider: ConnectionProvider?, displayName: String? = nil
  ) -> some View {
    HStack(spacing: 12) {
      if let provider {
        ProviderLogoView(provider: provider)
      } else {
        Image(systemName: "link")
          .frame(width: 36, height: 36)
          .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
      }
      VStack(alignment: .leading, spacing: 3) {
        Text(displayName ?? connection.name).froggyFont(.headline)
        Text(connection.connectedAccount ?? connection.description)
          .froggyFont(.caption).foregroundStyle(.secondary).lineLimit(2)
      }
      Spacer()
      Text(connection.connectionStatus == "connected" ? "Connected" : "Needs Attention")
        .froggyFont(.caption)
        .foregroundStyle(connection.connectionStatus == "connected" ? FrogTheme.accent : .orange)
    }
  }
}

private struct ConnectionDetailView: View {
  let connection: Capability
  let provider: ConnectionProvider?
  let reconnect: (() -> Void)?
  let disconnect: () -> Void

  var body: some View {
    Form {
      Section {
        LabeledContent("Status", value: statusLabel)
        if let account = connection.connectedAccount {
          LabeledContent("Account", value: account)
        }
        if let updatedAt = connection.updatedAt?.froggyDate {
          LabeledContent("Last updated", value: updatedAt.formatted(date: .abbreviated, time: .shortened))
        }
      }
      Section(provider?.privacyTitle ?? "Private Connection") {
        Text(provider?.privacyDescription ?? connection.description)
      }
      if let actions = connection.actions, !actions.isEmpty {
        Section("Access") {
          ForEach(actions, id: \.self) { action in
            Label(action, systemImage: "checkmark.circle")
          }
          if let permissions = provider?.permissionsSummary {
            Text(permissions).froggyFont(.footnote).foregroundStyle(.secondary)
          }
        }
      }
      Section {
        if let reconnect {
          Button(
            provider?.reconnectLabel ?? "Reconnect Account",
            systemImage: "arrow.clockwise", action: reconnect)
        }
        Button("Disconnect", systemImage: "link.badge.minus", role: .destructive, action: disconnect)
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle(connection.name)
    .toolbarTitleDisplayMode(.inline)
  }

  private var statusLabel: String {
    connection.connectionStatus == "connected" ? "Connected" : "Needs attention"
  }
}

struct DocumentsView: View {
  @Bindable var model: AppModel
  let botId: String
  var showsDismissButton = true
  @State private var documents: [BotDocument] = []
  @State private var previewURL: URL?
  @State private var previewTask: Task<Void, Never>?
  @State private var isLoading = false
  @State private var loadError: String?
  var body: some View {
    List {
      ForEach(documents) { document in
        Button {
          open(document)
        } label: {
          Label {
            VStack(alignment: .leading) {
              Text(document.name)
              Text(
                ByteCountFormatter.string(
                  fromByteCount: Int64(document.size), countStyle: .file)
              )
              .froggyFont(.caption).foregroundStyle(.secondary)
            }
          } icon: {
            Image(systemName: document.kind == "image" ? "photo" : "doc")
          }
        }
        .buttonStyle(.plain)
        .contextMenu {
          Button("Quick Look", systemImage: "eye") { open(document) }
        }
      }
    }
    .froggyListSurface()
    .froggyNavigationTitle("Documents")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
    }
    .overlay {
      if isLoading && documents.isEmpty {
        ProgressView("Loading documents…")
      } else if let loadError, documents.isEmpty {
        ContentUnavailableView {
          Label("Couldn’t Load Documents", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      } else if documents.isEmpty {
        ContentUnavailableView(
          "No Documents", systemImage: "doc",
          description: Text("Documents created or shared in this chat will appear here."))
      }
    }
    .quickLookPreview($previewURL)
    .onChange(of: previewURL) { previous, current in
      if previous != current { FrogBotAPI.removeDownloadedPreview(at: previous) }
    }
    .onDisappear {
      previewTask?.cancel()
      FrogBotAPI.removeDownloadedPreview(at: previewURL)
      previewURL = nil
    }
    .refreshable { await load() }
    .task { await load() }
  }
  private func open(_ item: BotDocument) {
    previewTask?.cancel()
    let api = model.api
    previewTask = Task {
      do {
        guard let downloaded = try await api?.downloadFile(fileId: item.id, name: item.name)
        else { return }
        guard !Task.isCancelled else {
          FrogBotAPI.removeDownloadedPreview(at: downloaded)
          return
        }
        previewURL = downloaded
      } catch {
        if !Task.isCancelled { model.present(error) }
      }
    }
  }
  private func load() async {
    isLoading = true
    defer { isLoading = false }
    guard let api = model.api else {
      loadError = nil
      return
    }
    do {
      documents = try await api.botDocuments(botId)
      loadError = nil
    } catch {
      if documents.isEmpty {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
  }
}

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
          .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
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
        .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
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
      model.bootstrap?.bots.first(where: { $0.id == selection.id })?.name ?? "FroggyBot"
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

private struct MemoryExportDocument: FileDocument {
  static var readableContentTypes: [UTType] { [.json] }
  let data: Data

  init(data: Data) { self.data = data }

  init(configuration: ReadConfiguration) throws {
    guard let data = configuration.file.regularFileContents else {
      throw CocoaError(.fileReadCorruptFile)
    }
    self.data = data
  }

  func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
    FileWrapper(regularFileWithContents: data)
  }
}

struct AccountView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  var showsDismissButton = true
  @AppStorage(FroggyPreferenceKeys.appearance) private var appearance =
    FroggyAppearancePreference.system.rawValue
  @AppStorage(FroggyPreferenceKeys.textSize) private var textSize =
    FroggyTextSizePreference.platformDefaultRawValue
  @State private var links: [SharedLink] = []
  @State private var loadingLinks = true
  @State private var linksError: String?
  @State private var busyLinkToken: String?
  @State private var revokeCandidate: SharedLink?
  @State private var notificationAuthorization = UNAuthorizationStatus.notDetermined
  @State private var confirmDelete = false
  @State private var deletingAccount = false
  @State private var exportingMemory = false
  @State private var memoryExportDocument: MemoryExportDocument?
  @State private var showingMemoryExporter = false

  var body: some View {
    Form {
      Section("Build Your Team") {
        NavigationLink {
          BotLibrary(model: model, showsDismissButton: false)
        } label: {
          Label("Add a Bot", systemImage: "plus.circle.fill")
        }
      }

      Section("Manage") {
        NavigationLink {
          MemoriesView(model: model, groupId: nil, showsDismissButton: false)
        } label: {
          Label("Memory", systemImage: "brain.head.profile")
        }
        NavigationLink {
          SkillsView(model: model, showsDismissButton: false)
        } label: {
          Label("Tools & Skills", systemImage: "wrench.and.screwdriver")
        }
        NavigationLink {
          ConnectionsView(model: model, showsDismissButton: false)
        } label: {
          Label("Connected Accounts", systemImage: "link")
        }
      }

      Section {
        Picker("Appearance", selection: $appearance) {
          ForEach(FroggyAppearancePreference.allCases) { preference in
            Text(preference.title).tag(preference.rawValue)
          }
        }
        .accessibilityIdentifier("settings.appearance")

        Picker("Text Size", selection: $textSize) {
          ForEach(FroggyTextSizePreference.allCases) { preference in
            Text(preference.title).tag(preference.rawValue)
          }
        }
        .accessibilityIdentifier("settings.text-size")
      } header: {
        Text("Display")
      } footer: {
        Text("Changes apply immediately and stay on this device.")
      }

      Section {
        LabeledContent {
          Text(notificationStatusLabel)
            .foregroundStyle(notificationStatusColor)
        } label: {
          Label("Reply Notifications", systemImage: "bell.badge")
        }
        notificationAction
        if case .failed(let message) = model.pushRegistrationState,
          isNotificationPermissionGranted
        {
          Label(message, systemImage: "exclamationmark.triangle")
            .froggyFont(.footnote)
            .foregroundStyle(.orange)
        }
      } header: {
        Text("Notifications")
      } footer: {
        Text("Apple permission and FroggyBot delivery registration must both be active.")
      }

      Section("Active Shared Links") {
        if loadingLinks {
          HStack {
            Spacer()
            ProgressView()
            Spacer()
          }
        } else if let linksError {
          ContentUnavailableView {
            Label("Couldn’t Load Links", systemImage: "wifi.exclamationmark")
          } description: {
            Text(linksError)
          } actions: {
            Button("Try Again") { Task { await loadLinks() } }
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
                    .froggyFont(.caption)
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
              Button("Revoke", role: .destructive) { revokeCandidate = link }
                .disabled(busyLinkToken != nil)
                .tint(FrogTheme.danger)
                .foregroundStyle(FrogTheme.danger)
            }
          }
        }
      }

      Section("Data & Privacy") {
        Button { exportMemory() } label: {
          if exportingMemory {
            Label { Text("Preparing Memory Export…") } icon: { ProgressView() }
          } else {
            Label("Export Memory", systemImage: "square.and.arrow.down")
          }
        }
        .disabled(exportingMemory)
        Link("Privacy Policy", destination: URL(string: "https://froggybot.com/privacy")!)
        Link("Terms of Use", destination: URL(string: "https://froggybot.com/terms")!)
      }

      Section {
        Button { signOut() } label: {
          Label("Log Out", systemImage: "rectangle.portrait.and.arrow.right")
        }
        .disabled(deletingAccount)
        .foregroundStyle(.primary)
      }

      Section {
        Button(role: .destructive) { confirmDelete = true } label: {
          if deletingAccount {
            Label { Text("Deleting Account…") } icon: { ProgressView() }
          } else {
            Label("Delete Account", systemImage: "trash")
          }
        }
        .disabled(deletingAccount)
        .tint(FrogTheme.danger)
        .foregroundStyle(FrogTheme.danger)
      } footer: {
        Text("Permanently deletes your bots, chats, memory, files, connected accounts, owned groups, schedules, skills, invitations, and shared links.")
      }

      Section("About") {
        LabeledContent("App", value: "FroggyBot for Apple")
        LabeledContent("Platforms", value: "iPhone + Mac")
        LabeledContent("Version", value: versionLabel)
          .accessibilityIdentifier("settings.version")
        Link("Support", destination: URL(string: "mailto:tmoreton89@gmail.com?subject=FroggyBot%20Support")!)
      }
    }
    .formStyle(.grouped)
    #if os(macOS)
      .froggyNavigationTitle("Settings", isPresented: !showsDismissButton)
      .safeAreaInset(edge: .top, spacing: 0) {
        if showsDismissButton {
          settingsHeader
        }
      }
    #else
      .froggyNavigationTitle("Settings")
    #endif
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      #if !os(macOS)
        if showsDismissButton {
          CloseButton()
        }
      #endif
    }
    .task { await load() }
    .refreshable { await loadLinks() }
    .fileExporter(
      isPresented: $showingMemoryExporter,
      document: memoryExportDocument,
      contentType: .json,
      defaultFilename: "froggybot-memory"
    ) { result in
      if case .failure(let error) = result {
        let cocoaError = error as NSError
        if cocoaError.domain != NSCocoaErrorDomain
          || cocoaError.code != CocoaError.Code.userCancelled.rawValue
        {
          model.present(error)
        }
      }
      memoryExportDocument = nil
    }
    .confirmationDialog(
      "Revoke this shared link?",
      isPresented: Binding(
        get: { revokeCandidate != nil }, set: { if !$0 { revokeCandidate = nil } }),
      titleVisibility: .visible
    ) {
      if let revokeCandidate {
        Button("Revoke Link", role: .destructive) { revoke(revokeCandidate) }
      }
      Button("Cancel", role: .cancel) { revokeCandidate = nil }
    } message: {
      Text("Anyone using this link will immediately lose access.")
    }
    .confirmationDialog(
      "Permanently delete your FroggyBot account?", isPresented: $confirmDelete,
      titleVisibility: .visible
    ) {
      Button("Delete Account", role: .destructive) { deleteAccount() }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("This cannot be undone. Connected-account access will be revoked, shared links will stop working, and owned groups will be deleted for every member.")
    }
  }

  #if os(macOS)
    private var settingsHeader: some View {
      HStack(spacing: 10) {
        Button("Back", systemImage: "chevron.backward") { model.sheet = nil }
          .labelStyle(.iconOnly)
          .buttonStyle(.plain)
          .foregroundStyle(FrogTheme.accent)
          .frame(width: 36, height: 36)
          .contentShape(Rectangle())
          .accessibilityIdentifier("sheet.close")
          .help("Back to chat")
        Text("Settings")
          .froggyFont(.headline, weight: .semibold)
          .accessibilityAddTraits(.isHeader)
        Spacer(minLength: 8)
      }
      .padding(.horizontal, 24)
      .padding(.vertical, 12)
      .background(.bar)
      .overlay(alignment: .bottom) { Divider() }
    }
  #endif

  @ViewBuilder private var notificationAction: some View {
    switch notificationAuthorization {
    case .notDetermined:
      Button("Enable Notifications") { enableNotifications() }
    case .denied:
      Button("Open System Settings", systemImage: "gear") {
        NativeNotifications.openSystemSettings()
      }
    case .authorized, .provisional:
      if model.pushRegistrationState != .registered {
        Button("Retry Delivery Registration", systemImage: "arrow.clockwise") {
          Task { await NativeNotifications.registerIfAuthorized() }
        }
      }
    #if os(iOS)
      case .ephemeral:
        if model.pushRegistrationState != .registered {
          Button("Retry Delivery Registration", systemImage: "arrow.clockwise") {
            Task { await NativeNotifications.registerIfAuthorized() }
          }
        }
    #endif
    @unknown default:
      EmptyView()
    }
  }

  private var isNotificationPermissionGranted: Bool {
    #if os(iOS)
      notificationAuthorization == .authorized || notificationAuthorization == .provisional
        || notificationAuthorization == .ephemeral
    #else
      notificationAuthorization == .authorized || notificationAuthorization == .provisional
    #endif
  }

  private var notificationStatusLabel: String {
    guard isNotificationPermissionGranted else { return "Off" }
    switch model.pushRegistrationState {
    case .registered: return "On"
    case .registering: return "Registering"
    case .failed: return "Needs Attention"
    case .idle: return "Waiting"
    }
  }

  private var notificationStatusColor: Color {
    switch model.pushRegistrationState {
    case .registered where isNotificationPermissionGranted: FrogTheme.accent
    case .failed where isNotificationPermissionGranted: .orange
    default: .secondary
    }
  }

  private var versionLabel: String {
    let info = Bundle.main.infoDictionary ?? [:]
    let version = info["CFBundleShortVersionString"] as? String ?? "—"
    let build = info["CFBundleVersion"] as? String ?? "—"
    return "\(version) (\(build))"
  }

  private func load() async {
    async let notificationLoad: Void = refreshNotificationStatus()
    await loadLinks()
    _ = await notificationLoad
  }

  private func loadLinks() async {
    loadingLinks = true
    defer { loadingLinks = false }
    do {
      links = try await model.requireAPI().shares()
      linksError = nil
    } catch {
      linksError = error.localizedDescription
    }
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
    notificationAuthorization = settings.authorizationStatus
  }

  private func revoke(_ link: SharedLink) {
    revokeCandidate = nil
    busyLinkToken = link.token
    Task {
      defer { busyLinkToken = nil }
      do {
        try await model.requireAPI().revokeShare(link.token)
        links.removeAll { $0.token == link.token }
      } catch {
        model.present(error)
      }
    }
  }

  private func signOut() {
    Task {
      await model.unregisterPush()
      await auth.signOut()
    }
  }

  private func exportMemory() {
    exportingMemory = true
    Task {
      defer { exportingMemory = false }
      do {
        memoryExportDocument = MemoryExportDocument(
          data: try await model.requireAPI().downloadMemoryExport())
        showingMemoryExporter = true
      } catch {
        model.present(error)
      }
    }
  }

  private func deleteAccount() {
    deletingAccount = true
    Task {
      do {
        try await model.requireAPI().deleteAccount()
        await auth.signOut()
      } catch {
        deletingAccount = false
        model.present(error)
      }
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
