import SwiftUI

struct GroupRoutineEditor: View {
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
            .froggyGlassButton(prominent: true)
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
