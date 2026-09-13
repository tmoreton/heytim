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
    .tint(FrogTheme.accent)
  }
}

struct CloseButton: ToolbarContent {
  @Environment(\.dismiss) private var dismiss
  private let action: (() -> Void)?

  init(action: (() -> Void)? = nil) {
    self.action = action
  }

  var body: some ToolbarContent {
    ToolbarItem(placement: .cancellationAction) {
      Button("Close") {
        if let action {
          action()
        } else {
          dismiss()
        }
      }
    }
  }
}

private struct GuidedTextEditor: View {
  let title: String
  let prompt: String
  @Binding var text: String
  let minHeight: CGFloat

  var body: some View {
    TextEditor(text: $text)
      .frame(minHeight: minHeight)
      .overlay(alignment: .topLeading) {
        if text.isEmpty {
          Text(prompt)
            .foregroundStyle(.tertiary)
            .padding(.horizontal, 5)
            .padding(.vertical, 8)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
      }
      .accessibilityLabel(title)
      .accessibilityHint(prompt)
  }
}

private struct BotColorOption: Identifiable, Sendable {
  let value: String
  let name: String
  var id: String { value }
}

private struct ScheduleWeekday: Identifiable, Sendable {
  let id: String
  let name: String
}

private let customBotColors = [
  BotColorOption(value: "#58BEAA", name: "Teal"),
  BotColorOption(value: "#FFAA34", name: "Gold"),
  BotColorOption(value: "#6C5CE7", name: "Purple"),
  BotColorOption(value: "#3984F6", name: "Blue"),
  BotColorOption(value: "#F46A27", name: "Orange"),
  BotColorOption(value: "#E95383", name: "Pink"),
]

private struct BotColorPicker: View {
  @Binding var selection: String
  let options: [BotColorOption]

  var body: some View {
    HStack(spacing: 4) {
      ForEach(options) { option in
        Button {
          selection = option.value
        } label: {
          ZStack {
            Circle()
              .fill(Color(hex: option.value))
              .frame(width: 30, height: 30)
            if selection == option.value {
              Image(systemName: "checkmark")
                .font(.caption.bold())
                .foregroundStyle(.white)
                .shadow(radius: 1)
            }
          }
          .frame(width: 44, height: 44)
          .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(option.name)
        .accessibilityValue(selection == option.value ? "Selected" : "")
      }
    }
    .accessibilityElement(children: .contain)
    .accessibilityLabel("Bot color")
  }
}

struct BotLibrary: View {
  @Bindable var model: AppModel
  @State private var search = ""

  private var templates: [BotTemplate] {
    (model.bootstrap?.botTemplates ?? []).filter {
      search.isEmpty || $0.name.localizedCaseInsensitiveContains(search)
        || $0.tagline.localizedCaseInsensitiveContains(search)
        || ($0.category?.localizedCaseInsensitiveContains(search) == true)
        || ($0.tags?.contains(where: { $0.localizedCaseInsensitiveContains(search) }) == true)
    }
  }

  private var featured: [BotTemplate] { templates.filter { $0.featured == true } }
  private var remaining: [BotTemplate] { templates.filter { $0.featured != true } }

  var body: some View {
    List {
      Section {
        Button {
          model.sheet = .botEditor(nil)
        } label: {
          Label("Create a Custom Bot", systemImage: "slider.horizontal.3")
        }
      } footer: {
        Text("Start from a template below, or choose every instruction, skill, and tool yourself.")
      }

      if !featured.isEmpty {
        Section("Featured") {
          ForEach(featured) { template in
            templateLink(template)
          }
        }
      }
      if !remaining.isEmpty {
        Section(featured.isEmpty ? "Templates" : "More Templates") {
          ForEach(remaining) { template in
            templateLink(template)
          }
        }
      }
      if templates.isEmpty {
        ContentUnavailableView(
          search.isEmpty ? "No Templates" : "No Matching Bots",
          systemImage: search.isEmpty ? "square.grid.2x2" : "magnifyingglass",
          description: Text(search.isEmpty ? "Bot templates are temporarily unavailable." : "Try another name, category, or skill."))
      }
    }
    .froggyListSurface()
    .navigationTitle("Add a Bot")
    .searchable(text: $search, prompt: "Search templates")
    .toolbar { CloseButton { model.sheet = nil } }
  }

  private func templateLink(_ template: BotTemplate) -> some View {
    NavigationLink {
      BotTemplateDetailView(model: model, template: template)
    } label: {
      HStack(spacing: 12) {
        BotAvatar(name: template.name, color: template.color)
        VStack(alignment: .leading, spacing: 4) {
          HStack {
            Text(template.name).font(.headline)
            if isInstalled(template) {
              Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(FrogTheme.accent)
                .accessibilityLabel("Added")
            }
          }
          Text(template.tagline).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
          HStack(spacing: 12) {
            Label(countLabel(template.skillIds.count, singular: "skill"), systemImage: "sparkles")
            Label(countLabel(effectiveToolCount(template), singular: "tool"), systemImage: "wrench.and.screwdriver")
          }
          .font(.caption)
          .foregroundStyle(.secondary)
        }
      }
      .padding(.vertical, 3)
    }
    .accessibilityIdentifier("bot.template.\(template.id)")
  }

  private func isInstalled(_ template: BotTemplate) -> Bool {
    model.bootstrap?.bots.contains(where: { $0.templateId == template.id }) == true
  }

  private func effectiveToolCount(_ template: BotTemplate) -> Int {
    template.effectiveToolIDs(skills: model.bootstrap?.skills ?? []).count
  }

  private func countLabel(_ count: Int, singular: String) -> String {
    "\(count) \(singular)\(count == 1 ? "" : "s")"
  }
}

private struct BotTemplateDetailView: View {
  @Bindable var model: AppModel
  let template: BotTemplate
  @State private var installing = false

  private var skills: [Skill] {
    let byID = Dictionary(uniqueKeysWithValues: (model.bootstrap?.skills ?? []).map { ($0.id, $0) })
    return template.skillIds.compactMap { byID[$0] }
  }

  private var toolIDs: [String] {
    template.effectiveToolIDs(skills: model.bootstrap?.skills ?? [])
  }

  private var toolsByID: [String: Capability] {
    Dictionary(uniqueKeysWithValues: (model.bootstrap?.tools ?? []).map { ($0.id, $0) })
  }

  private var installed: Bool {
    model.bootstrap?.bots.contains(where: { $0.templateId == template.id }) == true
  }

  var body: some View {
    Form {
      Section {
        HStack(alignment: .top, spacing: 14) {
          BotAvatar(name: template.name, color: template.color, size: 54)
          VStack(alignment: .leading, spacing: 5) {
            Text(template.name).font(.title2.bold())
            Text(template.tagline).foregroundStyle(.secondary)
            if let category = template.category {
              Text(category).font(.caption).foregroundStyle(FrogTheme.accent)
            }
          }
        }
        .padding(.vertical, 5)
      }

      Section {
        if skills.isEmpty {
          Text("This bot follows its focused instructions without an additional skill package.")
            .foregroundStyle(.secondary)
        } else {
          ForEach(skills) { skill in
            Label {
              VStack(alignment: .leading, spacing: 2) {
                Text(skill.name)
                Text(skill.description).font(.caption).foregroundStyle(.secondary)
              }
            } icon: {
              Image(systemName: "sparkles")
            }
          }
        }
      } header: {
        Text("Included Skills")
          .accessibilityIdentifier("bot.template.skills")
      }

      Section {
        if toolIDs.isEmpty {
          Text("No tools are required.").foregroundStyle(.secondary)
        } else {
          ForEach(toolIDs, id: \.self) { id in
            Label {
              VStack(alignment: .leading, spacing: 2) {
                Text(toolsByID[id]?.name ?? capabilityName(id))
                if let description = toolsByID[id]?.description, !description.isEmpty {
                  Text(description).font(.caption).foregroundStyle(.secondary)
                }
              }
            } icon: {
              Image(systemName: "wrench.and.screwdriver")
            }
          }
        }
      } header: {
        Text("Tools This Bot Can Use")
          .accessibilityIdentifier("bot.template.tools")
      }

      Section {
        DisclosureGroup("View Full Instructions") {
          Text(template.prompt)
            .font(.callout)
            .textSelection(.enabled)
            .padding(.vertical, 6)
        }
      } footer: {
        Text("You can edit the bot after adding it. Connected accounts are never added automatically.")
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(template.name)
    .toolbar {
      ToolbarItem(placement: .confirmationAction) {
        if installed {
          Label("Added", systemImage: "checkmark.circle.fill")
            .foregroundStyle(FrogTheme.accent)
        } else {
          Button("Add Bot") {
            installing = true
            Task {
              await model.installTemplate(template.id)
              installing = false
            }
          }
          .disabled(installing)
        }
      }
    }
    .overlay { if installing { ProgressView() } }
  }

  private func capabilityName(_ id: String) -> String {
    id.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
  }
}

private struct BotEditor: View {
  @Bindable var model: AppModel
  let id: String?
  @State private var draft = BotDraft()
  @State private var saving = false
  @Environment(\.dismiss) private var dismiss

  private var editingBot: Bot? {
    guard let id else { return nil }
    return model.bootstrap?.bots.first(where: { $0.id == id })
  }

  private var colorOptions: [BotColorOption] {
    if editingBot?.systemRole == "chief" {
      return [BotColorOption(value: "#007A3D", name: "FroggyBot green")]
    }
    return customBotColors
  }

  private var identityIssue: String? {
    let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
    if name.isEmpty { return "Enter a bot name." }
    if draft.name.count > model.constraints.botNameMaxLength {
      return "Keep the name under \(model.constraints.botNameMaxLength) characters."
    }
    if draft.tagline.count > model.constraints.botTaglineMaxLength {
      return "Keep the description under \(model.constraints.botTaglineMaxLength) characters."
    }
    return nil
  }

  private var instructionsIssue: String? {
    if draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Add instructions so the bot knows how to help."
    }
    if draft.prompt.count > model.constraints.botPromptMaxLength {
      return "Instructions are longer than the supported limit."
    }
    return nil
  }

  private var canSave: Bool { identityIssue == nil && instructionsIssue == nil && !saving }

  var body: some View {
    let alwaysAllowedTools = revocableAlwaysAllowedTools(
      tools: model.bootstrap?.tools ?? [], skills: model.bootstrap?.skills ?? [], draft: draft)
    Form {
      Section {
        TextField("Name", text: $draft.name)
        TextField("What this bot does", text: $draft.tagline)
        VStack(alignment: .leading, spacing: 4) {
          Text("Color").font(.subheadline)
          BotColorPicker(selection: $draft.color, options: colorOptions)
        }
      } header: {
        Text("Identity")
      } footer: {
        Text(identityIssue ?? "Use a short name and a one-line description people can scan quickly.")
          .foregroundStyle(
            identityIssue == nil || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              ? Color.secondary : Color.red)
      }
      Section {
        GuidedTextEditor(
          title: "Instructions",
          prompt: "Describe this bot’s role, tone, boundaries, and what a successful answer looks like.",
          text: $draft.prompt,
          minHeight: 150)
      } header: {
        Text("Instructions")
      } footer: {
        HStack(alignment: .firstTextBaseline) {
          Text(instructionsIssue ?? "Be specific. You can revise these instructions later.")
          Spacer(minLength: 12)
          Text("\(draft.prompt.count.formatted()) / \(model.constraints.botPromptMaxLength.formatted())")
            .monospacedDigit()
        }
        .foregroundStyle(
          instructionsIssue == nil || draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? Color.secondary : Color.red)
      }
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
      CloseButton { model.sheet = nil }
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") { save() }.disabled(!canSave)
      }
    }
    .onAppear {
      if let bot = editingBot {
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
  @State private var memberRemovalCandidate: GroupMember?
  @Environment(\.dismiss) private var dismiss
  private var group: BotGroup? { model.bootstrap?.groups.first { $0.id == id } }
  private var editable: Bool { group == nil || group?.allowedActions?.contains("edit") == true }
  private var groupIssue: String? {
    if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Enter a group name."
    }
    if draft.name.count > model.constraints.groupNameMaxLength {
      return "Keep the name under \(model.constraints.groupNameMaxLength) characters."
    }
    return nil
  }
  private var memoryIssue: String? {
    draft.memory.count > model.constraints.groupMemoryMaxLength
      ? "Shared context is longer than the supported limit." : nil
  }
  private var canSave: Bool {
    groupIssue == nil && memoryIssue == nil && !draft.botIds.isEmpty && !saving
  }

  var body: some View {
    Form {
      Section {
        TextField("Name", text: $draft.name)
      } header: {
        Text("Group")
      } footer: {
        Text(groupIssue ?? "Choose a name everyone will recognize.")
          .foregroundStyle(
            groupIssue == nil || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              ? Color.secondary : Color.red)
      }
      .disabled(!editable)
      Section {
        GuidedTextEditor(
          title: "Shared context",
          prompt: "Add goals, decisions, or background every bot in this group should know.",
          text: $draft.memory,
          minHeight: 100)
      } header: {
        Text("Shared Context")
      } footer: {
        HStack(alignment: .firstTextBaseline) {
          Text(memoryIssue ?? "Optional. This context is available to every bot in the group.")
          Spacer(minLength: 12)
          Text("\(draft.memory.count.formatted()) / \(model.constraints.groupMemoryMaxLength.formatted())")
            .monospacedDigit()
        }
        .foregroundStyle(memoryIssue == nil ? Color.secondary : Color.red)
      }
      .disabled(!editable)
      Section {
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
      } header: {
        Text("Bots")
      } footer: {
        Text(draft.botIds.isEmpty ? "Choose at least one bot to continue." : "You can change the bot team later.")
          .foregroundStyle(.secondary)
      }
      .disabled(!editable)
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
                ) { memberRemovalCandidate = member }
                .tint(FrogTheme.danger)
                .foregroundStyle(FrogTheme.danger)
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
      CloseButton { model.sheet = nil }
      if editable {
        ToolbarItem(placement: .confirmationAction) {
          Button("Save") { save() }.disabled(!canSave)
        }
      }
    }
    .onAppear { if let group { draft = GroupDraft(group: group) } }
    .confirmationDialog(
      memberRemovalCandidate?.allowedActions?.contains("leave") == true
        ? "Leave this group?" : "Remove this person from the group?",
      isPresented: Binding(
        get: { memberRemovalCandidate != nil },
        set: { if !$0 { memberRemovalCandidate = nil } }),
      titleVisibility: .visible
    ) {
      if let memberRemovalCandidate {
        Button(
          memberRemovalCandidate.allowedActions?.contains("leave") == true
            ? "Leave Group" : "Remove \(memberRemovalCandidate.name)",
          role: .destructive
        ) { remove(memberRemovalCandidate.id) }
      }
      Button("Cancel", role: .cancel) { memberRemovalCandidate = nil }
    } message: {
      if let memberRemovalCandidate {
        Text(
          memberRemovalCandidate.allowedActions?.contains("leave") == true
            ? "You will lose access to this group and its conversation."
            : "\(memberRemovalCandidate.name) will lose access to this group and its conversation."
        )
      }
    }
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
    memberRemovalCandidate = nil
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
  @State private var runningID: String?
  @State private var deleteCandidate: ScheduledTask?
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
          Button { run(item.id) } label: {
            if runningID == item.id {
              HStack(spacing: 7) {
                ProgressView().controlSize(.small)
                Text("Running")
              }
            } else {
              Label("Run Now", systemImage: "play.fill")
            }
          }
            .froggyGlassButton(tint: FrogTheme.accent)
            .controlSize(.large)
            .frame(minWidth: 104, minHeight: 44)
            .disabled(runningID != nil)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
          Button("Delete", systemImage: "trash", role: .destructive) {
            deleteCandidate = item
          }
        }
        .contextMenu {
          Button("Edit Task", systemImage: "pencil") { editing = item }
          Button("Run Now", systemImage: "play.fill") { run(item.id) }
            .disabled(runningID != nil)
          Divider()
          Button("Delete Task", systemImage: "trash", role: .destructive) {
            deleteCandidate = item
          }
        }
      }
      if schedules.isEmpty {
        ContentUnavailableView("No scheduled tasks", systemImage: "calendar.badge.plus")
      }
    }.froggyListSurface().navigationTitle("Scheduled tasks")
      .toolbar {
        CloseButton { model.sheet = nil }
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
      .confirmationDialog(
        "Delete this scheduled task?",
        isPresented: Binding(
          get: { deleteCandidate != nil },
          set: { if !$0 { deleteCandidate = nil } }),
        titleVisibility: .visible
      ) {
        if let deleteCandidate {
          Button("Delete \(deleteCandidate.name)", role: .destructive) {
            remove(deleteCandidate)
          }
        }
        Button("Cancel", role: .cancel) { deleteCandidate = nil }
      } message: {
        Text("This stops all future runs. Past run history is not changed.")
      }
  }
  private func load() async {
    guard let api = model.api else { return }
    do { schedules = try await api.schedules(for: selection) } catch { model.present(error) }
  }
  private func run(_ id: String) {
    runningID = id
    Task {
      defer { runningID = nil }
      do {
        try await model.api?.runSchedule(id, selection: selection)
        await load()
      } catch { model.present(error) }
    }
  }
  private func remove(_ task: ScheduledTask) {
    deleteCandidate = nil
    Task {
      do {
        try await model.api?.deleteSchedule(task.id, selection: selection)
        await load()
      } catch { model.present(error) }
    }
  }
}

private struct ScheduleEditor: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  let existing: ScheduledTask?
  let completed: () async -> Void
  @State private var draft = ScheduledTaskDraft()
  @State private var saving = false
  @Environment(\.dismiss) private var dismiss

  private var weekdays: [ScheduleWeekday] {
    [
      ScheduleWeekday(id: "SUN", name: "Sunday"),
      ScheduleWeekday(id: "MON", name: "Monday"),
      ScheduleWeekday(id: "TUE", name: "Tuesday"),
      ScheduleWeekday(id: "WED", name: "Wednesday"),
      ScheduleWeekday(id: "THU", name: "Thursday"),
      ScheduleWeekday(id: "FRI", name: "Friday"),
      ScheduleWeekday(id: "SAT", name: "Saturday"),
    ]
  }

  private var timeZoneOptions: [String] {
    var seen = Set<String>()
    return [
      draft.timezone,
      TimeZone.current.identifier,
      "America/New_York",
      "America/Chicago",
      "America/Denver",
      "America/Los_Angeles",
      "UTC",
    ].filter { !$0.isEmpty && TimeZone(identifier: $0) != nil && seen.insert($0).inserted }
  }

  private var taskIssue: String? {
    if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Enter a task name."
    }
    if draft.name.count > model.constraints.scheduleNameMaxLength {
      return "Keep the task name under \(model.constraints.scheduleNameMaxLength) characters."
    }
    if draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Describe what the bot should do."
    }
    if draft.prompt.count > model.constraints.schedulePromptMaxLength {
      return "Task instructions are longer than the supported limit."
    }
    return nil
  }

  private var canSave: Bool { taskIssue == nil && !saving }

  var body: some View {
    Form {
      Section {
        TextField("Name", text: $draft.name)
        GuidedTextEditor(
          title: "Task instructions",
          prompt: "For example: Review the latest conversation and send me the three priorities for today.",
          text: $draft.prompt,
          minHeight: 130)
      } header: {
        Text("Task")
      } footer: {
        HStack(alignment: .firstTextBaseline) {
          Text(taskIssue ?? "The bot will follow these instructions each time the task runs.")
          Spacer(minLength: 12)
          Text("\(draft.prompt.count.formatted()) / \(model.constraints.schedulePromptMaxLength.formatted())")
            .monospacedDigit()
        }
        .foregroundStyle(
          taskIssue == nil
            || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? Color.secondary : Color.red)
      }

      Section {
        Picker("Repeat", selection: $draft.frequency) {
          ForEach(["hourly", "daily", "weekdays", "weekly", "monthly"], id: \.self) {
            Text($0.capitalized)
          }
        }
        if draft.frequency == "weekly" {
          Picker("Day", selection: weeklyDay) {
            ForEach(weekdays) { weekday in
              Text(weekday.name).tag(weekday.id)
            }
          }
        }
        if draft.frequency == "monthly" {
          Stepper(
            "Day \(draft.dayOfMonth ?? model.constraints.scheduleDayOfMonthMin)",
            value: Binding(
              get: { draft.dayOfMonth ?? model.constraints.scheduleDayOfMonthMin },
              set: { draft.dayOfMonth = $0 }),
            in: model.constraints.scheduleDayOfMonthMin...model.constraints.scheduleDayOfMonthMax
          )
        }
        if draft.frequency != "hourly" {
          DatePicker("Time", selection: taskTime, displayedComponents: .hourAndMinute)
        }
        Picker("Time Zone", selection: $draft.timezone) {
          ForEach(timeZoneOptions, id: \.self) { identifier in
            Text(timeZoneLabel(identifier)).tag(identifier)
          }
        }
      } header: {
        Text("Schedule")
      } footer: {
        Text(scheduleSummary)
      }

      Section {
        Toggle("Task is active", isOn: $draft.enabled)
      } footer: {
        Text("Turn this off to pause future runs without deleting the task.")
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(existing == nil ? "New task" : "Edit task")
    .toolbar {
      CloseButton { dismiss() }
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") { save() }
          .disabled(!canSave)
      }
    }
    .onAppear {
      if let existing { draft = ScheduledTaskDraft(task: existing) }
      normalizeConditionalFields()
    }
    .onChange(of: draft.frequency) { _, _ in normalizeConditionalFields() }
  }

  private var weeklyDay: Binding<String> {
    Binding(
      get: {
        guard let value = draft.dayOfWeek?.uppercased(),
          weekdays.contains(where: { $0.id == value })
        else { return "MON" }
        return value
      },
      set: { draft.dayOfWeek = $0 })
  }

  private var taskTime: Binding<Date> {
    Binding(
      get: {
        let values = draft.time.split(separator: ":").compactMap { Int($0) }
        let hour = values.indices.contains(0) ? values[0] : 9
        let minute = values.indices.contains(1) ? values[1] : 0
        return Calendar.current.date(
          bySettingHour: min(23, max(0, hour)),
          minute: min(59, max(0, minute)), second: 0, of: Date()) ?? Date()
      },
      set: { value in
        let components = Calendar.current.dateComponents([.hour, .minute], from: value)
        draft.time = String(
          format: "%02d:%02d", components.hour ?? 9, components.minute ?? 0)
      })
  }

  private var scheduleSummary: String {
    let zone = timeZoneLabel(draft.timezone)
    switch draft.frequency {
    case "hourly": return "Runs every hour on the hour in \(zone)."
    case "weekdays": return "Runs Monday through Friday at the selected time in \(zone)."
    case "weekly":
      let name = weekdays.first(where: { $0.id == weeklyDay.wrappedValue })?.name ?? "Monday"
      return "Runs every \(name) at the selected time in \(zone)."
    case "monthly":
      return "Runs on day \(draft.dayOfMonth ?? model.constraints.scheduleDayOfMonthMin) of each month in \(zone)."
    default: return "Runs every day at the selected time in \(zone)."
    }
  }

  private func timeZoneLabel(_ identifier: String) -> String {
    guard let zone = TimeZone(identifier: identifier) else {
      return identifier.replacingOccurrences(of: "_", with: " ")
    }
    let name = zone.localizedName(for: .shortGeneric, locale: .current) ?? identifier
    return "\(name) · \(identifier.replacingOccurrences(of: "_", with: " "))"
  }

  private func normalizeConditionalFields() {
    if draft.frequency == "weekly" {
      let raw = draft.dayOfWeek?.uppercased() ?? "MON"
      let aliases = [
        "SUNDAY": "SUN", "MONDAY": "MON", "TUESDAY": "TUE", "WEDNESDAY": "WED",
        "THURSDAY": "THU", "FRIDAY": "FRI", "SATURDAY": "SAT",
      ]
      draft.dayOfWeek = weekdays.contains(where: { $0.id == raw }) ? raw : aliases[raw] ?? "MON"
    } else {
      draft.dayOfWeek = nil
    }
    if draft.frequency == "monthly" {
      let lower = model.constraints.scheduleDayOfMonthMin
      let upper = model.constraints.scheduleDayOfMonthMax
      draft.dayOfMonth = min(upper, max(lower, draft.dayOfMonth ?? lower))
    } else {
      draft.dayOfMonth = nil
    }
  }

  private func save() {
    saving = true
    Task {
      defer { saving = false }
      do {
        _ = try await model.api?.saveSchedule(draft, selection: selection, id: existing?.id)
        await completed()
        dismiss()
      } catch { model.present(error) }
    }
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
    .navigationTitle("Run history").toolbar { CloseButton { model.sheet = nil } }.task {
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
  @State private var loading = true
  @State private var loadError: String?
  @State private var savingNewMemory = false
  @State private var busyMemoryID: String?
  @State private var forgetCandidate: MemoryRecord?

  private var editable: Bool {
    guard let groupId else { return true }
    return model.bootstrap?.groups.first(where: { $0.id == groupId })?.allowedActions?.contains(
      "manageMemory") == true
  }

  private var maximumLength: Int { model.bootstrap?.constraints.memoryMaxLength ?? 16_000 }
  private var trimmedNewMemory: String {
    newMemory.trimmingCharacters(in: .whitespacesAndNewlines)
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
            Button("Add") { add() }
              .disabled(
                trimmedNewMemory.isEmpty || newMemory.count > maximumLength || savingNewMemory)
          }
          if !newMemory.isEmpty {
            HStack {
              if newMemory.count > maximumLength {
                Text("Memory is too long").foregroundStyle(.red)
              }
              Spacer()
              Text("\(newMemory.count.formatted()) / \(maximumLength.formatted())")
                .foregroundStyle(newMemory.count > maximumLength ? .red : .secondary)
            }
            .font(.caption)
          }
        }
      }
      Section("Remembered") {
        if loading {
          HStack {
            Spacer()
            ProgressView()
            Spacer()
          }
        } else if let loadError, snapshot == nil {
          ContentUnavailableView {
            Label("Couldn’t Load Memory", systemImage: "wifi.exclamationmark")
          } description: {
            Text(loadError)
          } actions: {
            Button("Try Again") { Task { await load() } }
          }
        } else if snapshot?.records.isEmpty != false {
          ContentUnavailableView(
            "Nothing Remembered Yet", systemImage: "brain.head.profile",
            description: Text("Facts and preferences you add or ask FroggyBot to remember will appear here."))
        } else {
          ForEach(snapshot?.records ?? []) { record in
            Group {
              if editingID == record.id {
                VStack(alignment: .leading, spacing: 8) {
                  TextField("Memory text", text: $editingText, axis: .vertical)
                  HStack {
                    Button("Cancel") {
                      editingID = nil
                      editingText = ""
                    }
                    Spacer()
                    Text("\(editingText.count.formatted()) / \(maximumLength.formatted())")
                      .font(.caption).foregroundStyle(.secondary)
                    Button("Save") { update(record) }.disabled(
                      editingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        || editingText.count > maximumLength || busyMemoryID != nil)
                  }
                }
              } else {
                VStack(alignment: .leading, spacing: 4) {
                  Text(record.content)
                  Text("\(record.kind.capitalized) · \(record.source)").font(.caption)
                    .foregroundStyle(.secondary)
                }
              }
            }
            .opacity(busyMemoryID == record.id ? 0.55 : 1)
            .swipeActions {
              if editable {
                Button("Forget", role: .destructive) { forgetCandidate = record }
                Button("Edit") {
                  editingID = record.id
                  editingText = record.content
                }.tint(FrogTheme.green)
              }
            }
          }
        }
      }
      if let snapshot {
        Section("Privacy") {
          Text(
            "Raw conversation history is retained for \(snapshot.rawConversationRetentionDays) days. Learned memory can be reviewed and deleted here."
          ).font(.footnote)
        }
      }
    }
    .froggyListSurface()
    .navigationTitle(groupId == nil ? "Memory" : "Group Memory")
    .toolbar { CloseButton { model.sheet = nil } }
    .refreshable { await load() }
    .task { await load() }
    .confirmationDialog(
      "Forget this memory?",
      isPresented: Binding(
        get: { forgetCandidate != nil }, set: { if !$0 { forgetCandidate = nil } }),
      titleVisibility: .visible
    ) {
      if let forgetCandidate {
        Button("Forget Memory", role: .destructive) { remove(forgetCandidate.id) }
      }
      Button("Cancel", role: .cancel) { forgetCandidate = nil }
    } message: {
      Text("FroggyBot will stop using this information in future conversations.")
    }
  }

  private func load() async {
    loading = true
    defer { loading = false }
    do {
      snapshot = try await model.requireAPI().memories(groupId: groupId)
      loadError = nil
    } catch {
      if snapshot == nil {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
  }

  private func add() {
    let content = trimmedNewMemory
    savingNewMemory = true
    Task {
      defer { savingNewMemory = false }
      do {
        _ = try await model.requireAPI().createMemory(
          kind: newKind, content: content, groupId: groupId)
        newMemory = ""
        await load()
      } catch { model.present(error) }
    }
  }

  private func update(_ record: MemoryRecord) {
    let content = editingText.trimmingCharacters(in: .whitespacesAndNewlines)
    busyMemoryID = record.id
    Task {
      defer { busyMemoryID = nil }
      do {
        _ = try await model.requireAPI().updateMemory(
          id: record.id, content: content, groupId: groupId)
        editingID = nil
        editingText = ""
        await load()
      } catch { model.present(error) }
    }
  }

  private func remove(_ id: String) {
    forgetCandidate = nil
    busyMemoryID = id
    Task {
      defer { busyMemoryID = nil }
      do {
        try await model.requireAPI().deleteMemory(id: id, groupId: groupId)
        await load()
      } catch { model.present(error) }
    }
  }
}

struct SkillsView: View {
  @Bindable var model: AppModel
  @State private var selection = CapabilityLibrarySection.skills

  private enum CapabilityLibrarySection: String, CaseIterable, Identifiable {
    case skills = "Skills"
    case tools = "Tools"
    var id: Self { self }
  }

  var body: some View {
    List {
      Section {
        Picker("Capabilities", selection: $selection) {
          ForEach(CapabilityLibrarySection.allCases) { section in
            Text("\(section.rawValue) \(count(for: section))").tag(section)
          }
        }
        .pickerStyle(.segmented)
        .accessibilityIdentifier("capabilities.selector")
      }

      switch selection {
      case .skills:
        Section("Skills") {
          ForEach(model.bootstrap?.skills ?? []) { skill in
            NavigationLink {
              SkillDetailView(model: model, id: skill.id)
            } label: {
              VStack(alignment: .leading, spacing: 3) {
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
            ContentUnavailableView("No Skills", systemImage: "sparkles")
          }
        }
      case .tools:
        Section("Built-in Tools") {
          ForEach(model.bootstrap?.tools.filter { $0.source != "user" } ?? []) { tool in
            NavigationLink {
              CapabilityDetailView(capability: tool)
            } label: {
              Label {
                VStack(alignment: .leading, spacing: 3) {
                  Text(tool.name).font(.headline)
                  Text(tool.description).foregroundStyle(.secondary)
                }
              } icon: {
                Image(systemName: tool.risk == "interactive" ? "hand.raised" : "wrench.and.screwdriver")
              }
            }
          }
          if model.bootstrap?.tools.filter({ $0.source != "user" }).isEmpty != false {
            ContentUnavailableView("No Tools", systemImage: "wrench.and.screwdriver")
          }
        }
      }
    }.froggyListSurface().navigationTitle("Capabilities").toolbar {
      CloseButton { model.sheet = nil }
      if selection == .skills {
        ToolbarItem(placement: .primaryAction) {
          Button("Create", systemImage: "plus") { model.sheet = .skillEditor(nil) }
        }
      }
    }
  }

  private func count(for section: CapabilityLibrarySection) -> Int {
    switch section {
    case .skills: model.bootstrap?.skills.count ?? 0
    case .tools: model.bootstrap?.tools.filter { $0.source != "user" }.count ?? 0
    }
  }
}

private struct CapabilityDetailView: View {
  let capability: Capability

  var body: some View {
    Form {
      Section {
        Text(capability.description)
      }
      Section("Details") {
        if let category = capability.category { LabeledContent("Category", value: category) }
        if let provider = capability.provider { LabeledContent("Provider", value: provider) }
        LabeledContent("Access", value: accessLabel)
        LabeledContent("Source", value: capability.source == "user" ? "Connected account" : "FroggyBot")
      }
      if let actions = capability.actions, !actions.isEmpty {
        Section("Actions") {
          ForEach(actions, id: \.self) { action in
            Label(action, systemImage: "checkmark.circle")
          }
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(capability.name)
  }

  private var accessLabel: String {
    capability.risk == "interactive" ? "Asks before making changes" : "Read only"
  }
}

private struct SkillDetailView: View {
  @Bindable var model: AppModel
  let id: String
  @State private var detail: SkillDetail?
  @State private var shareURL: URL?
  @State private var loadError: String?
  var body: some View {
    Form {
      if let detail {
        Section { Text(detail.description) }
        Section("Required Tools") {
          if detail.requiredToolIds.isEmpty {
            Text("No tools are required.").foregroundStyle(.secondary)
          } else {
            ForEach(detail.requiredToolIds, id: \.self) { toolID in
              let tool = model.bootstrap?.tools.first { $0.id == toolID }
              Label(tool?.name ?? capabilityName(toolID), systemImage: "wrench.and.screwdriver")
            }
          }
        }
        Section {
          DisclosureGroup("View Full Instructions") {
            Text(detail.instructions).textSelection(.enabled).padding(.vertical, 6)
          }
        }
        Section {
          if detail.editable {
            Button("Edit Skill", systemImage: "pencil") { model.sheet = .skillEditor(id) }
          }
          if let shareURL {
            ShareLink(item: shareURL) { Label("Share Skill", systemImage: "square.and.arrow.up") }
          } else {
            Button("Create Share Link", systemImage: "link") { share() }
          }
        }
      } else if let loadError {
        ContentUnavailableView {
          Label("Couldn’t Load Skill", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      } else {
        ProgressView().frame(maxWidth: .infinity)
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .navigationTitle(detail?.name ?? "Skill")
    .task { await load() }
  }

  private func load() async {
    do {
      detail = try await model.requireAPI().skill(id)
      loadError = nil
    } catch {
      loadError = error.localizedDescription
    }
  }

  private func share() {
    Task {
      do { shareURL = try await model.requireAPI().shareSkill(id) } catch { model.present(error) }
    }
  }

  private func capabilityName(_ id: String) -> String {
    id.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
  }
}
