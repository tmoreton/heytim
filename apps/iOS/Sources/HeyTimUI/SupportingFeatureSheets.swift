import SwiftUI
import AuthenticationServices
import Observation
import QuickLook
import StoreKit
import UniformTypeIdentifiers
import UserNotifications

extension Notification.Name {
  static let heyTimBillingDidReturn = Notification.Name("HeyTimBillingDidReturn")
}

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

  func start(url: URL, chooseAnotherAccount: Bool = false) {
    outcome = nil
    isRunning = true
    let session = ASWebAuthenticationSession(
      url: url, callbackURLScheme: "heytim"
    ) { @Sendable [weak self] callbackURL, error in
      self?.finish(callbackURL: callbackURL, error: error)
    }
    session.presentationContextProvider = self
    // A fresh browser session avoids silently reconnecting the account that
    // is already signed in when the user asks to add another account.
    session.prefersEphemeralWebBrowserSession = chooseAnotherAccount
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
  var initialDraft: SkillDraft?
  @State private var draft = SkillDraft()
  @State private var loading = false
  @State private var saving = false
  @State private var appliedInitialDraft = false
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
              .accessibilityLabel("Name")
            TextField("Description", text: $draft.description, axis: .vertical)
              .accessibilityLabel("Description")
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
        CloseButton { model.sheet = nil }
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
    .task {
      if id == nil, !appliedInitialDraft, let initialDraft {
        draft = initialDraft
        appliedInitialDraft = true
      }
      await load()
    }
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
        if showsDismissButton { model.sheet = nil } else { dismiss() }
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
  @State private var refreshingPlaidID: String?
  @State private var successMessage: String?
  @State private var showingMCPServerSetup = false
  @State private var mcpServerName = ""
  @State private var mcpServerURL = ""
  @State private var mcpServerToken = ""
  @State private var updatingMCPServer = false
  @State private var editingMCPServerID: String?
  @State private var savingMCPServer = false
  @State private var webAuthentication = WebAuthenticationController()

  private var providers: [ConnectionProvider] { model.bootstrap?.connectionProviders ?? [] }

  var body: some View {
    List {
      if loadError == nil {
        Section("Connected accounts") {
          ForEach(providers.filter { $0.id != "mcp_server" }) { provider in
            providerAccessRow(provider)
          }
          if providers.filter({ $0.id != "mcp_server" }).isEmpty && !loading {
            Text("No account providers are available.").foregroundStyle(.secondary)
          }
        }
        Section {
          ForEach(providers.filter { $0.id == "mcp_server" }) { provider in
            providerAccessRow(provider)
          }
        } header: {
          Text("MCP servers")
        } footer: {
          Text("Add Home Assistant at its /api/mcp/assist URL or any other trusted HTTPS MCP endpoint. Each server and account is enabled separately in a bot’s Tools list.")
        }
      }
    }
    .froggyListSurface()
    #if os(macOS)
      .froggyNavigationTitle("Connections")
    #else
      .navigationTitle("")
    #endif
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      ToolbarItem(placement: .primaryAction) {
        Menu {
          ForEach(providers) { provider in
            Button(provider.name) {
              connect(
                provider.id,
                chooseAnotherAccount: provider.id != "mcp_server"
                  && !connections(for: provider.id).isEmpty)
            }
            .accessibilityIdentifier("connection.add.\(provider.id)")
          }
        } label: {
          Label("Add account or server", systemImage: "plus")
        }
        .disabled(connectingProviderID != nil || webAuthentication.isRunning)
        .accessibilityIdentifier("connections.add")
      }
    }
    .overlay {
      if loading {
        ProgressView()
      } else if let loadError {
        ContentUnavailableView {
          Label("Couldn’t Load Accounts", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
    .refreshable { await load() }
    .task { await load() }
    .sheet(isPresented: $showingMCPServerSetup) {
      mcpServerSetupSheet
    }
    .onChange(of: webAuthentication.outcome) { _, outcome in
      guard let outcome else { return }
      switch outcome {
      case .callback(let url):
        Task {
          if let callback = await model.handleConnectionCallback(url),
            callback.status == .connected
          {
            successMessage = "\(providerName(callback.providerID)) sign-in completed. Check the account name below before assigning it to a bot."
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
      Text("Bots using this account will lose access. Hey Tim will revoke supported OAuth access and schedule its stored credential for deletion.")
    }
  }

  private func load() async {
    loading = true
    defer { loading = false }
    _ = await model.refreshBootstrap()
    do {
      connections = try await model.requireAPI().connections()
      loadError = nil
    } catch {
      loadError = error.localizedDescription
    }
  }

  private func connect(_ id: String, chooseAnotherAccount: Bool = false) {
    if id == "mcp_server" {
      updatingMCPServer = false
      mcpServerName = ""
      mcpServerURL = ""
      mcpServerToken = ""
      showingMCPServerSetup = true
      return
    }
    connectingProviderID = id
    Task {
      do {
        var callback = URLComponents()
        callback.scheme = "heytim"
        callback.host = "app"
        callback.queryItems = [URLQueryItem(name: "connection", value: id)]
        guard let returnURL = callback.url else { throw APIError.invalidResponse }
        let url = try await model.requireAPI().beginConnection(
          providerId: id, returnURL: returnURL)
        webAuthentication.start(url: url, chooseAnotherAccount: chooseAnotherAccount)
      } catch {
        connectingProviderID = nil
        model.present(error)
      }
    }
  }

  private func updateMCPServer(_ connection: Capability) {
    updatingMCPServer = true
    editingMCPServerID = connection.id
    mcpServerName = connection.name
    mcpServerURL = connection.endpoint ?? ""
    mcpServerToken = ""
    showingMCPServerSetup = true
  }

  private func closeMCPServerSetup() {
    updatingMCPServer = false
    editingMCPServerID = nil
    mcpServerName = ""
    mcpServerURL = ""
    mcpServerToken = ""
    showingMCPServerSetup = false
  }

  private var mcpServerSetupSheet: some View {
    NavigationStack {
      Form {
        Section {
          TextField("Server name", text: $mcpServerName)
            .accessibilityIdentifier("connection.mcp.name")
          TextField("MCP HTTPS URL", text: $mcpServerURL)
            .autocorrectionDisabled()
            .accessibilityIdentifier("connection.mcp.url")
            .disabled(updatingMCPServer)
          SecureField("Access token", text: $mcpServerToken)
            .accessibilityIdentifier("connection.mcp.token")
        } header: {
          Text(updatingMCPServer ? "Update MCP server" : "Add MCP server")
        } footer: {
          Text(updatingMCPServer
               ? "Leave the token blank to rename this server without changing its credential. Enter a new token to rotate it. To change the URL, add a new server and reassign bots."
               : "Use a public HTTPS MCP endpoint you trust. For Home Assistant, enter the full /api/mcp/assist URL and a long-lived access token. HeyTim stores tokens privately. Add multiple servers and enable each only for the bots that need it.")
        }
      }
      .formStyle(.grouped)
      .navigationTitle("MCP server")
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { closeMCPServerSetup() }
        }
        ToolbarItem(placement: .confirmationAction) {
            Button(updatingMCPServer ? "Save server" : "Add server") { saveMCPServer() }
            .disabled(savingMCPServer || mcpServerName.isEmpty || mcpServerURL.isEmpty || (!updatingMCPServer && mcpServerToken.isEmpty))
        }
      }
      .overlay { if savingMCPServer { ProgressView() } }
    }
    .frame(minWidth: 460, minHeight: 340)
  }

  private func saveMCPServer() {
    guard !savingMCPServer else { return }
    savingMCPServer = true
    Task {
      defer { savingMCPServer = false }
      do {
        let name = mcpServerName.trimmingCharacters(in: .whitespacesAndNewlines)
        if let editingMCPServerID, mcpServerToken.isEmpty {
          _ = try await model.requireAPI().renameMCPServer(id: editingMCPServerID, name: name)
        } else {
          _ = try await model.requireAPI().connectMCPServer(
            name: name,
            url: mcpServerURL.trimmingCharacters(in: .whitespacesAndNewlines),
            accessToken: mcpServerToken.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let updated = updatingMCPServer
        closeMCPServerSetup()
        await load()
        successMessage = updated
          ? "MCP server saved. Its connection has not been tested."
          : "MCP server saved, but not tested. Enable it in a bot’s Tools list to use it."
      } catch {
        model.present(error)
      }
    }
  }

  private func remove(_ connection: Capability) {
    disconnectCandidate = nil
    Task {
      do {
        try await model.requireAPI().deleteConnection(connection.id)
        await load()
      } catch { model.present(error) }
    }
  }

  private func refreshPlaid(_ connection: Capability) {
    guard refreshingPlaidID == nil else { return }
    refreshingPlaidID = connection.id
    Task {
      defer { refreshingPlaidID = nil }
      do {
        _ = try await model.requireAPI().requestPlaidSync(connection.id)
        await load()
      } catch { model.present(error) }
    }
  }

  private func connections(for providerID: String) -> [Capability] {
    connections.filter { $0.provider == providerID }
  }

  private func providerName(_ id: String) -> String {
    providers.first(where: { $0.id == id })?.name ?? "Account"
  }

  @ViewBuilder
  private func providerAccessRow(_ provider: ConnectionProvider) -> some View {
    let accounts = connections(for: provider.id)
    if !accounts.isEmpty {
      VStack(alignment: .leading, spacing: 8) {
        ForEach(accounts) { connection in
          FeatureLink {
            ConnectionDetailView(
              connection: connection, provider: provider,
              reconnect: {
                if provider.id == "mcp_server" { updateMCPServer(connection) }
                else { connect(provider.id, chooseAnotherAccount: true) }
              },
              disconnect: { disconnectCandidate = connection },
              refreshPlaid: provider.id == "plaid" ? { refreshPlaid(connection) } : nil)
          } label: {
            connectionRow(connection, provider: provider)
          }
        }
      }
    } else {
      HStack(spacing: 12) {
        ProviderLogoView(provider: provider)
        VStack(alignment: .leading, spacing: 3) {
          Text(provider.name).froggyFont(.headline)
          Text(provider.description)
            .froggyFont(.caption).foregroundStyle(.secondary).lineLimit(2)
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

  private func connectionRow(
    _ connection: Capability, provider: ConnectionProvider
  ) -> some View {
    HStack(spacing: 12) {
      ProviderLogoView(provider: provider)
      VStack(alignment: .leading, spacing: 3) {
        Text(provider.id == "mcp_server" ? connection.name : provider.name)
          .froggyFont(.headline)
        Text(provider.id == "mcp_server"
             ? (connection.endpoint ?? connection.description)
             : (connection.connectedAccount ?? connection.description))
          .froggyFont(.caption).foregroundStyle(.secondary).lineLimit(2)
      }
      Spacer()
      Text(connectionStatusLabel(connection))
        .froggyFont(.caption)
        .foregroundStyle(connection.connectionStatus == "connected" ? FrogTheme.accent : .secondary)
    }
  }

  private func connectionStatusLabel(_ connection: Capability) -> String {
    if connection.provider == "mcp_server" { return "Saved · Not tested" }
    if connection.provider == "plaid", connection.plaidSync?.status == "needs_reconnect" {
      return "Reconnect required"
    }
    if connection.connectionStatus == "connected" { return "Connected" }
    if connection.connectionStatus == "reauthorization_required" { return "Reconnect required" }
    return "Needs attention"
  }
}

private struct ConnectionDetailView: View {
  let connection: Capability
  let provider: ConnectionProvider?
  let reconnect: (() -> Void)?
  let disconnect: () -> Void
  let refreshPlaid: (() -> Void)?

  var body: some View {
    Form {
      Section {
        LabeledContent("Status", value: statusLabel)
        if let account = connection.connectedAccount, connection.provider != "mcp_server" {
          LabeledContent("Account", value: account)
        }
        if let endpoint = connection.endpoint, connection.provider == "mcp_server" {
          LabeledContent("Server URL", value: endpoint)
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
      if connection.provider == "github", let repositories = connection.repositories {
        Section("Connected repositories") {
          ForEach(repositories) { repository in
            Text(repository.name)
          }
        }
      }
      if connection.provider == "plaid" {
        Section("Transactions") {
          LabeledContent("Sync", value: plaidSyncLabel)
          if let count = connection.plaidSync?.transactionCount {
            LabeledContent("Saved transactions", value: count.formatted())
          }
          if let date = connection.plaidSync?.lastSyncedAt?.froggyDate {
            LabeledContent("Last synced", value: date.formatted(date: .abbreviated, time: .shortened))
          }
          if connection.plaidSync?.historicalComplete == false {
            Text("Historical transactions are still arriving from Plaid. New changes sync automatically.")
              .froggyFont(.caption).foregroundStyle(.secondary)
          }
          if let refreshPlaid {
            Button("Sync transactions now", systemImage: "arrow.triangle.2.circlepath", action: refreshPlaid)
          }
        }
      }
      Section {
        if let reconnect {
          Button(
            connection.provider == "mcp_server" ? "Update Server" : "Sign in again…",
            systemImage: "arrow.clockwise", action: reconnect)
          if connection.provider != "mcp_server" {
            Text("Choose the account shown above. Signing in with another account adds a separate connection instead of replacing this one.")
              .froggyFont(.caption).foregroundStyle(.secondary)
          }
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
    if connection.provider == "mcp_server" { return "Saved, not tested" }
    if connection.provider == "plaid", connection.plaidSync?.status == "needs_reconnect" {
      return "Reconnect required"
    }
    if connection.connectionStatus == "connected" { return "Connected" }
    if connection.connectionStatus == "reauthorization_required" { return "Reconnect required" }
    return "Needs attention"
  }

  private var plaidSyncLabel: String {
    switch connection.plaidSync?.status {
    case "ready": return connection.plaidSync?.historicalComplete == false
      ? "History pending" : "Up to date"
    case "queued": return "Queued"
    case "syncing": return "Syncing"
    case "waiting_for_plaid": return "Waiting for Plaid"
    case "needs_reconnect": return "Reconnect required"
    case "error": return "Sync needs attention"
    default: return "Not synced yet"
    }
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
      if previous != current { HeyTimAPI.removeDownloadedPreview(at: previous) }
    }
    .onDisappear {
      previewTask?.cancel()
      HeyTimAPI.removeDownloadedPreview(at: previewURL)
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
          HeyTimAPI.removeDownloadedPreview(at: downloaded)
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

struct GroupRoutinesView: View {
  @Bindable var model: AppModel
  let groupId: String
  @State private var routines: [GroupRoutine] = []
  @State private var runs: [GroupRoutineRun] = []
  @State private var editing: GroupRoutine?
  @State private var deleteCandidate: GroupRoutine?
  @State private var creating = false
  @State private var loading = false

  private var isOwner: Bool {
    model.bootstrap?.groups.first(where: { $0.id == groupId })?.isOwner == true
  }

  var body: some View {
    List {
      Section("Event routines") {
        ForEach(routines) { routine in
          HStack {
            VStack(alignment: .leading, spacing: 4) {
              Text(routine.name)
              Text(routine.trigger.eventType == "github.issue.opened"
                   ? "Repository issue · \(routine.trigger.repositoryName ?? "Repository")"
                   : "Saved room decision")
                .froggyFont(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            Text(routine.enabled ? "On" : "Off")
              .foregroundStyle(routine.enabled ? FrogTheme.green : .secondary)
            if isOwner {
              Button("Edit", systemImage: "pencil") { editing = routine }
                .labelStyle(.iconOnly)
            }
          }
          .contextMenu {
            if isOwner {
              Button("Edit") { editing = routine }
              Button("Delete", role: .destructive) {
                deleteCandidate = routine
              }
            }
          }
        }
        if routines.isEmpty && !loading {
          Text("No event routines yet.")
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 140)
        }
      }
      Section("Recent runs") {
        ForEach(runs) { run in
          VStack(alignment: .leading, spacing: 3) {
            Text(routines.first(where: { $0.id == run.routineId })?.name ?? "Event routine")
            Text("\(run.eventType) · \(run.status.capitalized)")
              .froggyFont(.caption)
              .foregroundStyle(.secondary)
          }
        }
        if runs.isEmpty && !loading {
          Text("No event runs yet.")
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 140)
        }
      }
    }
    .froggyListSurface()
    .froggyNavigationTitle("Event routines")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if isOwner {
        ToolbarItem(placement: .primaryAction) {
          Button("New routine", systemImage: "plus") { creating = true }
        }
      }
    }
    .overlay { if loading && routines.isEmpty { ProgressView("Loading routines…") } }
    .refreshable { await load() }
    .task { await load() }
    .sheet(isPresented: $creating) {
      GroupRoutineEditor(model: model, groupId: groupId, existing: nil) {
        Task { await load() }
      }
    }
    .sheet(item: $editing) { routine in
      GroupRoutineEditor(model: model, groupId: groupId, existing: routine) {
        Task { await load() }
      }
    }
    .confirmationDialog(
      "Delete this event routine?", isPresented: Binding(
        get: { deleteCandidate != nil },
        set: { if !$0 { deleteCandidate = nil } })
    ) {
      if let deleteCandidate {
        Button("Delete \(deleteCandidate.name)", role: .destructive) {
          Task { await delete(deleteCandidate) }
          self.deleteCandidate = nil
        }
      }
    }
  }

  private func load() async {
    guard let api = model.api else { return }
    loading = true
    defer { loading = false }
    do {
      async let loadedRoutines = api.groupRoutines(groupId)
      async let loadedRuns = api.groupRoutineRuns(groupId)
      routines = try await loadedRoutines
      runs = try await loadedRuns
    } catch { model.present(error) }
  }

  private func delete(_ routine: GroupRoutine) async {
    guard let api = model.api else { return }
    do {
      try await api.deleteGroupRoutine(routine.id, groupId: groupId)
      await load()
    } catch { model.present(error) }
  }
}

private struct GroupRoutineEditor: View {
  @Bindable var model: AppModel
  let groupId: String
  let existing: GroupRoutine?
  let onSaved: () -> Void
  @Environment(\.dismiss) private var dismiss
  @State private var name: String
  @State private var prompt: String
  @State private var enabled: Bool
  @State private var eventType: String
  @State private var connectionId: String
  @State private var repositoryId: Int
  @State private var connections: [Capability] = []
  @State private var saving = false
  @State private var sampleText = ""
  @State private var previewText: String?
  @State private var previewing = false

  init(model: AppModel, groupId: String, existing: GroupRoutine?, onSaved: @escaping () -> Void) {
    self.model = model
    self.groupId = groupId
    self.existing = existing
    self.onSaved = onSaved
    _name = State(initialValue: existing?.name ?? "")
    _prompt = State(initialValue: existing?.prompt ?? "")
    _enabled = State(initialValue: existing?.enabled ?? false)
    _eventType = State(initialValue: existing?.trigger.eventType ?? "group.decision.saved")
    _connectionId = State(initialValue: existing?.trigger.connectionId ?? "")
    _repositoryId = State(initialValue: existing?.trigger.repositoryId ?? 0)
  }

  private var githubConnections: [Capability] {
    connections.filter { $0.provider == "github" && $0.connectionStatus == "connected" }
  }
  private var selectedRepositories: [ConnectedRepository] {
    githubConnections.first(where: { $0.id == connectionId })?.repositories ?? []
  }
  private var canSave: Bool {
    !saving && !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && (eventType != "github.issue.opened" || (!connectionId.isEmpty && repositoryId > 0))
  }

  var body: some View {
    NavigationStack {
      Form {
        TextField("Name", text: $name)
        TextField("What should the bots do?", text: $prompt, axis: .vertical)
          .lineLimit(4...12)
        Picker("When", selection: $eventType) {
          Text("A room decision is saved").tag("group.decision.saved")
          Text("A repository issue opens").tag("github.issue.opened")
        }
        if eventType == "github.issue.opened" {
          Picker("Connected account", selection: $connectionId) {
            Text("Choose account").tag("")
            ForEach(githubConnections) { connection in
              Text(connection.connectedAccount ?? connection.name).tag(connection.id)
            }
          }
          Picker("Repository", selection: $repositoryId) {
            Text("Choose repository").tag(0)
            ForEach(selectedRepositories) { repository in
              Text(repository.name).tag(repository.id)
            }
          }
        }
        Toggle("Enabled", isOn: $enabled)
        Section("Preview") {
          TextField(
            eventType == "github.issue.opened" ? "Sample issue title" : "Sample decision",
            text: $sampleText, axis: .vertical)
          Button("Preview prompt") { Task { await preview() } }
            .disabled(previewing || sampleText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          if let previewText {
            Text(previewText)
              .froggyFont(.callout)
              .textSelection(.enabled)
          }
        }
        Text("Event routines can use this bot’s enabled tools. If Ask before acting is enabled, interactive actions may pause for approval.")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      }
      .froggyNavigationTitle(existing == nil ? "New routine" : "Edit routine")
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { dismiss() }
        }
        ToolbarItem(placement: .confirmationAction) {
          Button("Save") { Task { await save() } }
            .disabled(!canSave)
        }
      }
      .task {
        guard let api = model.api else { return }
        do { connections = try await api.connections() }
        catch { model.present(error) }
      }
      .onChange(of: connectionId) { _, _ in repositoryId = 0 }
    }
  }

  private func save() async {
    guard let api = model.api, canSave else { return }
    saving = true
    defer { saving = false }
    do {
      let trigger = GroupRoutineTrigger(
        eventType: eventType,
        connectionId: eventType == "github.issue.opened" ? connectionId : nil,
        repositoryId: eventType == "github.issue.opened" ? repositoryId : nil)
      _ = try await api.saveGroupRoutine(
        GroupRoutineDraft(name: name, prompt: prompt, trigger: trigger, enabled: enabled),
        groupId: groupId, id: existing?.id)
      onSaved()
      dismiss()
    } catch { model.present(error) }
  }

  private func preview() async {
    guard let api = model.api else { return }
    previewing = true
    defer { previewing = false }
    do {
      let trigger = GroupRoutineTrigger(
        eventType: eventType,
        connectionId: eventType == "github.issue.opened" ? connectionId : nil,
        repositoryId: eventType == "github.issue.opened" ? repositoryId : nil)
      let request = GroupRoutinePreviewRequest(
        prompt: prompt, trigger: trigger,
        decisionText: eventType == "group.decision.saved" ? sampleText : nil,
        issue: eventType == "github.issue.opened"
          ? .init(number: 1, title: sampleText, body: "Sample issue body") : nil)
      previewText = try await api.previewGroupRoutine(request, groupId: groupId).prompt
    } catch { model.present(error) }
  }
}

struct WorkspaceFilePickerView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  let onSelect: (Attachment) -> Void
  @Environment(\.dismiss) private var dismiss
  @State private var files: [Attachment] = []
  @State private var loading = false

  var body: some View {
    NavigationStack {
      List(files) { file in
        Button {
          onSelect(file)
          dismiss()
        } label: {
          HStack {
            Label(file.name, systemImage: "doc")
            Spacer()
            Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
              .foregroundStyle(.secondary)
          }
        }
      }
      .overlay {
        if loading { ProgressView("Loading saved files…") }
        else if files.isEmpty {
          ContentUnavailableView("No saved files", systemImage: "folder")
        }
      }
      .froggyNavigationTitle("Saved files")
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { dismiss() }
        }
      }
      .task {
        guard let api = model.api else { return }
        loading = true
        defer { loading = false }
        do { files = try await api.workspaceFiles(for: selection).files }
        catch { model.present(error) }
      }
    }
  }
}

struct WorkspaceFilesView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  @State private var snapshot: WorkspaceSnapshot?
  @State private var loading = false
  @State private var busy = false
  @State private var importing = false
  @State private var previewURL: URL?
  @State private var deleteCandidate: Attachment?
  @State private var exportDocument: MemoryExportDocument?
  @State private var showingExporter = false

  var body: some View {
    List {
      if let snapshot {
        Section {
          ForEach(snapshot.files) { file in
            HStack {
              Button {
                Task { await open(file) }
              } label: {
                Label(file.name, systemImage: "doc")
              }
              .buttonStyle(.plain)
              Spacer()
              if let revision = file.revision, revision > 1 {
                Text("v\(revision)")
                  .froggyFont(.caption)
                  .foregroundStyle(.secondary)
              }
              Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                .foregroundStyle(.secondary)
              Button("Delete", systemImage: "trash", role: .destructive) {
                deleteCandidate = file
              }
              .labelStyle(.iconOnly)
              .disabled(busy)
            }
          }
        } header: {
          Text("Persistent files")
        } footer: {
          Text("\(snapshot.fileCount) of \(snapshot.limits.files) files · \(ByteCountFormatter.string(fromByteCount: Int64(snapshot.totalBytes), countStyle: .file)) of \(ByteCountFormatter.string(fromByteCount: Int64(snapshot.limits.bytes), countStyle: .file))")
        }
      }
      if snapshot?.files.isEmpty == false {
        Text("The exported download list contains links that expire after five minutes. Save the files you need before the links expire.")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      }
    }
    .froggyListSurface()
    .overlay {
      if snapshot?.files.isEmpty == true && !loading {
        ContentUnavailableView(
          "No saved files", systemImage: "folder",
          description: Text("Add a file to use it in a later code session."))
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .allowsHitTesting(false)
      }
    }
    .froggyNavigationTitle("Workspace files")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      ToolbarItem(placement: .primaryAction) {
        Button("Add file", systemImage: "plus") { importing = true }
          .disabled(busy || loading || snapshot?.fileCount == snapshot?.limits.files)
      }
      ToolbarItem(placement: .primaryAction) {
        Button("Export download list", systemImage: "square.and.arrow.up") {
          Task { await export() }
        }
        .disabled(busy || snapshot?.files.isEmpty != false)
      }
    }
    .overlay {
      if loading && snapshot == nil { ProgressView("Loading files…") }
    }
    .refreshable { await load() }
    .task { await load() }
    .quickLookPreview($previewURL)
    .onChange(of: previewURL) { previous, current in
      if previous != current { HeyTimAPI.removeDownloadedPreview(at: previous) }
    }
    .fileImporter(
      isPresented: $importing, allowedContentTypes: [.image, .pdf, .plainText, .data]
    ) { result in
      switch result {
      case .success(let url): Task { await add(url) }
      case .failure(let error): model.present(error)
      }
    }
    .fileExporter(
      isPresented: $showingExporter, document: exportDocument,
      contentType: .json, defaultFilename: "heytim-workspace-links"
    ) { result in
      if case .failure(let error) = result { model.present(error) }
      exportDocument = nil
    }
    .confirmationDialog(
      "Delete this workspace file?", isPresented: Binding(
        get: { deleteCandidate != nil },
        set: { if !$0 { deleteCandidate = nil } })
    ) {
      if let deleteCandidate {
        Button("Delete \(deleteCandidate.name)", role: .destructive) {
          Task { await delete(deleteCandidate) }
          self.deleteCandidate = nil
        }
      }
    }
  }

  private func load() async {
    guard let api = model.api else { return }
    loading = true
    defer { loading = false }
    do { snapshot = try await api.workspaceFiles(for: selection) }
    catch { model.present(error) }
  }

  private func add(_ url: URL) async {
    guard let api = model.api else { return }
    busy = true
    let access = url.startAccessingSecurityScopedResource()
    defer {
      if access { url.stopAccessingSecurityScopedResource() }
      busy = false
    }
    do {
      let upload = try await api.upload(try UploadAsset(url: url))
      _ = try await api.addWorkspaceFile(upload.id, to: selection)
      await load()
    } catch { model.present(error) }
  }

  private func open(_ file: Attachment) async {
    guard let api = model.api else { return }
    do {
      previewURL = try await api.downloadFile(
        fileId: file.id, name: file.name,
        groupId: selection.kind == .group ? selection.id : nil)
    } catch { model.present(error) }
  }

  private func delete(_ file: Attachment) async {
    guard let api = model.api else { return }
    busy = true
    defer { busy = false }
    do {
      try await api.deleteWorkspaceFile(file.id, from: selection)
      await load()
    } catch { model.present(error) }
  }

  private func export() async {
    guard let api = model.api else { return }
    busy = true
    defer { busy = false }
    do {
      let manifest = try await api.workspaceExport(for: selection)
      let encoder = JSONEncoder()
      encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
      exportDocument = MemoryExportDocument(data: try encoder.encode(manifest))
      showingExporter = true
    } catch { model.present(error) }
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

private struct SettingsNavigationLabel: View {
  let title: String
  let detail: String
  let systemImage: String

  var body: some View {
    Label {
      VStack(alignment: .leading, spacing: 3) {
        Text(title)
        Text(detail)
          .froggyFont(.caption)
          .foregroundStyle(.secondary)
      }
      .padding(.vertical, 2)
    } icon: {
      Image(systemName: systemImage)
    }
  }
}

struct AccountView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  var showsDismissButton = true
  #if os(iOS)
    @Environment(AppleHealthCoordinator.self) private var appleHealth
  #endif
  #if os(macOS)
    @Environment(DesktopControlCoordinator.self) private var desktopControl
  #endif
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
  @State private var billing: BillingSummary?
  @State private var loadingBilling = true
  @State private var billingBusy = false
  @State private var billingError: String?
  @State private var storefrontCountryCode: String?
  @Environment(\.openURL) private var openURL
  @Environment(\.scenePhase) private var scenePhase

  var body: some View {
    Form {
      Section("Your Team") {
        FeatureLink {
          BotLibrary(model: model, showsDismissButton: false)
        } label: {
          SettingsNavigationLabel(
            title: "Add a Bot",
            detail: "Choose a template or create a custom teammate.",
            systemImage: "plus.circle.fill")
        }
      }

      Section("Workspace") {
        FeatureLink {
          MemoriesView(model: model, groupId: nil, showsDismissButton: false)
        } label: {
          SettingsNavigationLabel(
            title: "Memory",
            detail: "Review facts and preferences shared across your bots.",
            systemImage: "brain.head.profile")
        }
        FeatureLink {
          SkillsView(model: model, showsDismissButton: false)
        } label: {
          SettingsNavigationLabel(
            title: "Tools & Skills",
            detail: "Browse playbooks and available capabilities.",
            systemImage: "wrench.and.screwdriver")
        }
        FeatureLink {
          ConnectionsView(model: model, showsDismissButton: false)
        } label: {
          SettingsNavigationLabel(
            title: "Accounts & MCP Servers",
            detail: "Connect, reconnect, or remove external services.",
            systemImage: "link")
        }
      }

      billingSection

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

      #if os(macOS)
        DesktopControlSettingsSection(coordinator: desktopControl)
      #elseif os(iOS)
        AppleHealthSettingsSection(coordinator: appleHealth)
      #endif

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
        Text("Apple permission and Hey Tim delivery registration must both be active.")
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
        Link("Privacy Policy", destination: URL(string: "https://heytim.ai/privacy")!)
        Link("Terms of Use", destination: URL(string: "https://heytim.ai/terms")!)
      }

      accountSection

      Section("About") {
        LabeledContent("Version", value: versionLabel)
          .accessibilityIdentifier("settings.version")
        #if os(macOS)
          Button("Check for Updates…", systemImage: "arrow.triangle.2.circlepath") {
            DesktopUpdateController.shared.checkForUpdates()
          }
          .disabled(!DesktopUpdateController.shared.isConfigured)
          .accessibilityIdentifier("settings.check-for-updates")
        #endif
        Link("Support", destination: URL(string: "mailto:support@heytim.ai?subject=Hey%20Tim%20Support")!)
      }
    }
    .formStyle(.grouped)
    .froggyNavigationTitle("Settings")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
    }
    .task { await load() }
    .refreshable { await load() }
    .onReceive(NotificationCenter.default.publisher(for: .heyTimBillingDidReturn)) { _ in
      Task { await loadBilling() }
    }
    .onChange(of: scenePhase) { _, phase in
      if phase == .active { Task { await loadBilling() } }
    }
    .fileExporter(
      isPresented: $showingMemoryExporter,
      document: memoryExportDocument,
      contentType: .json,
      defaultFilename: "heytim-memory"
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
      "Permanently delete your Hey Tim account?", isPresented: $confirmDelete,
      titleVisibility: .visible
    ) {
      Button("Delete Account", role: .destructive) { deleteAccount() }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("This cannot be undone. Connected-account access will be revoked, shared links will stop working, and owned groups will be deleted for every member.")
    }
  }

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

  private var accountSection: some View {
    Section {
      Button { signOut() } label: {
        Label("Log Out", systemImage: "rectangle.portrait.and.arrow.right")
      }
      .disabled(deletingAccount)
      .foregroundStyle(.primary)

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
    } header: {
      Text("Account")
    } footer: {
      Text(
        "Permanently deletes your bots, chats, memory, files, connected accounts, owned groups, schedules, skills, invitations, and shared links."
      )
    }
  }

  @ViewBuilder private var billingSection: some View {
    Section {
      if loadingBilling, billing == nil {
        HStack {
          Spacer()
          ProgressView()
          Spacer()
        }
      } else if let billing {
        LabeledContent("Plan") {
          Text(billing.plan == "plus" ? "Plus" : billing.plan == "preview" ? "Preview" : "Free")
            .fontWeight(.semibold)
        }
        VStack(alignment: .leading, spacing: 8) {
          ProgressView(
            value: Double(min(billing.creditsUsed, billing.creditLimit)),
            total: Double(max(1, billing.creditLimit)))
            .tint(FrogTheme.accent)
          HStack {
            Text("\(billing.creditsUsed) of \(billing.creditLimit) work credits used")
            Spacer()
            Text("\(billing.creditsRemaining) left")
          }
          .froggyFont(.caption)
          .foregroundStyle(.secondary)
          if let resetDate = billing.resetsAt.froggyDate {
            Text("Resets \(resetDate.formatted(.dateTime.month(.abbreviated).day().year()))")
              .froggyFont(.caption)
              .foregroundStyle(.secondary)
          }
        }

        if billing.plan == "plus", billing.managementAvailable {
          Button { startBillingPortal() } label: {
            billingButtonLabel("Manage Subscription", systemImage: "creditcard")
          }
          .disabled(billingBusy)
        } else if billing.checkoutAvailable,
          storefrontCountryCode == billing.supportedStorefrontCountryCode
        {
          Button { startCheckout(countryCode: billing.supportedStorefrontCountryCode) } label: {
            billingButtonLabel("Upgrade to Plus — \(priceLabel(billing.price))", systemImage: "sparkles")
          }
          .disabled(billingBusy)
        } else if billing.billingAvailable, storefrontCountryCode != nil,
          storefrontCountryCode != billing.supportedStorefrontCountryCode
        {
          Text("Plus web checkout is currently available in the U.S. only.")
            .froggyFont(.footnote)
            .foregroundStyle(.secondary)
        }

        if billing.cancelAtPeriodEnd, let resetDate = billing.resetsAt.froggyDate {
          Text("Plus remains active until \(resetDate.formatted(.dateTime.month(.abbreviated).day().year())).")
            .froggyFont(.footnote)
            .foregroundStyle(.secondary)
        }
        if billing.billingAvailable, billing.mode == "test" {
          Label("Test billing is enabled. No live charge will be made.", systemImage: "testtube.2")
            .froggyFont(.footnote)
            .foregroundStyle(.secondary)
        }
      }

      if let billingError {
        Label(billingError, systemImage: "exclamationmark.triangle")
          .froggyFont(.footnote)
          .foregroundStyle(.orange)
        Button("Try Again") { Task { await loadBilling() } }
      }
    } header: {
      Text("Usage & Plan")
    } footer: {
      Text("A work credit covers one bot reply or one planned group reply. Token and provider usage is still measured privately for cost and reliability.")
    }
  }

  @ViewBuilder private func billingButtonLabel(
    _ title: String, systemImage: String
  ) -> some View {
    if billingBusy {
      Label { Text("Opening…") } icon: { ProgressView() }
    } else {
      Label(title, systemImage: systemImage)
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
    async let linksLoad: Void = loadLinks()
    async let billingLoad: Void = loadBilling()
    _ = await (linksLoad, billingLoad)
    _ = await notificationLoad
  }

  private func loadBilling() async {
    loadingBilling = true
    defer { loadingBilling = false }
    if storefrontCountryCode == nil {
      let storefront = await Storefront.current
      storefrontCountryCode = storefront?.countryCode ?? Locale.current.region?.identifier
    }
    do {
      billing = try await model.requireAPI().billingSummary()
      billingError = nil
    } catch {
      billingError = error.localizedDescription
    }
  }

  private func startCheckout(countryCode: String) {
    billingBusy = true
    Task {
      defer { billingBusy = false }
      do {
        openURL(try await model.requireAPI().createBillingCheckout(
          storefrontCountryCode: countryCode))
      } catch {
        model.present(error)
      }
    }
  }

  private func startBillingPortal() {
    billingBusy = true
    Task {
      defer { billingBusy = false }
      do {
        openURL(try await model.requireAPI().createBillingPortal())
      } catch {
        model.present(error)
      }
    }
  }

  private func priceLabel(_ price: BillingSummary.Price) -> String {
    let amount = Double(price.unitAmount) / 100
    let formatted = amount.formatted(
      .currency(code: price.currency.uppercased()).precision(.fractionLength(0...2)))
    return "\(formatted)/\(price.interval)"
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
