import SwiftUI

public struct FeatureSheet: View {
  let sheet: AppSheet
  @Bindable var model: AppModel
  let auth: AuthSession
  public var body: some View {
    NavigationStack {
      switch sheet {
      case .botLibrary: BotLibrary(model: model)
      case .botEditor(let id): BotEditor(model: model, id: id)
      case .groupEditor(let id): GroupEditor(model: model, id: id)
      case .schedules(let selection): SchedulesView(model: model, selection: selection)
      case .scheduleRuns(let selection): ScheduleRunsView(model: model, selection: selection)
      case .memories(let id): MemoriesView(model: model, groupId: id)
      case .account: AccountView(model: model, auth: auth)
      case .skills: SkillsView(model: model)
      case .skillEditor(let id): SkillEditor(model: model, id: id)
      case .connections: ConnectionsView(model: model)
      case .documents(let id): DocumentsView(model: model, botId: id)
      case .browser(let botId, let groupId):
        BrowserHandoffView(model: model, botId: botId, groupId: groupId)
      case .share(let selection): ShareView(model: model, selection: selection)
      }
    }
    .froggySheetSize()
    .tint(FrogTheme.brand)
  }
}

struct CloseButton: ToolbarContent {
  @Environment(\.dismiss) private var dismiss
  var body: some ToolbarContent {
    ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
  }
}

private struct BotLibrary: View {
  @Bindable var model: AppModel
  var body: some View {
    List {
      Button {
        model.sheet = .botEditor(nil)
      } label: {
        Label("Create a custom bot", systemImage: "plus.circle.fill")
      }
      Section("Templates") {
        ForEach(model.bootstrap?.botTemplates ?? []) { template in
          HStack {
            BotAvatar(name: template.name, color: template.color)
            VStack(alignment: .leading) {
              Text(template.name).font(.headline)
              Text(template.tagline).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Install") { Task { await model.installTemplate(template.id) } }
          }
        }
        if model.bootstrap?.botTemplates.isEmpty != false {
          ContentUnavailableView("No templates", systemImage: "square.grid.2x2")
        }
      }
    }.froggyListSurface().navigationTitle("Add a bot").toolbar { CloseButton() }
  }
}

private struct BotEditor: View {
  @Bindable var model: AppModel
  let id: String?
  @State private var draft = BotDraft()
  @State private var saving = false
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    let alwaysAllowedTools = revocableAlwaysAllowedTools(
      tools: model.bootstrap?.tools ?? [], skills: model.bootstrap?.skills ?? [], draft: draft)
    Form {
      Section("Identity") {
        TextField("Name", text: $draft.name)
        TextField("What this bot does", text: $draft.tagline)
        HStack {
          TextField("Color", text: $draft.color)
          BotAvatar(name: draft.name.isEmpty ? "F" : draft.name, color: draft.color)
        }
      }
      Section("Instructions") { TextEditor(text: $draft.prompt).frame(minHeight: 150) }
      Section("Skills") {
        capabilitySelection(
          items: model.bootstrap?.skills.map {
            Capability(id: $0.id, name: $0.name, description: $0.description)
          } ?? [], values: $draft.skillIds)
      }
      Section("Tools") {
        capabilitySelection(items: model.bootstrap?.tools ?? [], values: $draft.toolIds)
      }
      if !alwaysAllowedTools.isEmpty {
        Section {
          capabilitySelection(items: alwaysAllowedTools, values: $draft.alwaysAllowedToolIds)
        } header: {
          Text("Always allowed in direct chats")
        } footer: {
          Text(
            "Turn one off to require approval again. Groups and schedules still require supervision."
          )
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(id == nil ? "New bot" : "Edit bot")
    .toolbar {
      CloseButton()
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") { save() }.disabled(
          draft.name.trimmingCharacters(in: .whitespaces).isEmpty || saving)
      }
    }
    .onAppear {
      if let id, let bot = model.bootstrap?.bots.first(where: { $0.id == id }) {
        draft = BotDraft(bot: bot)
      }
    }
  }
  @ViewBuilder private func capabilitySelection(items: [Capability], values: Binding<[String]>)
    -> some View
  {
    ForEach(items) { item in
      Toggle(
        isOn: Binding(
          get: { values.wrappedValue.contains(item.id) },
          set: { enabled in
            if enabled {
              values.wrappedValue.append(item.id)
            } else {
              values.wrappedValue.removeAll { $0 == item.id }
            }
          })
      ) {
        VStack(alignment: .leading) {
          Text(item.name)
          Text(item.description).font(.caption).foregroundStyle(.secondary)
        }
      }
    }
  }
  private func save() {
    saving = true
    Task {
      if await model.saveBot(draft, id: id) { dismiss() }
      saving = false
    }
  }
}

func revocableAlwaysAllowedTools(tools: [Capability], skills: [Skill], draft: BotDraft)
  -> [Capability]
{
  let selectedSkillIDs = Set(draft.skillIds)
  let requiredToolIDs = skills.lazy
    .filter { selectedSkillIDs.contains($0.id) }
    .flatMap(\.requiredToolIds)
  let activeToolIDs = Set(draft.toolIds).union(requiredToolIDs)
  let allowedToolIDs = Set(draft.alwaysAllowedToolIds)
  return tools.filter {
    $0.risk == "interactive" && activeToolIDs.contains($0.id) && allowedToolIDs.contains($0.id)
  }
}

private struct GroupEditor: View {
  @Bindable var model: AppModel
  let id: String?
  @State private var draft = GroupDraft()
  @State private var saving = false
  @Environment(\.dismiss) private var dismiss
  private var group: BotGroup? { model.bootstrap?.groups.first { $0.id == id } }
  private var editable: Bool { group == nil || group?.allowedActions?.contains("edit") == true }
  var body: some View {
    Form {
      Section("Group") {
        TextField("Name", text: $draft.name)
        TextEditor(text: $draft.memory).frame(minHeight: 90)
      }.disabled(!editable)
      Section("Bots") {
        ForEach(model.bootstrap?.bots ?? []) { bot in
          Toggle(
            isOn: Binding(
              get: { draft.botIds.contains(bot.id) },
              set: { on in
                if on {
                  draft.botIds.append(bot.id)
                } else {
                  draft.botIds.removeAll { $0 == bot.id }
                }
              })
          ) { Label(bot.name, systemImage: "bubble.left") }
        }
      }.disabled(!editable)
      if let group {
        Section("Members") {
          ForEach(group.members) { member in
            HStack {
              Text(member.name)
              Spacer()
              Text(member.role.capitalized).foregroundStyle(.secondary)
              if member.allowedActions?.contains(where: { $0 == "remove" || $0 == "leave" }) == true
              {
                Button(
                  member.allowedActions?.contains("leave") == true ? "Leave" : "Remove",
                  role: .destructive
                ) { remove(member.id) }
              }
            }
          }
        }
        Section("Saved decisions") {
          ForEach(group.decisions) { decision in
            VStack(alignment: .leading) {
              Text(decision.text)
              Text("Saved by \(decision.createdByName)").font(.caption).foregroundStyle(.secondary)
            }
            .swipeActions {
              if decision.allowedActions?.contains("remove") == true {
                Button("Delete", role: .destructive) { deleteDecision(decision.id) }
              }
            }
          }
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(id == nil ? "New group" : "Edit group")
    .toolbar {
      CloseButton()
      if editable {
        ToolbarItem(placement: .confirmationAction) {
          Button("Save") { save() }.disabled(draft.name.isEmpty || draft.botIds.isEmpty || saving)
        }
      }
    }
    .onAppear { if let group { draft = GroupDraft(group: group) } }
  }
  private func save() {
    saving = true
    Task {
      if await model.saveGroup(draft, id: id) { dismiss() }
      saving = false
    }
  }
  private func remove(_ member: String) {
    guard let id, let api = model.api else { return }
    Task {
      do {
        try await api.removeMember(groupId: id, memberId: member)
        await model.refreshBootstrap()
      } catch { model.present(error) }
    }
  }
  private func deleteDecision(_ decision: String) {
    guard let id, let api = model.api else { return }
    Task {
      do {
        try await api.deleteDecision(groupId: id, decisionId: decision)
        await model.refreshBootstrap()
      } catch { model.present(error) }
    }
  }
}

private struct SchedulesView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  @State private var schedules: [ScheduledTask] = []
  @State private var editing: ScheduledTask?
  @State private var creating = false
  var body: some View {
    List {
      ForEach(schedules) { item in
        HStack {
          Button {
            editing = item
          } label: {
            HStack {
              Image(systemName: item.enabled ? "clock.badge.checkmark" : "clock")
              VStack(alignment: .leading) {
                Text(item.name)
                Text("\(item.frequency.capitalized) · \(item.time) · \(item.timezone)")
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
              Spacer()
            }
            .contentShape(Rectangle())
          }
          .buttonStyle(.plain)
          Button("Run") { run(item.id) }
            .froggyGlassButton(tint: FrogTheme.brand)
            .controlSize(.small)
        }
      }.onDelete(perform: remove)
      if schedules.isEmpty {
        ContentUnavailableView("No scheduled tasks", systemImage: "calendar.badge.plus")
      }
    }.froggyListSurface().navigationTitle("Scheduled tasks")
      .toolbar {
        CloseButton()
        ToolbarItem(placement: .primaryAction) {
          Button("New", systemImage: "plus") { creating = true }
        }
      }
      .task { await load() }
      .sheet(isPresented: $creating) {
        NavigationStack {
          ScheduleEditor(model: model, selection: selection, existing: nil) { await load() }
        }
        .froggySheetSize()
      }
      .sheet(item: $editing) { task in
        NavigationStack {
          ScheduleEditor(model: model, selection: selection, existing: task) { await load() }
        }
        .froggySheetSize()
      }
  }
  private func load() async {
    guard let api = model.api else { return }
    do { schedules = try await api.schedules(for: selection) } catch { model.present(error) }
  }
  private func run(_ id: String) {
    Task {
      do {
        try await model.api?.runSchedule(id, selection: selection)
        await load()
      } catch { model.present(error) }
    }
  }
  private func remove(at offsets: IndexSet) {
    for index in offsets {
      let id = schedules[index].id
      Task {
        do {
          try await model.api?.deleteSchedule(id, selection: selection)
          await load()
        } catch { model.present(error) }
      }
    }
  }
}

private struct ScheduleEditor: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  let existing: ScheduledTask?
  let completed: () async -> Void
  @State private var draft = ScheduledTaskDraft()
  @Environment(\.dismiss) private var dismiss
  var body: some View {
    Form {
      TextField("Name", text: $draft.name)
      TextEditor(text: $draft.prompt).frame(minHeight: 130)
      Picker("Frequency", selection: $draft.frequency) {
        ForEach(["hourly", "daily", "weekdays", "weekly", "monthly"], id: \.self) {
          Text($0.capitalized)
        }
      }
      if draft.frequency == "weekly" {
        TextField(
          "Day of week",
          text: Binding(get: { draft.dayOfWeek ?? "Monday" }, set: { draft.dayOfWeek = $0 }))
      }
      if draft.frequency == "monthly" {
        Stepper(
          "Day \(draft.dayOfMonth ?? 1)",
          value: Binding(get: { draft.dayOfMonth ?? 1 }, set: { draft.dayOfMonth = $0 }), in: 1...28
        )
      }
      TextField("Time (HH:mm)", text: $draft.time)
      TextField("Timezone", text: $draft.timezone)
      Toggle("Enabled", isOn: $draft.enabled)
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(existing == nil ? "New task" : "Edit task")
    .toolbar {
      CloseButton()
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") {
          Task {
            do {
              _ = try await model.api?.saveSchedule(draft, selection: selection, id: existing?.id)
              await completed()
              dismiss()
            } catch { model.present(error) }
          }
        }
        .disabled(draft.name.isEmpty || draft.prompt.isEmpty)
      }
    }
    .onAppear { if let existing { draft = ScheduledTaskDraft(task: existing) } }
  }
}

private struct ScheduleRunsView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  @State private var runs: [ScheduleRun] = []
  var body: some View {
    List(runs) { run in
      VStack(alignment: .leading, spacing: 6) {
        HStack {
          Text(run.scheduleName).font(.headline)
          Spacer()
          Text(run.status.capitalized).foregroundStyle(
            run.status == "complete" ? FrogTheme.green : .secondary)
        }
        Text(run.prompt).lineLimit(2)
        if let output = run.output {
          Text(output).font(.callout).foregroundStyle(.secondary).lineLimit(5)
        }
      }
    }
    .froggyListSurface()
    .navigationTitle("Run history").toolbar { CloseButton() }.task {
      do { runs = try await model.api?.scheduleRuns(for: selection) ?? [] } catch {
        model.present(error)
      }
    }
  }
}

struct MemoriesView: View {
  @Bindable var model: AppModel
  let groupId: String?
  @State private var snapshot: MemorySnapshot?
  @State private var newMemory = ""
  @State private var newKind = "fact"
  @State private var editingID: String?
  @State private var editingText = ""
  private var editable: Bool {
    guard let groupId else { return true }
    return model.bootstrap?.groups.first(where: { $0.id == groupId })?.allowedActions?.contains(
      "manageMemory") == true
  }
  var body: some View {
    List {
      if editable {
        Section {
          if groupId == nil {
            Picker("Kind", selection: $newKind) {
              Text("Fact").tag("fact")
              Text("Preference").tag("preference")
            }
            .pickerStyle(.segmented)
          }
          HStack {
            TextField("Add a fact or preference", text: $newMemory)
            Button("Add") { add() }.disabled(newMemory.isEmpty)
          }
        }
      }
      Section("Remembered") {
        ForEach(snapshot?.records ?? []) { record in
          Group {
            if editingID == record.id {
              VStack(alignment: .leading) {
                TextField("Memory text", text: $editingText, axis: .vertical)
                HStack {
                  Button("Cancel") { editingID = nil }
                  Button("Save") { update(record) }.disabled(
                    editingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
              }
            } else {
              VStack(alignment: .leading) {
                Text(record.content)
                Text("\(record.kind.capitalized) · \(record.source)").font(.caption)
                  .foregroundStyle(.secondary)
              }
            }
          }
          .swipeActions {
            if editable {
              Button("Forget", role: .destructive) { remove(record.id) }
              Button("Edit") {
                editingID = record.id
                editingText = record.content
              }.tint(FrogTheme.green)
            }
          }
        }
      }
      Section("Privacy") {
        Text(
          "Raw conversation history is retained for \(snapshot?.rawConversationRetentionDays ?? 0) days. Learned memory can be reviewed and deleted here."
        ).font(.footnote)
      }
    }.froggyListSurface().navigationTitle(groupId == nil ? "Memory" : "Group memory").toolbar { CloseButton() }.task {
      await load()
    }
  }
  private func load() async {
    do { snapshot = try await model.api?.memories(groupId: groupId) } catch { model.present(error) }
  }
  private func add() {
    let content = newMemory
    newMemory = ""
    Task {
      do {
        _ = try await model.api?.createMemory(kind: newKind, content: content, groupId: groupId)
        await load()
      } catch { model.present(error) }
    }
  }
  private func update(_ record: MemoryRecord) {
    let content = editingText
    editingID = nil
    Task {
      do {
        _ = try await model.api?.updateMemory(id: record.id, content: content, groupId: groupId)
        await load()
      } catch { model.present(error) }
    }
  }
  private func remove(_ id: String) {
    Task {
      do {
        try await model.api?.deleteMemory(id: id, groupId: groupId)
        await load()
      } catch { model.present(error) }
    }
  }
}

struct SkillsView: View {
  @Bindable var model: AppModel
  var body: some View {
    List {
      ForEach(model.bootstrap?.skills ?? []) { skill in
        NavigationLink {
          SkillDetailView(model: model, id: skill.id)
        } label: {
          VStack(alignment: .leading) {
            HStack {
              Text(skill.name).font(.headline)
              if skill.source == "official" {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(FrogTheme.green)
              }
            }
            Text(skill.description).foregroundStyle(.secondary)
          }
        }
      }
      if model.bootstrap?.skills.isEmpty != false {
        ContentUnavailableView("No skills", systemImage: "sparkles")
      }
    }.froggyListSurface().navigationTitle("Skills").toolbar {
      CloseButton()
      ToolbarItem(placement: .primaryAction) {
        Button("Create", systemImage: "plus") { model.sheet = .skillEditor(nil) }
      }
    }
  }
}

private struct SkillDetailView: View {
  @Bindable var model: AppModel
  let id: String
  @State private var detail: SkillDetail?
  @State private var shareURL: URL?
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        Text(detail?.description ?? "").font(.title3)
        Text(detail?.instructions ?? "")
        if detail?.editable == true {
          Button("Edit") { model.sheet = .skillEditor(id) }
            .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
        }
        if let shareURL {
          ShareLink(item: shareURL) { Label("Share link", systemImage: "square.and.arrow.up") }
        } else if detail != nil {
          Button("Create share link", systemImage: "link") { share() }
        }
      }.padding()
    }
    .background(FrogTheme.pageBackground)
    .navigationTitle(detail?.name ?? "Skill").task {
      do { detail = try await model.api?.skill(id) } catch { model.present(error) }
    }
  }
  private func share() {
    Task { do { shareURL = try await model.api?.shareSkill(id) } catch { model.present(error) } }
  }
}
