import SwiftUI

public struct FeatureSheet: View {
  let sheet: AppSheet
  @Bindable var model: AppModel
  let auth: AuthSession
  public var body: some View {
    FeatureNavigation {
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
    .froggySheetNavigation()
    #if os(iOS)
      .froggySheetSize()
    #endif
    .tint(FrogTheme.accent)
  }
}

/// Use one stack per Mac column to preserve editor state when popping a page.
/// Separately presented sheets on iPhone need their own stack.
struct FeatureNavigation<Content: View>: View {
  @ViewBuilder let content: () -> Content

  var body: some View {
    #if os(macOS)
      content()
    #else
      NavigationStack { content() }
    #endif
  }
}

/// Transient, value-based routes let the Mac sidebar clear nested pages as
/// well as the feature root. Destination-based links aren't in NavigationPath.
struct FeatureDestination: Hashable {
  let id: UUID
  let content: @MainActor () -> AnyView

  static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id }
  func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct FeatureLink<Destination: View, Label: View>: View {
  @ViewBuilder let destination: () -> Destination
  @ViewBuilder let label: () -> Label
  @State private var id = UUID()

  var body: some View {
    #if os(macOS)
      NavigationLink(
        value: FeatureDestination(id: id, content: { AnyView(destination()) }), label: label)
    #else
      NavigationLink(destination: destination, label: label)
    #endif
  }
}

struct CloseButton: ToolbarContent {
  @Environment(\.dismiss) private var dismiss
  @Environment(\.froggyUsesSheetNavigation) private var usesSheetNavigation
  private let action: (() -> Void)?

  init(action: (() -> Void)? = nil) {
    self.action = action
  }

  var body: some ToolbarContent {
    #if os(macOS)
      if usesSheetNavigation {
        ToolbarItem(placement: .navigation) { button }
      } else {
        ToolbarItem(placement: .primaryAction) { button }
      }
    #else
      ToolbarItem(placement: .cancellationAction) { button }
    #endif
  }

  @ViewBuilder private var button: some View {
    #if os(macOS)
      if usesSheetNavigation {
        Button("Back", systemImage: "chevron.backward", action: close)
          .labelStyle(.iconOnly)
          .accessibilityIdentifier("sheet.close")
          .help("Back to chat")
      } else {
        Button("Close", systemImage: "xmark", action: close)
          .labelStyle(.iconOnly)
          .accessibilityIdentifier("sheet.close")
      }
    #else
      Button("Close", systemImage: "xmark", action: close)
        .labelStyle(.iconOnly)
        .accessibilityIdentifier("sheet.close")
    #endif
  }

  private func close() {
    if let action {
      action()
    } else {
      dismiss()
    }
  }
}

struct GuidedTextEditor: View {
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

struct BotColorOption: Identifiable, Sendable {
  let value: String
  let name: String
  var id: String { value }
}

private struct ScheduleWeekday: Identifiable, Sendable {
  let id: String
  let name: String
}

let customBotColors = [
  BotColorOption(value: "#58BEAA", name: "Teal"),
  BotColorOption(value: "#FFAA34", name: "Gold"),
  BotColorOption(value: "#6C5CE7", name: "Purple"),
  BotColorOption(value: "#3984F6", name: "Blue"),
  BotColorOption(value: "#F46A27", name: "Orange"),
  BotColorOption(value: "#E95383", name: "Pink"),
]

struct BotColorPicker: View {
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
                .froggyFont(.caption, weight: .bold)
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
  var showsDismissButton = true
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
        FeatureLink {
          BotEditor(model: model, id: nil, showsDismissButton: false)
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
    .froggyNavigationTitle("Add a Bot")
    .toolbarTitleDisplayMode(.inline)
    .searchable(text: $search, prompt: "Search templates")
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
    }
  }

  private func templateLink(_ template: BotTemplate) -> some View {
    FeatureLink {
      BotTemplateDetailView(model: model, template: template)
    } label: {
      HStack(spacing: 12) {
        BotAvatar(name: template.name, color: template.color)
        VStack(alignment: .leading, spacing: 4) {
          HStack {
            Text(template.name).froggyFont(.headline)
            if isInstalled(template) {
              Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(FrogTheme.accent)
                .accessibilityLabel("Added")
            }
          }
          Text(template.tagline).froggyFont(.subheadline).foregroundStyle(.secondary).lineLimit(2)
          HStack(spacing: 12) {
            Label(countLabel(template.skillIds.count, singular: "skill"), systemImage: "sparkles")
            Label(countLabel(effectiveToolCount(template), singular: "tool"), systemImage: "wrench.and.screwdriver")
          }
          .froggyFont(.caption)
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
            Text(template.name).froggyFont(.title2, weight: .bold)
            Text(template.tagline).foregroundStyle(.secondary)
            if let category = template.category {
              Text(category).froggyFont(.caption).foregroundStyle(FrogTheme.accent)
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
                Text(skill.description).froggyFont(.caption).foregroundStyle(.secondary)
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
                  Text(description).froggyFont(.caption).foregroundStyle(.secondary)
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
            .froggyFont(.callout)
            .textSelection(.enabled)
            .padding(.vertical, 6)
        }
      } footer: {
        Text("You can edit the bot after adding it. Connected accounts are never added automatically.")
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle(template.name)
    .toolbarTitleDisplayMode(.inline)
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
  var showsDismissButton = true
  @State private var draft = BotDraft()
  @State private var saving = false
  @State private var loadedDraft = false
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

  private var selectedSkillCount: Int { draft.skillIds.count }

  private var effectiveToolCount: Int {
    let selectedSkillIDs = Set(draft.skillIds)
    let requiredToolIDs = (model.bootstrap?.skills ?? []).lazy
      .filter { selectedSkillIDs.contains($0.id) }
      .flatMap(\.requiredToolIds)
    return Set(draft.toolIds).union(requiredToolIDs).count
  }

  var body: some View {
    Form {
      Section {
        TextField("Name", text: $draft.name)
          .accessibilityLabel("Name")
        TextField("Description", text: $draft.tagline)
          .accessibilityLabel("What this bot does")
        VStack(alignment: .leading, spacing: 4) {
          Text("Color").froggyFont(.subheadline)
          BotColorPicker(selection: $draft.color, options: colorOptions)
        }
      } header: {
        Text("Identity")
      } footer: {
        Text(
          identityIssue ?? "Use a short name and a one-line description people can scan quickly."
        )
          .foregroundStyle(
            identityIssue == nil || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              ? Color.secondary : Color.red)
      }
      Section {
        FeatureLink {
          BotPromptEditor(
            prompt: $draft.prompt,
            maximumLength: model.constraints.botPromptMaxLength)
        } label: {
          VStack(alignment: .leading, spacing: 6) {
            Label("Edit Prompt", systemImage: "text.alignleft")
              .froggyFont(.headline)
            Text(
              draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "Add the bot’s role, tone, boundaries, and definition of success."
                : draft.prompt
            )
            .froggyFont(.callout)
            .foregroundStyle(.secondary)
            .lineLimit(4)
          }
          .padding(.vertical, 4)
        }
        .accessibilityIdentifier("bot.prompt.editor")
      } header: {
        Text("Prompt")
      } footer: {
        HStack(alignment: .firstTextBaseline) {
          Text(
            instructionsIssue ?? "Opens a dedicated editor so you can work with the full prompt."
          )
          Spacer(minLength: 12)
          Text(
            "\(draft.prompt.count.formatted()) / \(model.constraints.botPromptMaxLength.formatted())"
          )
            .monospacedDigit()
        }
        .foregroundStyle(
          instructionsIssue == nil || draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? Color.secondary : Color.red)
      }

      Section {
        FeatureLink {
          BotToolsAndSkillsEditor(
            model: model, draft: $draft,
            skills: model.bootstrap?.skills ?? [],
            tools: model.bootstrap?.tools ?? [],
            providers: model.bootstrap?.connectionProviders ?? [])
        } label: {
          Label {
            VStack(alignment: .leading, spacing: 3) {
              Text("Tools & Skills")
              Text(
                "\(selectedSkillCount) \(selectedSkillCount == 1 ? "skill" : "skills") · \(effectiveToolCount) \(effectiveToolCount == 1 ? "tool" : "tools")"
              )
              .froggyFont(.caption)
              .foregroundStyle(.secondary)
            }
          } icon: {
            Image(systemName: "wrench.and.screwdriver")
          }
        }
        .accessibilityIdentifier("bot.tools-and-skills")
      } footer: {
        Text("Choose optional playbooks and the actions this bot can use.")
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle(id == nil ? "New bot" : "Edit bot")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      ToolbarItem(placement: .confirmationAction) {
        Button("Save") { save() }.disabled(!canSave)
      }
    }
    .onAppear {
      guard !loadedDraft else { return }
      loadedDraft = true
      if let bot = editingBot {
        draft = BotDraft(bot: bot)
      }
    }
  }

  private func save() {
    saving = true
    Task {
      if await model.saveBot(draft, id: id) {
        if showsDismissButton { model.sheet = nil } else { dismiss() }
      }
      saving = false
    }
  }
}

struct BotPromptEditor: View {
  @Binding var prompt: String
  let maximumLength: Int
  @Environment(\.dismiss) private var dismiss

  private var issue: String? {
    if prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Add instructions so the bot knows how to help."
    }
    if prompt.count > maximumLength {
      return "The prompt is longer than the supported limit."
    }
    return nil
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Describe the bot’s role, tone, boundaries, and what a successful answer looks like.")
        .froggyFont(.callout)
        .foregroundStyle(.secondary)
      GuidedTextEditor(
        title: "Bot prompt",
        prompt: "Help people… Always include… Never… Keep responses…",
        text: $prompt,
        minHeight: 420)
        .froggyFont(.body)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
      HStack(alignment: .firstTextBaseline) {
        Text(issue ?? "This prompt is active for every reply from this bot.")
        Spacer(minLength: 12)
        Text("\(prompt.count.formatted()) / \(maximumLength.formatted())")
          .monospacedDigit()
      }
      .froggyFont(.caption)
      .foregroundStyle(issue == nil ? Color.secondary : Color.red)
    }
    .padding(20)
    .background(FrogTheme.pageBackground)
    .froggyNavigationTitle("Bot Prompt")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      ToolbarItem(placement: .confirmationAction) {
        Button("Done") { dismiss() }
      }
    }
  }
}

struct BotToolsAndSkillsEditor: View {
  @Bindable var model: AppModel
  @Binding var draft: BotDraft
  let skills: [Skill]
  let tools: [Capability]
  let providers: [ConnectionProvider]

  private var requiredByTool: [String: [String]] {
    var result: [String: [String]] = [:]
    for skill in skills where draft.skillIds.contains(skill.id) {
      for toolID in skill.requiredToolIds {
        result[toolID, default: []].append(skill.name)
      }
    }
    return result
  }

  private var alwaysAllowedTools: [Capability] {
    revocableAlwaysAllowedTools(tools: tools, skills: skills, draft: draft)
  }

  private var providerToolGroups: (
    groups: [ConnectionProviderToolGroup], ungrouped: [Capability]
  ) {
    connectionProviderToolGroups(tools: tools, providers: providers)
  }

  var body: some View {
    Form {
      Section {
        Text(
          "Skills are playbooks the bot can activate when a request matches. Tools are actions it can call when needed."
        )
        .froggyFont(.callout)
        .foregroundStyle(.secondary)
      }

      Section("Skills") {
        ForEach(skills) { skill in
          capabilityToggle(
            id: skill.id,
            name: skill.name,
            description: skill.description,
            values: $draft.skillIds)
        }
        if skills.isEmpty {
          ContentUnavailableView("No Skills", systemImage: "sparkles")
        }
      }

      Section("Tools") {
        ForEach(providerToolGroups.groups) { group in
          ForEach(includedTools(in: group)) { tool in
            toolToggle(tool)
          }
          ForEach(group.family.providers) { provider in
            let providerTools = connectedTools(for: provider, in: group)
            if providerTools.isEmpty {
              connectionLink(provider)
            } else {
              ForEach(providerTools) { tool in
                toolToggle(tool, name: provider.name)
              }
            }
          }
        }
        ForEach(providerToolGroups.ungrouped) { tool in
          toolToggle(tool)
        }
        if tools.isEmpty && providerToolGroups.groups.isEmpty {
          ContentUnavailableView("No Tools", systemImage: "wrench.and.screwdriver")
        }
      }

      if !alwaysAllowedTools.isEmpty {
        Section {
          ForEach(alwaysAllowedTools) { tool in
            capabilityToggle(
              id: tool.id,
              name: tool.name,
              description: tool.description,
              values: $draft.alwaysAllowedToolIds)
          }
        } header: {
          Text("Always allowed in direct chats")
        } footer: {
          Text("Turn one off to require approval again. Groups and schedules still require supervision.")
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle("Tools & Skills")
    .toolbarTitleDisplayMode(.inline)
  }

  @ViewBuilder private func capabilityToggle(
    id: String, name: String, description: String, values: Binding<[String]>
  ) -> some View {
    Toggle(
      isOn: Binding(
        get: { values.wrappedValue.contains(id) },
        set: { enabled in set(enabled, id: id, in: &values.wrappedValue) })
    ) {
      VStack(alignment: .leading, spacing: 3) {
        Text(name)
        Text(description).froggyFont(.caption).foregroundStyle(.secondary)
      }
    }
  }

  @ViewBuilder private func toolToggle(_ tool: Capability, name: String? = nil) -> some View {
    let requiredBy = requiredByTool[tool.id] ?? []
    Toggle(
      isOn: Binding(
        get: { requiredBy.isEmpty ? draft.toolIds.contains(tool.id) : true },
        set: { enabled in
          guard requiredBy.isEmpty else { return }
          set(enabled, id: tool.id, in: &draft.toolIds)
        })
    ) {
      HStack(spacing: 10) {
        toolIcon(tool)
        VStack(alignment: .leading, spacing: 3) {
          Text(name ?? tool.name)
          Text(tool.description).froggyFont(.caption).foregroundStyle(.secondary)
          if !requiredBy.isEmpty {
            Text("Required by \(requiredBy.joined(separator: ", "))")
              .froggyFont(.caption2, weight: .semibold)
              .foregroundStyle(FrogTheme.accent)
          }
        }
      }
    }
    .disabled(!requiredBy.isEmpty)
  }

  private func includedTools(in group: ConnectionProviderToolGroup) -> [Capability] {
    let providerIDs = Set(group.family.providers.map(\.id))
    return group.tools.filter { tool in
      tool.provider.map(providerIDs.contains) != true
    }
  }

  private func connectedTools(
    for provider: ConnectionProvider, in group: ConnectionProviderToolGroup
  ) -> [Capability] {
    group.tools.filter { $0.provider == provider.id }
  }

  private func connectionLink(_ provider: ConnectionProvider) -> some View {
    FeatureLink {
      ConnectionsView(model: model, showsDismissButton: false)
    } label: {
      HStack(spacing: 10) {
        connectionIcon(provider)
        VStack(alignment: .leading, spacing: 3) {
          Text(provider.name)
          Text(provider.description)
            .froggyFont(.caption)
            .foregroundStyle(.secondary)
        }
        Spacer(minLength: 8)
        Text("Connect")
          .froggyFont(.caption, weight: .semibold)
          .foregroundStyle(FrogTheme.accent)
      }
    }
    .accessibilityIdentifier("bot.connection.\(provider.id)")
    .accessibilityHint("Opens Connected Accounts")
  }

  @ViewBuilder private func connectionIcon(_ provider: ConnectionProvider) -> some View {
    if let family = providerFamily(for: provider) {
      ProviderLogoView(
        providerID: family.logoProviderId, iconText: family.iconText, size: 30)
    } else {
      ProviderLogoView(provider: provider, size: 30)
    }
  }

  @ViewBuilder private func toolIcon(_ tool: Capability) -> some View {
    if let family = providerFamily(for: tool) {
      ProviderLogoView(
        providerID: family.logoProviderId, iconText: family.iconText, size: 30)
    } else if let provider = providers.first(where: { $0.id == tool.provider }) {
      ProviderLogoView(provider: provider, size: 30)
    } else {
      Image(systemName: toolSymbol(tool))
        .froggyFont(.body, weight: .semibold)
        .foregroundStyle(FrogTheme.accent)
        .frame(width: 30, height: 30)
        .background(
          FrogTheme.accent.opacity(0.10),
          in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityHidden(true)
    }
  }

  private func providerFamily(for tool: Capability) -> ConnectionProviderFamily? {
    connectionProviderFamilies(providers).first { family in
      family.includedToolIDs.contains(tool.id)
        || tool.provider.map(Set(family.providers.map(\.id)).contains) == true
    }
  }

  private func providerFamily(for provider: ConnectionProvider) -> ConnectionProviderFamily? {
    guard let familyID = provider.familyId else { return nil }
    return connectionProviderFamilies(providers).first { $0.id == familyID }
  }

  private func toolSymbol(_ tool: Capability) -> String {
    let identity = "\(tool.id) \(tool.name)".lowercased()
    if identity.contains("image") || identity.contains("thumbnail") { return "photo" }
    if identity.contains("browser") { return "globe" }
    if identity.contains("list") || identity.contains("task") { return "checklist" }
    if identity.contains("web") || identity.contains("search") { return "magnifyingglass" }
    if identity.contains("file") || identity.contains("data")
      || identity.contains("code_interpreter")
    {
      return "doc.text"
    }
    if identity.contains("time") || identity.contains("clock") { return "clock" }
    if identity.contains("calculator") { return "function" }
    if identity.contains("memory") { return "brain.head.profile" }
    return "wrench.and.screwdriver"
  }

  private func set(_ enabled: Bool, id: String, in values: inout [String]) {
    if enabled {
      if !values.contains(id) { values.append(id) }
    } else {
      values.removeAll { $0 == id }
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

struct GroupEditor: View {
  @Bindable var model: AppModel
  let id: String?
  var showsDismissButton = true
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
              Text("Saved by \(decision.createdByName)").froggyFont(.caption).foregroundStyle(.secondary)
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
    .froggyNavigationTitle(id == nil ? "New group" : "Edit group")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
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
      if await model.saveGroup(draft, id: id) {
        if showsDismissButton { model.sheet = nil } else { dismiss() }
      }
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

struct SchedulesView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  var showsDismissButton = true
  @State private var schedules: [ScheduledTask] = []
  @State private var editing: ScheduledTask?
  @State private var creating = false
  @State private var runningID: String?
  @State private var deleteCandidate: ScheduledTask?
  @State private var isLoading = false
  @State private var loadError: String?
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
                  .froggyFont(.caption)
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
    }
    .froggyListSurface()
    .froggyNavigationTitle("Scheduled tasks")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      ToolbarItem(placement: .primaryAction) {
        Button("New", systemImage: "plus") { creating = true }
      }
    }
    .overlay {
      if isLoading && schedules.isEmpty {
        ProgressView("Loading scheduled tasks…")
      } else if let loadError, schedules.isEmpty {
        ContentUnavailableView {
          Label("Couldn’t Load Scheduled Tasks", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      } else if schedules.isEmpty {
        ContentUnavailableView(
          "No Scheduled Tasks", systemImage: "calendar.badge.plus",
          description: Text("Create a task to have this conversation run automatically."))
      }
    }
    .refreshable { await load() }
    .task { await load() }
    .navigationDestination(isPresented: $creating) {
      ScheduleEditor(model: model, selection: selection, existing: nil) { await load() }
    }
    .navigationDestination(item: $editing) { task in
      ScheduleEditor(model: model, selection: selection, existing: task) { await load() }
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
    isLoading = true
    defer { isLoading = false }
    guard let api = model.api else {
      loadError = nil
      return
    }
    do {
      schedules = try await api.schedules(for: selection)
      loadError = nil
    } catch {
      if schedules.isEmpty {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
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
    .froggyNavigationTitle(existing == nil ? "New task" : "Edit task")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
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

struct ScheduleRunsView: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  var showsDismissButton = true
  @State private var runs: [ScheduleRun] = []
  @State private var isLoading = false
  @State private var loadError: String?
  var body: some View {
    List {
      ForEach(runs) { run in
        VStack(alignment: .leading, spacing: 6) {
          HStack {
            Text(run.scheduleName).froggyFont(.headline)
            Spacer()
            Text(run.status.capitalized).foregroundStyle(
              run.status == "complete" ? FrogTheme.green : .secondary)
          }
          Text(run.prompt).lineLimit(2)
          if let output = run.output {
            Text(output).froggyFont(.callout).foregroundStyle(.secondary).lineLimit(5)
          }
        }
      }
    }
    .froggyListSurface()
    .froggyNavigationTitle("Run history")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
    }
    .overlay {
      if isLoading && runs.isEmpty {
        ProgressView("Loading run history…")
      } else if let loadError, runs.isEmpty {
        ContentUnavailableView {
          Label("Couldn’t Load Run History", systemImage: "wifi.exclamationmark")
        } description: {
          Text(loadError)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      } else if runs.isEmpty {
        ContentUnavailableView(
          "No Runs Yet", systemImage: "clock.arrow.circlepath",
          description: Text("Completed and in-progress scheduled task runs will appear here."))
      }
    }
    .refreshable { await load() }
    .task { await load() }
  }

  private func load() async {
    isLoading = true
    defer { isLoading = false }
    guard let api = model.api else {
      loadError = nil
      return
    }
    do {
      runs = try await api.scheduleRuns(for: selection)
      loadError = nil
    } catch {
      if runs.isEmpty {
        loadError = error.localizedDescription
      } else {
        model.present(error)
      }
    }
  }
}

enum MemoryUsageState: Equatable {
  case allBots
  case bot(String)
  case group
  case unused

  var isInUse: Bool { self != .unused }

  var label: String {
    switch self {
    case .allBots: "Available to every bot"
    case .bot(let name): "Available to \(name)"
    case .group: "Available in this group"
    case .unused: "Not in use · original bot removed"
    }
  }

  var systemImage: String {
    switch self {
    case .allBots: "person.2.fill"
    case .bot: "bubble.left.and.sparkles.fill"
    case .group: "person.3.fill"
    case .unused: "archivebox"
    }
  }
}

func memoryUsageState(for record: MemoryRecord, groupID: String?) -> MemoryUsageState {
  if groupID != nil || record.scope == "group" { return .group }
  guard record.kind == "summary" else { return .allBots }
  guard let botName = record.botName?.trimmingCharacters(in: .whitespacesAndNewlines),
    !botName.isEmpty
  else {
    return record.botId == nil ? .unused : .bot("its original bot")
  }
  return .bot(botName)
}

private enum MemoryFilter: String, CaseIterable, Identifiable {
  case all
  case inUse
  case cleanup
  case facts
  case preferences
  case summaries

  var id: Self { self }

  var title: String {
    switch self {
    case .all: "All"
    case .inUse: "In Use"
    case .cleanup: "Cleanup"
    case .facts: "Facts"
    case .preferences: "Preferences"
    case .summaries: "Summaries"
    }
  }

  func includes(_ record: MemoryRecord, usage: MemoryUsageState) -> Bool {
    switch self {
    case .all: true
    case .inUse: usage.isInUse
    case .cleanup: !usage.isInUse
    case .facts: record.kind == "fact"
    case .preferences: record.kind == "preference"
    case .summaries: record.kind == "summary"
    }
  }
}

private struct MemoryListSection: Identifiable {
  let id: String
  let title: String
  let detail: String
  let records: [MemoryRecord]
}

struct MemoriesView: View {
  @Bindable var model: AppModel
  let groupId: String?
  var showsDismissButton = true
  @State private var snapshot: MemorySnapshot?
  @State private var newMemory = ""
  @State private var newKind = "fact"
  @State private var editingID: String?
  @State private var editingText = ""
  @State private var loading = true
  @State private var loadError: String?
  @State private var search = ""
  @State private var filter = MemoryFilter.all
  @State private var selecting = false
  @State private var selectedIDs: Set<String> = []
  @State private var savingNewMemory = false
  @State private var busyMemoryIDs: Set<String> = []
  @State private var forgetCandidates: [MemoryRecord] = []

  private var editable: Bool {
    guard let groupId else { return true }
    return model.bootstrap?.groups.first(where: { $0.id == groupId })?.allowedActions?.contains(
      "manageMemory") == true
  }

  private var maximumLength: Int { model.bootstrap?.constraints.memoryMaxLength ?? 16_000 }
  private var records: [MemoryRecord] { snapshot?.records ?? [] }
  private var trimmedNewMemory: String {
    newMemory.trimmingCharacters(in: .whitespacesAndNewlines)
  }

  private var inUseRecords: [MemoryRecord] {
    records.filter { memoryUsageState(for: $0, groupID: groupId).isInUse }
  }

  private var cleanupRecords: [MemoryRecord] {
    records.filter { !memoryUsageState(for: $0, groupID: groupId).isInUse }
  }

  private var filteredRecords: [MemoryRecord] {
    let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
    return records.filter { record in
      let usage = memoryUsageState(for: record, groupID: groupId)
      guard filter.includes(record, usage: usage) else { return false }
      guard !query.isEmpty else { return true }
      return [record.content, record.kind, record.source, record.botName ?? "", usage.label]
        .contains { $0.localizedCaseInsensitiveContains(query) }
    }
  }

  private var sections: [MemoryListSection] {
    if groupId != nil {
      return section(
        id: "group", title: "Available in This Group",
        detail: "These can be recalled by every bot participating here.",
        records: filteredRecords)
    }
    let allBots = filteredRecords.filter { $0.kind != "summary" }
    let botSummaries = filteredRecords.filter {
      if case .bot = memoryUsageState(for: $0, groupID: nil) { return true }
      return false
    }
    let unused = filteredRecords.filter {
      memoryUsageState(for: $0, groupID: nil) == .unused
    }
    return section(
      id: "all-bots", title: "Available to Every Bot",
      detail: "Personal facts and preferences are searched when any bot might need them.",
      records: allBots)
      + section(
        id: "bot-summaries", title: "Bot Conversation Summaries",
        detail: "Each summary is available only to the bot named on it.",
        records: botSummaries)
      + section(
        id: "cleanup", title: "Ready for Cleanup",
        detail: "These summaries belonged to bots that no longer exist and are not recalled.",
        records: unused)
  }

  var body: some View {
    List {
      if let snapshot {
        overview(snapshot)
      }

      if editable && !selecting && snapshot != nil {
        addMemorySection
      }

      if loading && snapshot == nil {
        Section {
          HStack {
            Spacer()
            ProgressView()
            Spacer()
          }
        }
      } else if let loadError, snapshot == nil {
        Section {
          ContentUnavailableView {
            Label("Couldn’t Load Memory", systemImage: "wifi.exclamationmark")
          } description: {
            Text(loadError)
          } actions: {
            Button("Try Again") { Task { await load() } }
          }
        }
      } else if records.isEmpty {
        Section {
          ContentUnavailableView(
            "Nothing Remembered Yet", systemImage: "brain.head.profile",
            description: Text(
              "Facts and preferences you add or ask FroggyBot to remember will appear here."))
        }
      } else if filteredRecords.isEmpty {
        Section {
          ContentUnavailableView(
            filter == .cleanup ? "Nothing to Clean Up" : "No Matching Memories",
            systemImage: filter == .cleanup ? "checkmark.circle" : "magnifyingglass",
            description: Text(
              filter == .cleanup
                ? "Every saved memory is still connected to an active bot or group."
                : "Try another search or choose a different filter."))
        }
      } else {
        ForEach(sections) { section in
          Section {
            ForEach(section.records) { record in
              memoryRow(record)
            }
          } header: {
            HStack(alignment: .firstTextBaseline) {
              Text(section.title)
              Spacer()
              Text(section.records.count.formatted()).monospacedDigit()
            }
          } footer: {
            Text(section.detail)
          }
        }
      }

      if let snapshot {
        Section("How Memory Works") {
          Text("In-use memories are searched for relevance; they are not all added to every reply.")
          Text(
            "Raw conversation history expires after \(snapshot.rawConversationRetentionDays) days. The memories listed here remain until you edit or forget them."
          )
        }
        .froggyFont(.footnote)
      }
    }
    .froggyListSurface()
    .froggyNavigationTitle(groupId == nil ? "Memory" : "Group Memory")
    .toolbarTitleDisplayMode(.inline)
    .searchable(text: $search, prompt: "Search memories")
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      ToolbarItemGroup(placement: .confirmationAction) {
        if !records.isEmpty {
          Menu {
            Picker("Show", selection: $filter) {
              ForEach(MemoryFilter.allCases) { option in
                Text(option.title).tag(option)
              }
            }
          } label: {
            Label("Filter: \(filter.title)", systemImage: "line.3.horizontal.decrease.circle")
          }
          .help("Filter memories")
        }
        if editable && !records.isEmpty {
          Button(selecting ? "Done" : "Select") {
            selecting.toggle()
            selectedIDs.removeAll()
            editingID = nil
            editingText = ""
          }
        }
      }
    }
    .safeAreaInset(edge: .bottom, spacing: 0) {
      if selecting {
        selectionBar
      }
    }
    .refreshable { await load() }
    .task { await load() }
    .confirmationDialog(
      forgetCandidates.count == 1
        ? "Forget this memory?" : "Forget \(forgetCandidates.count) memories?",
      isPresented: Binding(
        get: { !forgetCandidates.isEmpty },
        set: { if !$0 { forgetCandidates = [] } }),
      titleVisibility: .visible
    ) {
      if !forgetCandidates.isEmpty {
        Button(
          forgetCandidates.count == 1 ? "Forget Memory" : "Forget Selected Memories",
          role: .destructive
        ) {
          remove(forgetCandidates)
        }
      }
      Button("Cancel", role: .cancel) { forgetCandidates = [] }
    } message: {
      Text(
        forgetCandidates.count == 1
          ? "FroggyBot will stop using this information in future conversations."
          : "This permanently removes the selected memories. This cannot be undone."
      )
    }
  }

  @ViewBuilder private func overview(_ snapshot: MemorySnapshot) -> some View {
    Section {
      LabeledContent("In use", value: inUseRecords.count.formatted())
      if groupId == nil {
        LabeledContent(
          "Available to every bot",
          value: records.filter { $0.kind != "summary" }.count.formatted())
        LabeledContent(
          "Bot-only summaries",
          value: records.filter {
            if case .bot = memoryUsageState(for: $0, groupID: nil) { return true }
            return false
          }.count.formatted())
        if !cleanupRecords.isEmpty {
          Button("Review \(cleanupRecords.count) unused summaries", systemImage: "archivebox") {
            filter = .cleanup
            search = ""
          }
          .foregroundStyle(.orange)
        }
      }
    } header: {
      Text("At a Glance")
    } footer: {
      Text(
        groupId == nil
          ? "“In use” means the memory can be recalled when it is relevant, not that it is sent with every message."
          : "Every listed record can be recalled by bots in this group when it is relevant."
      )
    }
  }

  @ViewBuilder private var addMemorySection: some View {
    Section {
      if groupId == nil {
        Picker("Kind", selection: $newKind) {
          Text("Fact").tag("fact")
          Text("Preference").tag("preference")
        }
        .pickerStyle(.segmented)
      }
      HStack {
        TextField(
          groupId == nil ? "Add a fact or preference" : "Add group context",
          text: $newMemory)
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
        .froggyFont(.caption)
      }
    } header: {
      Text("Add Memory")
    } footer: {
      Text(
        groupId == nil
          ? "Facts and preferences are available to every bot."
          : "New group memories are available to every bot in this group."
      )
    }
  }

  @ViewBuilder private func memoryRow(_ record: MemoryRecord) -> some View {
    if editingID == record.id {
      VStack(alignment: .leading, spacing: 8) {
        TextField("Memory text", text: $editingText, axis: .vertical)
          .lineLimit(3...12)
        HStack {
          Button("Cancel") {
            editingID = nil
            editingText = ""
          }
          Spacer()
          Text("\(editingText.count.formatted()) / \(maximumLength.formatted())")
            .froggyFont(.caption)
            .foregroundStyle(editingText.count > maximumLength ? .red : .secondary)
          Button("Save") { update(record) }
            .disabled(
              editingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || editingText.count > maximumLength || !busyMemoryIDs.isEmpty)
        }
      }
    } else if selecting {
      Button {
        toggleSelection(record.id)
      } label: {
        HStack(alignment: .top, spacing: 12) {
          Image(systemName: selectedIDs.contains(record.id) ? "checkmark.circle.fill" : "circle")
            .froggyFont(.title3)
            .foregroundStyle(selectedIDs.contains(record.id) ? FrogTheme.accent : .secondary)
          memorySummary(record)
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel(
        "\(selectedIDs.contains(record.id) ? "Deselect" : "Select") memory: \(record.content)"
      )
    } else {
      HStack(alignment: .top, spacing: 12) {
        memorySummary(record)
        if editable {
          HStack(spacing: 4) {
            Button("Edit memory", systemImage: "pencil") { beginEditing(record) }
              .labelStyle(.iconOnly)
              .help("Edit memory")
            Button("Forget memory", systemImage: "trash", role: .destructive) {
              forgetCandidates = [record]
            }
            .labelStyle(.iconOnly)
            .help("Forget memory")
          }
          .buttonStyle(.borderless)
          .disabled(!busyMemoryIDs.isEmpty)
        }
      }
      .opacity(busyMemoryIDs.contains(record.id) ? 0.5 : 1)
      .swipeActions(edge: .trailing, allowsFullSwipe: false) {
        if editable {
          Button("Forget", role: .destructive) { forgetCandidates = [record] }
          Button("Edit") { beginEditing(record) }.tint(FrogTheme.green)
        }
      }
      .contextMenu {
        if editable {
          Button("Edit Memory", systemImage: "pencil") { beginEditing(record) }
          Button("Forget Memory", systemImage: "trash", role: .destructive) {
            forgetCandidates = [record]
          }
        }
      }
    }
  }

  private func memorySummary(_ record: MemoryRecord) -> some View {
    let usage = memoryUsageState(for: record, groupID: groupId)
    return VStack(alignment: .leading, spacing: 6) {
      Text(record.content)
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
      Label(usage.label, systemImage: usage.systemImage)
        .froggyFont(.caption, weight: .semibold)
        .foregroundStyle(usage.isInUse ? FrogTheme.accent : Color.orange)
      Text(memoryMetadata(record))
        .froggyFont(.caption2)
        .foregroundStyle(.secondary)
    }
  }

  private var selectionBar: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 12) {
        selectionControls
      }
      VStack(spacing: 8) {
        selectionControls
      }
    }
    .padding(12)
    .background(.bar)
  }

  @ViewBuilder private var selectionControls: some View {
    if !cleanupRecords.isEmpty && groupId == nil {
      Button("Select Unused") {
        selectedIDs = Set(cleanupRecords.map(\.id))
      }
    }
    Spacer(minLength: 8)
    Text("\(selectedIDs.count) selected")
      .froggyFont(.caption)
      .foregroundStyle(.secondary)
    Button("Forget Selected", role: .destructive) {
      forgetCandidates = records.filter { selectedIDs.contains($0.id) }
    }
    .disabled(selectedIDs.isEmpty || !busyMemoryIDs.isEmpty)
  }

  private func section(
    id: String, title: String, detail: String, records: [MemoryRecord]
  ) -> [MemoryListSection] {
    records.isEmpty
      ? []
      : [MemoryListSection(id: id, title: title, detail: detail, records: records)]
  }

  private func memoryMetadata(_ record: MemoryRecord) -> String {
    let kind: String
    switch record.kind {
    case "fact": kind = "Fact"
    case "preference": kind = "Preference"
    case "summary": kind = "Conversation summary"
    default: kind = record.kind.capitalized
    }
    let source = record.source == "manual" ? "Added by you" : "Learned from conversation"
    let date = record.createdAt.froggyDate?.formatted(date: .abbreviated, time: .omitted)
    return [kind, source, date].compactMap { $0 }.joined(separator: " · ")
  }

  private func beginEditing(_ record: MemoryRecord) {
    editingID = record.id
    editingText = record.content
  }

  private func toggleSelection(_ id: String) {
    if selectedIDs.contains(id) {
      selectedIDs.remove(id)
    } else {
      selectedIDs.insert(id)
    }
  }

  private func load() async {
    loading = true
    defer { loading = false }
    do {
      snapshot = try await model.requireAPI().memories(groupId: groupId)
      loadError = nil
      selectedIDs.formIntersection(Set(records.map(\.id)))
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
        let created = try await model.requireAPI().createMemory(
          kind: newKind, content: content, groupId: groupId)
        snapshot?.records.insert(created, at: 0)
        newMemory = ""
      } catch { model.present(error) }
    }
  }

  private func update(_ record: MemoryRecord) {
    let content = editingText.trimmingCharacters(in: .whitespacesAndNewlines)
    busyMemoryIDs.insert(record.id)
    Task {
      defer { busyMemoryIDs.remove(record.id) }
      do {
        let updated = try await model.requireAPI().updateMemory(
          id: record.id, content: content, groupId: groupId)
        if let index = snapshot?.records.firstIndex(where: { $0.id == record.id }) {
          snapshot?.records[index] = updated
        }
        editingID = nil
        editingText = ""
      } catch { model.present(error) }
    }
  }

  private func remove(_ candidates: [MemoryRecord]) {
    let ids = Set(candidates.map(\.id))
    forgetCandidates = []
    busyMemoryIDs.formUnion(ids)
    Task {
      var deletedIDs: Set<String> = []
      do {
        for id in ids {
          try await model.requireAPI().deleteMemory(id: id, groupId: groupId)
          deletedIDs.insert(id)
        }
      } catch {
        model.present(error)
      }
      snapshot?.records.removeAll { deletedIDs.contains($0.id) }
      busyMemoryIDs.subtract(ids)
      selectedIDs.subtract(deletedIDs)
      if selectedIDs.isEmpty && deletedIDs == ids { selecting = false }
    }
  }
}

private struct SkillEditorDestination: Identifiable, Hashable {
  let skillID: String?
  var id: String { skillID ?? "new" }
}

struct SkillsView: View {
  @Bindable var model: AppModel
  var showsDismissButton = true
  @State private var selection = CapabilityLibrarySection.skills
  @State private var editor: SkillEditorDestination?

  private enum CapabilityLibrarySection: String, CaseIterable, Identifiable {
    case skills = "Skills"
    case tools = "Tools"
    var id: Self { self }
  }

  var body: some View {
    List {
      Section {
        Picker("Tools and skills", selection: $selection) {
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
            FeatureLink {
              SkillDetailView(
                model: model, id: skill.id,
                edit: { editor = SkillEditorDestination(skillID: skill.id) })
            } label: {
              VStack(alignment: .leading, spacing: 3) {
                HStack {
                  Text(skill.name).froggyFont(.headline)
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
            FeatureLink {
              CapabilityDetailView(capability: tool)
            } label: {
              Label {
                VStack(alignment: .leading, spacing: 3) {
                  Text(tool.name).froggyFont(.headline)
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
    }
    .froggyListSurface()
    .froggyNavigationTitle("Tools & Skills")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton {
        CloseButton { model.sheet = nil }
      }
      if selection == .skills {
        ToolbarItem(placement: .primaryAction) {
          Button("Create", systemImage: "plus") {
            editor = SkillEditorDestination(skillID: nil)
          }
        }
      }
    }
    .navigationDestination(item: $editor) { destination in
      SkillEditor(model: model, id: destination.skillID, showsDismissButton: false)
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
    .froggyNavigationTitle(capability.name)
    .toolbarTitleDisplayMode(.inline)
  }

  private var accessLabel: String {
    capability.risk == "interactive" ? "Asks before making changes" : "Read only"
  }
}

private struct SkillDetailView: View {
  @Bindable var model: AppModel
  let id: String
  let edit: () -> Void
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
            Button("Edit Skill", systemImage: "pencil", action: edit)
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
    .froggyNavigationTitle(detail?.name ?? "Skill")
    .toolbarTitleDisplayMode(.inline)
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
