import SwiftUI
import UniformTypeIdentifiers

public struct MainView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  @State private var dictation = DictationModel()
  @State private var columns: NavigationSplitViewVisibility = .all
  @State private var showingPhoneSidebar = false

  public init(model: AppModel, auth: AuthSession) {
    self.model = model
    self.auth = auth
  }

  public var body: some View {
    layout
    .tint(FrogTheme.brand)
    .foregroundStyle(FrogTheme.text)
    .sheet(item: $model.sheet) { sheet in FeatureSheet(sheet: sheet, model: model, auth: auth) }
    .alert(
      "FroggyBot",
      isPresented: Binding(
        get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })
    ) {
      Button("OK") { model.errorMessage = nil }
    } message: {
      Text(model.errorMessage ?? "")
    }
    .alert(
      "Invitation",
      isPresented: Binding(
        get: { model.deepLinkInvite != nil }, set: { if !$0 { model.deepLinkInvite = nil } })
    ) {
      Button("Join") { Task { await model.acceptPendingInvite() } }
      Button("Cancel", role: .cancel) { model.deepLinkInvite = nil }
    } message: {
      Text("Add this shared \(model.deepLinkInvite?.kind ?? "item") to your account?")
    }
    .onChange(of: dictation.transcript) { _, value in
      if !value.isEmpty { model.composerText = value }
    }
    .onChange(of: model.composerText) { _, value in
      if value.isEmpty && !dictation.isRecording { _ = dictation.consumeTranscript() }
    }
    .onChange(of: model.selection) { _, newValue in
      #if os(iOS)
        if newValue != nil { showingPhoneSidebar = false }
      #endif
    }
    .onDisappear { dictation.shutDown() }
  }

  @ViewBuilder private var layout: some View {
    #if os(iOS)
      ZStack(alignment: .leading) {
        if showingPhoneSidebar || model.selection == nil {
          ConversationSidebar(model: model, auth: auth) { selection in
            model.select(selection)
            withAnimation(.easeOut(duration: 0.2)) { showingPhoneSidebar = false }
          }
          .transition(.move(edge: .leading))
        } else {
          ConversationView(model: model, dictation: dictation) {
            withAnimation(.easeOut(duration: 0.2)) { showingPhoneSidebar = true }
          }
          .transition(.move(edge: .trailing))
        }
      }
    #else
      NavigationSplitView(columnVisibility: $columns) {
      ConversationSidebar(model: model, auth: auth) { selection in
        model.select(selection)
      }
      .navigationSplitViewColumnWidth(min: 250, ideal: 290, max: 330)
    } detail: {
      if model.selection != nil {
        ConversationView(model: model, dictation: dictation) {
          columns = .all
        }
      } else {
        EmptyPanel(
          icon: "bubble.left.and.bubble.right", title: "Choose a chat",
          detail: "Select a person, group, or FroggyBot from the chat list.")
      }
    }
    .navigationSplitViewStyle(.balanced)
    #endif
  }
}

private struct ConversationSidebar: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  let select: (ConversationSelection) -> Void
  @State private var search = ""

  private var groups: [BotGroup] {
    (model.bootstrap?.groups ?? []).filter { searchMatch($0.name, $0.lastMessage) }
  }
  private var bots: [Bot] {
    (model.bootstrap?.bots ?? []).filter { searchMatch($0.name, $0.lastMessage) }
  }

  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 10) {
        VStack(alignment: .leading, spacing: 1) {
          Text("FroggyBot")
            .font(.system(size: 20, weight: .heavy))
            .tracking(-0.5)
            .foregroundStyle(FrogTheme.brand)
          Text("Your AI team").font(.system(size: 12)).foregroundStyle(FrogTheme.muted)
        }
        Spacer()
        Menu {
          Button("Add a bot", systemImage: "plus.circle") { model.sheet = .botLibrary }
          Button("Create a custom bot", systemImage: "slider.horizontal.3") {
            model.sheet = .botEditor(nil)
          }
          Button("New group", systemImage: "person.3") { model.sheet = .groupEditor(nil) }
        } label: {
          Image(systemName: "plus")
            .font(.system(size: 20, weight: .regular))
            .foregroundStyle(FrogTheme.textSoft)
            .frame(width: 44, height: 44)
            .background(FrogTheme.surface, in: Circle())
        }
        .menuStyle(.borderlessButton)
        .accessibilityLabel("Create bot or group")
      }
      .frame(minHeight: 70)
      .padding(.horizontal, 17)

      TextField("Search chats", text: $search)
        .textFieldStyle(.plain)
        .font(.system(size: 14))
        .foregroundStyle(FrogTheme.textSoft)
        .padding(.horizontal, 13)
        .frame(height: 44)
        .background(Color(hex: "#E6E4DF"), in: RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 12)
        .accessibilityLabel("Search chats")

      ScrollView {
        LazyVStack(spacing: 0) {
          if !groups.isEmpty {
            sidebarSection("Groups")
            ForEach(groups) { group in
              conversationRow(
                selection: .init(kind: .group, id: group.id), name: group.name,
                preview: group.lastMessage, date: group.lastMessageAt,
                processing: group.processing == true, processingName: group.processingBotName
              ) { GroupAvatar(group: group, size: 42) }
            }
          }
          if !bots.isEmpty {
            sidebarSection("Bots")
            ForEach(bots) { bot in
              conversationRow(
                selection: .init(kind: .bot, id: bot.id), name: bot.name,
                preview: bot.lastMessage, date: bot.lastMessageAt,
                processing: bot.processing == true, processingName: bot.name
              ) { BotAvatar(name: bot.name, color: bot.color, size: 42) }
            }
          }
          if groups.isEmpty && bots.isEmpty {
            Text(search.isEmpty ? "Your chats will appear here." : "No chats match your search.")
              .font(.system(size: 13))
              .foregroundStyle(FrogTheme.muted)
              .frame(maxWidth: .infinity, alignment: .leading)
              .padding(.horizontal, 14).padding(.top, 24)
          }
        }
        .padding(.horizontal, 8)
        .padding(.top, 11)
      }

      Divider().overlay(Color(hex: "#D9D6CF"))
      Button { model.sheet = .account } label: {
        HStack(spacing: 10) {
          Circle().fill(FrogTheme.brand).frame(width: 30, height: 30)
          VStack(alignment: .leading, spacing: 1) {
            Text("Account & settings").font(.system(size: 13, weight: .semibold))
            Text("Memory, skills, connections")
              .font(.system(size: 11)).foregroundStyle(FrogTheme.muted)
          }
          Spacer()
          Image(systemName: "chevron.right")
            .font(.system(size: 12, weight: .semibold)).foregroundStyle(FrogTheme.muted)
        }
        .padding(.horizontal, 16).frame(minHeight: 64)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open account settings")
    }
    .background(FrogTheme.drawer)
    .overlay(alignment: .trailing) { Rectangle().fill(Color(hex: "#D9D6CF")).frame(width: 0.5) }
    .overlay { if model.isLoading { ProgressView().tint(FrogTheme.brand) } }
  }

  private func sidebarSection(_ title: String) -> some View {
    Text(title.uppercased())
      .font(.system(size: 11, weight: .bold))
      .tracking(0.6)
      .foregroundStyle(FrogTheme.muted)
      .frame(maxWidth: .infinity, alignment: .leading)
      .padding(.horizontal, 9).padding(.top, 9).padding(.bottom, 5)
  }

  private func conversationRow<Avatar: View>(
    selection: ConversationSelection, name: String, preview: String, date: String,
    processing: Bool, processingName: String?, @ViewBuilder avatar: () -> Avatar
  ) -> some View {
    let selected = model.selection == selection
    return Button { select(selection) } label: {
      HStack(spacing: 11) {
        avatar()
        VStack(alignment: .leading, spacing: 3) {
          HStack(spacing: 7) {
            Text(name).font(.system(size: 15, weight: .semibold)).lineLimit(1)
            Spacer(minLength: 4)
            if processing {
              HStack(spacing: 4) {
                Circle().fill(FrogTheme.brand).frame(width: 6, height: 6)
                Text("WORKING").font(.system(size: 9, weight: .heavy))
              }
              .foregroundStyle(FrogTheme.brandDark)
              .padding(.horizontal, 6).padding(.vertical, 3)
              .background(Color(hex: "#D9EDDF"), in: Capsule())
            } else if let formatted = date.froggyDate?.formatted(.dateTime.month().day()) {
              Text(formatted).font(.system(size: 11)).foregroundStyle(FrogTheme.muted)
            }
          }
          Text(processing ? "\(processingName ?? name) is thinking…" : preview)
            .font(.system(size: 12, weight: processing ? .semibold : .regular))
            .foregroundStyle(processing ? Color(hex: "#187044") : FrogTheme.mutedWarm)
            .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
      .padding(.horizontal, 9)
      .frame(minHeight: 64)
      .contentShape(RoundedRectangle(cornerRadius: 13))
      .background(selected ? FrogTheme.selected : .clear, in: RoundedRectangle(cornerRadius: 13))
    }
    .buttonStyle(.plain)
    .accessibilityAddTraits(selected ? .isSelected : [])
  }

  private func searchMatch(_ values: String...) -> Bool {
    search.isEmpty || values.contains { $0.localizedCaseInsensitiveContains(search) }
  }
}

private struct ConversationView: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  let revealSidebar: () -> Void
  @State private var importing = false
  @State private var showDelete = false
  @State private var showClear = false

  var body: some View {
    VStack(spacing: 0) {
      conversationHeader
      ScrollViewReader { proxy in
        ScrollView {
          LazyVStack(spacing: 0) {
            if model.nextToken != nil {
              Button("Load earlier messages") { Task { await model.loadEarlier() } }
                .font(.system(size: 13, weight: .bold)).foregroundStyle(FrogTheme.brand)
                .frame(minHeight: 44).padding(.bottom, 8)
            }
            if model.messages.isEmpty { emptyConversation }
            ForEach(model.messages) { MessageBubble(message: $0, model: model) }
            Color.clear.frame(height: 1).id("bottom")
          }
          .padding(.horizontal, 14).padding(.top, 24).padding(.bottom, 42)
          .frame(maxWidth: 780)
          .frame(maxWidth: .infinity)
        }
        .onChange(of: model.messages.count) { _, _ in
          withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
        }
        .defaultScrollAnchor(.bottom)
      }
      Composer(model: model, dictation: dictation, importing: $importing)
    }
    .background(FrogTheme.appBackground)
    .fileImporter(
      isPresented: $importing, allowedContentTypes: [.image, .pdf, .plainText, .data],
      allowsMultipleSelection: true
    ) { result in
      if case .success(let urls) = result {
        Task { await model.upload(urls: urls) }
      } else if case .failure(let error) = result {
        model.present(error)
      }
    }
    .confirmationDialog("Clear this conversation?", isPresented: $showClear) {
      Button("Clear messages", role: .destructive) {
        Task { await model.clearCurrent(forgetMemory: false) }
      }
      Button("Clear and forget learned memory", role: .destructive) {
        Task { await model.clearCurrent(forgetMemory: true) }
      }
    }
    .confirmationDialog("Delete \(model.title)?", isPresented: $showDelete) {
      Button("Delete", role: .destructive) { Task { await model.deleteCurrent() } }
    }
  }

  private var conversationHeader: some View {
    HStack(spacing: 9) {
      Button(action: revealSidebar) {
        VStack(alignment: .leading, spacing: 5) {
          Capsule().fill(Color(hex: "#383731")).frame(width: 19, height: 2)
          Capsule().fill(Color(hex: "#383731")).frame(width: 13, height: 2)
        }
        .frame(width: 32, height: 32)
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Toggle chat list")

      if let group = model.selectedGroup {
        GroupAvatar(group: group, size: 31)
      } else if let bot = model.selectedBot {
        BotAvatar(name: bot.name, color: bot.color, size: 31)
      }
      VStack(alignment: .leading, spacing: 1) {
        Text(model.title).font(.system(size: 15, weight: .bold)).lineLimit(1)
        Text(model.subtitle).font(.system(size: 11)).foregroundStyle(FrogTheme.brand).lineLimit(1)
      }
      Spacer()
      actionsMenu
    }
    .padding(.horizontal, 14)
    .frame(minHeight: 58)
    .background(FrogTheme.appBackground)
    .overlay(alignment: .bottom) { Rectangle().fill(Color(hex: "#E0DED8")).frame(height: 0.5) }
  }

  private var actionsMenu: some View {
    Menu {
      if let bot = model.selectedBot {
        let actions = Set(bot.allowedActions ?? [])
        if actions.contains("schedule"), let selection = model.selection {
          Button("Scheduled tasks", systemImage: "calendar") { model.sheet = .schedules(selection) }
          Button("Run history", systemImage: "clock.arrow.circlepath") {
            model.sheet = .scheduleRuns(selection)
          }
        }
        if actions.contains("share"), let selection = model.selection {
          Button("Share", systemImage: "square.and.arrow.up") { model.sheet = .share(selection) }
        }
        if actions.contains("edit") {
          Button("Edit bot", systemImage: "pencil") { model.sheet = .botEditor(bot.id) }
        }
        if actions.contains("documents") {
          Button("Documents", systemImage: "doc") { model.sheet = .documents(bot.id) }
        }
        if actions.contains("browser") {
          Button("Browser", systemImage: "globe") { model.sheet = .browser(botId: bot.id, groupId: nil) }
        }
        Button("Memory", systemImage: "brain") { model.sheet = .memories(nil) }
        if actions.contains("clear") {
          Button("Clear chat", systemImage: "eraser", role: .destructive) { showClear = true }
        }
        if actions.contains("delete") {
          Button("Delete", systemImage: "trash", role: .destructive) { showDelete = true }
        }
      } else if let group = model.selectedGroup {
        let actions = Set(group.allowedActions ?? [])
        if actions.contains("schedule"), let selection = model.selection {
          Button("Scheduled tasks", systemImage: "calendar") { model.sheet = .schedules(selection) }
          Button("Run history", systemImage: "clock.arrow.circlepath") {
            model.sheet = .scheduleRuns(selection)
          }
        }
        if actions.contains("share"), let selection = model.selection {
          Button("Share", systemImage: "square.and.arrow.up") { model.sheet = .share(selection) }
        }
        if actions.contains("edit") {
          Button("Edit group", systemImage: "pencil") { model.sheet = .groupEditor(group.id) }
        }
        if actions.contains("viewMemory") || actions.contains("manageMemory") {
          Button("Group memory", systemImage: "brain") { model.sheet = .memories(group.id) }
        }
        if actions.contains("delete") {
          Button("Delete", systemImage: "trash", role: .destructive) { showDelete = true }
        }
      }
    } label: {
      Image(systemName: "ellipsis")
        .font(.system(size: 17, weight: .bold))
        .foregroundStyle(Color(hex: "#4B4942"))
        .frame(width: 32, height: 32)
    }
    .menuStyle(.borderlessButton)
    .accessibilityLabel("\(model.title) actions")
  }

  private var emptyConversation: some View {
    VStack(spacing: 0) {
      if let bot = model.selectedBot { BotAvatar(name: bot.name, color: bot.color, size: 70) }
      Text("Start a conversation")
        .font(.system(size: 22, weight: .heavy)).tracking(-0.4).padding(.top, 18)
      Text("Ask \(model.title) what you would like to move forward.")
        .font(.system(size: 14)).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center).padding(.top, 7)
    }
    .frame(maxWidth: .infinity, minHeight: 360)
  }
}

private struct MessageBubble: View {
  let message: ChatMessage
  @Bindable var model: AppModel
  @Environment(\.openURL) private var openURL

  private var mine: Bool {
    model.selectedGroup == nil ? message.isUser : message.authorType == "user" && message.isMine == true
  }
  private var groupMode: Bool { model.selectedGroup != nil }
  private var botMessage: Bool { message.role == "assistant" || message.authorType == "bot" }
  private var awaitingApproval: Bool {
    message.status == "awaiting_approval"
      || message.allowedActions?.contains(where: {
        ["reject", "approveOnce", "approveAlways"].contains($0)
      }) == true
  }

  var body: some View {
    HStack(alignment: .bottom, spacing: 7) {
      if groupMode && !mine { avatar }
      if mine { Spacer(minLength: 50) }
      VStack(alignment: mine ? .trailing : .leading, spacing: 3) {
        if groupMode {
          Text(mine ? "You" : authorLabel)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(mine ? FrogTheme.brand : FrogTheme.mutedWarm)
            .padding(.horizontal, 6)
        } else if message.source == "schedule" {
          Text("Scheduled · \(message.scheduleName ?? "Recurring task")")
            .font(.system(size: 10, weight: .bold)).foregroundStyle(Color(hex: "#61766B"))
            .padding(.horizontal, 6)
        }

        if !mine, let activity = message.activity, message.isActive {
          VStack(alignment: .leading, spacing: 5) {
            ForEach(activity, id: \.self) { step in
              Label(step, systemImage: "sparkles")
            }
            ProgressView().controlSize(.small).tint(FrogTheme.brand)
          }
          .font(.system(size: 11)).foregroundStyle(FrogTheme.muted)
          .padding(.horizontal, 6).padding(.bottom, 4)
        }

        VStack(alignment: .leading, spacing: 8) {
          if awaitingApproval {
            Text("Approval needed").font(.system(size: 14, weight: .heavy))
              .foregroundStyle(Color(hex: "#4B3C0D"))
            Text(
              "This reply may use \(message.approvalTools?.joined(separator: ", ") ?? "an interactive tool") to take action."
            )
            .font(.system(size: 13)).foregroundStyle(Color(hex: "#5E501F"))
          } else {
            markdownText(message.text)
              .font(.system(size: 15)).lineSpacing(3).textSelection(.enabled)
              .foregroundStyle(mine ? .white : FrogTheme.textSoft)
          }

          ForEach(message.attachments ?? []) { attachment in
            Button { open(attachment) } label: {
              Label(attachment.name, systemImage: attachment.kind == "image" ? "photo" : "doc")
            }
            .buttonStyle(.plain).font(.system(size: 12, weight: .semibold))
          }

          if awaitingApproval {
            HStack(spacing: 8) {
              if message.allowedActions?.contains("reject") == true {
                Button("Don’t allow") { Task { await model.reject(message) } }
                  .buttonStyle(FroggySecondaryButtonStyle())
              }
              if message.allowedActions?.contains("approveOnce") == true {
                Button("Allow once") { Task { await model.approve(message, always: false) } }
                  .buttonStyle(FroggySecondaryButtonStyle())
              }
              if message.allowedActions?.contains("approveAlways") == true {
                Button("Always allow") { Task { await model.approve(message, always: true) } }
                  .buttonStyle(FroggySecondaryButtonStyle())
              }
            }
          }
          if message.allowedActions?.contains("saveDecision") == true {
            Button("Save decision", systemImage: "bookmark") { Task { await model.saveDecision(message) } }
              .buttonStyle(.plain).font(.system(size: 12, weight: .heavy))
              .foregroundStyle(FrogTheme.brandDark).frame(minHeight: 40)
          }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(bubbleColor, in: bubbleShape)
        .overlay { if bubbleBorder != .clear { bubbleShape.stroke(bubbleBorder) } }

        HStack(spacing: 5) {
          Text(message.status.replacingOccurrences(of: "_", with: " ").capitalized)
          Text(message.createdAt.froggyDate?.formatted(date: .omitted, time: .shortened) ?? "")
        }
        .font(.system(size: 9)).foregroundStyle(FrogTheme.muted)
        .padding(.horizontal, 6).padding(.top, 1)
      }
      .frame(maxWidth: mine ? 650 : 720, alignment: mine ? .trailing : .leading)
      if !mine { Spacer(minLength: 50) }
    }
    .frame(maxWidth: .infinity)
    .padding(.bottom, 8)
  }

  @ViewBuilder private var avatar: some View {
    let name = message.authorName ?? (botMessage ? model.title : "Person")
    if botMessage {
      BotAvatar(name: name, color: message.authorColor ?? "#007A3D", size: 31)
    } else {
      PersonAvatar(name: name, size: 31)
    }
  }
  private var authorLabel: String {
    let name = message.authorName ?? (botMessage ? model.title : "Person")
    let role: String? = switch message.roundRole {
    case "lead": "Lead"
    case "contributor": "Contribution"
    case "synthesizer": "Team answer"
    default: nil
    }
    return role.map { "\(name) · \($0)" } ?? name
  }
  private var bubbleShape: UnevenRoundedRectangle {
    UnevenRoundedRectangle(
      topLeadingRadius: mine ? 18 : 6, bottomLeadingRadius: 18,
      bottomTrailingRadius: mine ? 6 : 18, topTrailingRadius: 18)
  }
  private var bubbleColor: Color {
    if awaitingApproval { return FrogTheme.approval }
    if message.status == "error" { return Color(hex: "#F8E6E1") }
    if message.roundRole == "synthesizer" { return FrogTheme.teamBubble }
    return mine ? FrogTheme.brand : FrogTheme.assistantBubble
  }
  private var bubbleBorder: Color {
    if awaitingApproval { return FrogTheme.approvalBorder }
    if message.roundRole == "synthesizer" { return FrogTheme.teamBorder }
    return .clear
  }
  private func markdownText(_ markdown: String) -> Text {
    (try? AttributedString(
      markdown: markdown, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
      .map(Text.init) ?? Text(markdown)
  }
  private func open(_ attachment: Attachment) {
    Task {
      do {
        if let url = try await model.api?.downloadURL(
          fileId: attachment.id, groupId: model.selectedGroup?.id)
        { openURL(url) }
      } catch { model.present(error) }
    }
  }
}

private struct Composer: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var importing: Bool

  var body: some View {
    VStack(spacing: 0) {
      if model.selectedGroup != nil { replyPicker }
      if !model.pendingAttachments.isEmpty { attachmentPicker }
      HStack(alignment: .bottom, spacing: 2) {
        Button { importing = true } label: {
          Image(systemName: "paperclip")
            .font(.system(size: 18)).foregroundStyle(Color(hex: "#4F4C45"))
            .frame(width: 34, height: 38)
        }
        .buttonStyle(.plain).accessibilityLabel("Attach files")

        TextField("Message \(model.title)", text: $model.composerText, axis: .vertical)
          .textFieldStyle(.plain).font(.system(size: 15)).lineLimit(1...6)
          .foregroundStyle(FrogTheme.textSoft).padding(.vertical, 9)
          .onSubmit { if canSend { Task { await model.send() } } }

        Button { dictation.toggle() } label: {
          Image(systemName: dictation.isRecording ? "mic.fill" : "mic")
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(dictation.isRecording ? .white : Color(hex: "#4F4C45"))
            .frame(width: 38, height: 38)
            .background(dictation.isRecording ? FrogTheme.brand : .clear, in: Circle())
        }
        .buttonStyle(.plain).accessibilityLabel("Dictate on device")

        Button {
          Task {
            if model.canStop && model.composerText.isEmpty { await model.stop() } else { await model.send() }
          }
        } label: {
          Image(systemName: model.canStop && model.composerText.isEmpty ? "stop.fill" : "arrow.up")
            .font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
            .frame(width: 38, height: 38)
            .background(canSend || model.canStop ? FrogTheme.brand : Color(hex: "#B8D5C6"), in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(model.isSending || (!canSend && !model.canStop))
        .accessibilityLabel(model.canStop && model.composerText.isEmpty ? "Stop reply" : "Send message")
      }
      .padding(.leading, 8).padding(.trailing, 6).padding(.vertical, 6)
      .frame(minHeight: 51)
      .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 20))
      .overlay(RoundedRectangle(cornerRadius: 20).stroke(Color(hex: "#DCD9D2")))
      .frame(maxWidth: 780)

      Text("Bots can make mistakes. Check important work. · Enter to send · Shift+Enter for a new line.")
        .font(.system(size: 10)).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center).padding(.top, 5)
      if let error = dictation.errorMessage {
        Text(error).font(.system(size: 11)).foregroundStyle(FrogTheme.danger).padding(.top, 3)
      }
    }
    .padding(.horizontal, 12).padding(.top, 8).padding(.bottom, 9)
    .frame(maxWidth: .infinity)
    .background(FrogTheme.appBackground)
  }

  private var canSend: Bool {
    !model.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      || !model.pendingAttachments.isEmpty
  }
  private var attachmentPicker: some View {
    ScrollView(.horizontal) {
      HStack(spacing: 7) {
        ForEach(model.pendingAttachments) { item in
          HStack(spacing: 7) {
            Image(systemName: "paperclip")
            Text(item.name).font(.system(size: 12, weight: .bold)).lineLimit(1)
            Button { model.removeAttachment(item.id) } label: {
              Image(systemName: "xmark.circle.fill")
            }
            .buttonStyle(.plain).accessibilityLabel("Remove \(item.name)")
          }
          .foregroundStyle(Color(hex: "#34322D"))
          .padding(.horizontal, 11).frame(minHeight: 38)
          .background(Color(hex: "#F3F2EE"), in: RoundedRectangle(cornerRadius: 12))
          .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color(hex: "#D8D4CB")))
        }
      }
    }
    .frame(maxWidth: 780).padding(.bottom, 7)
  }
  private var replyPicker: some View {
    ScrollView(.horizontal) {
      HStack(spacing: 7) {
        replyButton(id: nil, title: "Just the group") { PersonAvatar(name: "People", size: 24) }
        if let group = model.selectedGroup {
          if group.bots.count > 1 {
            replyButton(id: "all", title: "Bring in the team") {
              Image(systemName: "person.3.fill").foregroundStyle(FrogTheme.brand).frame(width: 24)
            }
          }
          ForEach(group.bots) { bot in
            replyButton(id: bot.id, title: "\(bot.name) replies") {
              BotAvatar(name: bot.name, color: bot.color, size: 24)
            }
          }
        }
      }
    }
    .frame(maxWidth: 780).padding(.bottom, 7).accessibilityLabel("Who should reply")
  }
  private func replyButton<Icon: View>(
    id: String?, title: String, @ViewBuilder icon: () -> Icon
  ) -> some View {
    let selected = model.activeGroupReplyBotId == id
    return Button { model.groupReplyBotId = id } label: {
      HStack(spacing: 7) {
        icon()
        Text(title).font(.system(size: 12, weight: .semibold))
      }
      .foregroundStyle(selected ? FrogTheme.brandDark : Color(hex: "#67635C"))
      .padding(.leading, 6).padding(.trailing, 12).frame(minHeight: 44)
      .background(selected ? Color(hex: "#E6F2EB") : FrogTheme.surface, in: Capsule())
      .overlay(Capsule().stroke(selected ? Color(hex: "#7CAB90") : Color(hex: "#DEDAD2")))
    }
    .buttonStyle(.plain).accessibilityAddTraits(selected ? .isSelected : [])
  }
}
