import Foundation
#if canImport(HeyTimCore)
import HeyTimCore
#endif
import SwiftUI

struct MCPServerSetupView: View {
  @Bindable var model: AppModel
  var editingID: String?
  var onSaved: () -> Void
  @State var name = ""
  @State var endpoint = ""
  @State private var token = ""
  @State private var authentication = "token"
  @State private var discovery: MCPDiscovery?
  @State private var selectedTools: Set<String> = []
  @State private var selectedBots: Set<String> = []
  @State private var busy = false
  @State private var errorMessage: String?
  @State private var savedConnection: Capability?
  @Environment(\.dismiss) private var dismiss

  private var canTest: Bool {
    !busy && !endpoint.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && (authentication == "none" || !token.isEmpty)
  }
  private var canRename: Bool { editingID != nil && token.isEmpty && discovery == nil }
  private var canSave: Bool {
    !busy && !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && (canRename || (discovery != nil && !selectedTools.isEmpty))
  }

  var body: some View {
    NavigationStack {
      Form {
        Section {
          TextField("Server name", text: $name)
            .accessibilityIdentifier("connection.mcp.name")
            .disabled(savedConnection != nil)
          TextField("MCP HTTPS URL", text: $endpoint)
            .autocorrectionDisabled()
            .accessibilityIdentifier("connection.mcp.url")
            .disabled(editingID != nil || savedConnection != nil)
          Picker("Authentication", selection: $authentication) {
            Text("Access token").tag("token")
            Text("No authentication").tag("none")
          }
          .accessibilityIdentifier("connection.mcp.auth")
          .disabled(savedConnection != nil)
          if authentication == "token" {
            SecureField("Access token", text: $token)
              .accessibilityIdentifier("connection.mcp.token")
              .disabled(savedConnection != nil)
          }
          Button(discovery == nil ? "Test connection" : "Test again") { testConnection() }
            .disabled(!canTest || savedConnection != nil)
            .accessibilityIdentifier("connection.mcp.test")
        } header: {
          Text(editingID == nil ? "Connect an integration" : "Update MCP server")
        } footer: {
          Text(editingID == nil
            ? "Use a trusted public HTTPS MCP endpoint. For Home Assistant, use /api/mcp/assist. Credentials stay private. Testing discovers tools without running them."
            : "Leave the token blank to rename. Enter a token and test to review tool access again. To change the URL, add another server.")
        }

        if let discovery {
          Section {
            LabeledContent("Server", value: discovery.serverName)
            if !discovery.serverVersion.isEmpty {
              LabeledContent("Version", value: discovery.serverVersion)
            }
            ForEach(discovery.tools) { tool in
              Toggle(isOn: Binding(
                get: { selectedTools.contains(tool.name) },
                set: { enabled in
                  if enabled { selectedTools.insert(tool.name) }
                  else { selectedTools.remove(tool.name) }
                })) {
                  VStack(alignment: .leading, spacing: 3) {
                    Text(tool.name).font(.body.monospaced())
                    if !tool.description.isEmpty {
                      Text(tool.description).font(.caption).foregroundStyle(.secondary)
                    }
                  }
                }
                .disabled(savedConnection != nil)
            }
            if discovery.tools.isEmpty {
              Text("This server exposes no tools.").foregroundStyle(.secondary)
            }
          } header: {
            Text("Choose tools · \(selectedTools.count) selected")
          } footer: {
            Text("Tool descriptions come from the server. Only selected tools will be available. Changed tool schemas need a new review. Actions ask for approval unless you explicitly allow this connection.")
          }
          Section {
            ForEach(model.bootstrap?.bots ?? []) { bot in
              Toggle(bot.name, isOn: Binding(
                get: { selectedBots.contains(bot.id) },
                set: { enabled in
                  if enabled { selectedBots.insert(bot.id) }
                  else { selectedBots.remove(bot.id) }
                }))
            }
          } header: {
            Text("Enable for bots")
          } footer: {
            Text("You can also enable this connection later in a bot’s Tools list.")
          }
        }
        if let errorMessage {
          Section {
            Text(errorMessage).foregroundStyle(.red).textSelection(.enabled)
          }
        }
      }
      .formStyle(.grouped)
      .navigationTitle("MCP server")
      .disabled(busy)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Cancel") { dismiss() }.disabled(busy)
        }
        ToolbarItem(placement: .confirmationAction) {
          Button(savedConnection == nil ? "Save connection" : "Retry bot assignment") { save() }
            .disabled(!canSave)
            .accessibilityIdentifier("connection.mcp.save")
        }
      }
      .overlay { if busy { ProgressView("Checking connection…") } }
      .onChange(of: endpoint) { invalidate() }
      .onChange(of: token) { invalidate() }
      .onChange(of: authentication) { invalidate() }
      .interactiveDismissDisabled(busy)
    }
    #if os(macOS)
    .frame(minWidth: 460, idealWidth: 600, minHeight: 420)
    #endif
  }

  private func invalidate() {
    discovery = nil
    selectedTools = []
    errorMessage = nil
  }

  private func testConnection() {
    busy = true
    invalidate()
    Task {
      defer { busy = false }
      do {
        discovery = try await model.requireAPI().discoverMCPServer(
          url: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
          accessToken: authentication == "none" ? nil : token.trimmingCharacters(in: .whitespacesAndNewlines))
      } catch { errorMessage = error.localizedDescription }
    }
  }

  private func save() {
    busy = true
    errorMessage = nil
    Task {
      defer { busy = false }
      do {
        let api = try model.requireAPI()
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if canRename, let editingID {
          _ = try await api.renameMCPServer(id: editingID, name: cleanName)
        } else if let discovery {
          let connection: Capability
          if let savedConnection { connection = savedConnection }
          else {
            let permissions = Dictionary(uniqueKeysWithValues: discovery.tools
              .filter { selectedTools.contains($0.name) }.map { ($0.name, $0.digest) })
            connection = try await api.connectReviewedMCPServer(
              name: cleanName, url: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
              accessToken: authentication == "none" ? nil : token.trimmingCharacters(in: .whitespacesAndNewlines),
              approvedTools: permissions)
            savedConnection = connection
          }
          for bot in model.bootstrap?.bots ?? [] where selectedBots.contains(bot.id) {
            var draft = BotDraft(bot: bot)
            if !draft.toolIds.contains(connection.id) { draft.toolIds.append(connection.id) }
            _ = try await api.saveBot(draft, id: bot.id)
          }
        }
        token = ""
        onSaved()
        dismiss()
      } catch {
        errorMessage = savedConnection == nil ? error.localizedDescription
          : "The connection was saved. Bot assignment needs another try: \(error.localizedDescription)"
      }
    }
  }
}
