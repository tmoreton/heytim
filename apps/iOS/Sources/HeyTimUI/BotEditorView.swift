import SwiftUI

struct BotEditor: View {
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
      return [BotColorOption(value: "#FFBC3B", name: "Tim yellow")]
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

  private var canSave: Bool {
    identityIssue == nil && instructionsIssue == nil
      && effectiveCatalogToolIDs(draft: draft, skills: model.bootstrap?.skills ?? []).count
        <= (model.constraints.maxToolsPerBot ?? 13)
      && !saving
  }

  private var selectedSkillCount: Int { draft.skillIds.count }

  private var effectiveToolCount: Int {
    effectiveCatalogToolIDs(draft: draft, skills: model.bootstrap?.skills ?? []).count
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
            botID: editingBot?.id,
            skills: model.bootstrap?.skills ?? [],
            tools: model.bootstrap?.tools ?? [],
            providers: model.bootstrap?.connectionProviders ?? [])
        } label: {
          Label {
            VStack(alignment: .leading, spacing: 3) {
              Text("Assign Tools & Skills")
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
        Text(
          effectiveCatalogToolIDs(draft: draft, skills: model.bootstrap?.skills ?? []).count
            > (model.constraints.maxToolsPerBot ?? 13)
            ? "Choose at most \(model.constraints.maxToolsPerBot ?? 13) tools, including those required by skills."
            : "Choose optional playbooks and the actions this bot can use.")
      }
      Section {
        Picker("Model", selection: $draft.modelPreference) {
          Text("DeepSeek").tag("deepseek")
          Text("GLM").tag("glm")
        }
        Picker("Reasoning", selection: $draft.reasoningEffort) {
          Text("Low").tag("low")
          Text("High").tag("high")
          Text("Maximum").tag("max")
        }
      } header: {
        Text("Model")
      } footer: {
        Text("Both models use Hey Tim's supported provider. The other model is available if the selected model fails before responding.")
      }
      Section {
        Picker("Mode", selection: $draft.conversationMode) {
          Text("Agent with tools").tag("agent")
          Text("Chat only").tag("chat")
        }
      } header: {
        Text("Conversation")
      } footer: {
        Text("Chat only replies without tools, connected accounts, or skills. You can switch modes later.")
      }
      if let bot = editingBot {
        Section("Email") {
          FeatureLink {
            BotInboxView(model: model, botId: bot.id, showsDismissButton: false)
          } label: {
            Label("Bot Inbox", systemImage: "tray")
          }
        }
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
        Button("Save") { save() }
          .froggyGlassButton(prominent: true)
          .disabled(!canSave)
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
