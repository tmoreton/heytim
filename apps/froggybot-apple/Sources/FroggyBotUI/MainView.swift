import SwiftUI
import UniformTypeIdentifiers

public struct MainView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  @State private var dictation = DictationModel()

  public init(model: AppModel, auth: AuthSession) {
    self.model = model
    self.auth = auth
  }

  public var body: some View {
    NavigationSplitView {
      Sidebar(model: model, auth: auth)
        .navigationSplitViewColumnWidth(min: 230, ideal: 280, max: 360)
    } detail: {
      if model.selection != nil {
        ConversationView(model: model, dictation: dictation)
      } else {
        EmptyPanel(
          icon: "bubble.left.and.bubble.right", title: "Choose a conversation",
          detail: "Select a bot or group from the sidebar.")
      }
    }
    .tint(FrogTheme.green)
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
    .onDisappear { dictation.shutDown() }
  }
}

private struct Sidebar: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  var body: some View {
    List(
      selection: Binding(
        get: { model.selection }, set: { if let value = $0 { model.select(value) } })
    ) {
      Section("Groups") {
        ForEach(model.bootstrap?.groups ?? []) { group in
          NavigationLink(value: ConversationSelection(kind: .group, id: group.id)) {
            Label {
              VStack(alignment: .leading) {
                Text(group.name)
                if !group.lastMessage.isEmpty {
                  Text(group.lastMessage).font(.caption).lineLimit(1).foregroundStyle(.secondary)
                }
              }
            } icon: {
              Image(systemName: "person.3.fill").foregroundStyle(FrogTheme.green)
            }
          }
        }
        Button("New group", systemImage: "plus") { model.sheet = .groupEditor(nil) }
      }
      Section("Bots") {
        ForEach(model.bootstrap?.bots ?? []) { bot in
          NavigationLink(value: ConversationSelection(kind: .bot, id: bot.id)) {
            HStack(spacing: 10) {
              BotAvatar(name: bot.name, color: bot.color, size: 30)
              VStack(alignment: .leading) {
                Text(bot.name)
                if !bot.lastMessage.isEmpty {
                  Text(bot.lastMessage).font(.caption).lineLimit(1).foregroundStyle(.secondary)
                }
              }
              if bot.processing == true { ProgressView().controlSize(.small) }
            }
          }
        }
        Button("Add a bot", systemImage: "plus") { model.sheet = .botLibrary }
      }
    }
    .navigationTitle("FroggyBot")
    .toolbar {
      ToolbarItem(placement: .primaryAction) {
        Menu {
          Button("Add a bot", systemImage: "plus.circle") { model.sheet = .botLibrary }
          Button("New group", systemImage: "person.3") { model.sheet = .groupEditor(nil) }
          Divider()
          Button("Skills", systemImage: "sparkles") { model.sheet = .skills }
          Button("Connections", systemImage: "link") { model.sheet = .connections }
          Button("Memory", systemImage: "brain") { model.sheet = .memories(nil) }
          Button("Account", systemImage: "person.crop.circle") { model.sheet = .account }
          Divider()
          Button("Sign out", role: .destructive) {
            Task {
              await model.unregisterPush()
              await auth.signOut()
            }
          }
        } label: {
          Image(systemName: "ellipsis.circle")
        }
      }
    }
    .overlay { if model.isLoading { ProgressView() } }
  }
}

private struct ConversationView: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @State private var importing = false
  @State private var showDelete = false
  @State private var showClear = false

  var body: some View {
    VStack(spacing: 0) {
      conversationHeader
      Divider()
      ScrollViewReader { proxy in
        ScrollView {
          LazyVStack(spacing: 15) {
            if model.nextToken != nil {
              Button("Load earlier messages") { Task { await model.loadEarlier() } }.font(.caption)
            }
            ForEach(model.messages) { MessageBubble(message: $0, model: model) }
            Color.clear.frame(height: 1).id("bottom")
          }.padding()
        }
        .onChange(of: model.messages.count) { _, _ in
          withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
        }
        .defaultScrollAnchor(.bottom)
      }
      Divider()
      Composer(model: model, dictation: dictation, importing: $importing)
    }
    .background(FrogTheme.background.opacity(0.45))
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
    HStack {
      VStack(alignment: .leading, spacing: 2) {
        Text(model.title).font(.headline)
        Text(model.subtitle).font(.caption).foregroundStyle(.secondary)
      }
      Spacer()
      Menu {
        if let bot = model.selectedBot {
          let actions = Set(bot.allowedActions ?? [])
          if actions.contains("schedule"), let selection = model.selection {
            Button("Scheduled tasks", systemImage: "calendar") {
              model.sheet = .schedules(selection)
            }
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
            Button("Browser", systemImage: "globe") {
              model.sheet = .browser(botId: bot.id, groupId: nil)
            }
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
            Button("Scheduled tasks", systemImage: "calendar") {
              model.sheet = .schedules(selection)
            }
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
        Image(systemName: "ellipsis.circle").font(.title3)
      }
    }.padding(.horizontal).padding(.vertical, 11).background(.bar)
  }
}

private struct MessageBubble: View {
  let message: ChatMessage
  @Bindable var model: AppModel
  @Environment(\.openURL) private var openURL
  var body: some View {
    HStack(alignment: .bottom) {
      if message.isUser { Spacer(minLength: 50) }
      VStack(alignment: .leading, spacing: 8) {
        if !message.isUser {
          Text(message.authorName ?? model.title).font(.caption.bold()).foregroundStyle(
            Color(hex: message.authorColor ?? "#007A3D"))
        }
        markdownText(message.text).textSelection(.enabled)
        ForEach(message.attachments ?? []) { attachment in
          Button {
            open(attachment)
          } label: {
            Label(attachment.name, systemImage: attachment.kind == "image" ? "photo" : "doc")
          }
          .buttonStyle(.plain)
          .font(.caption)
        }
        if let activity = message.activity, message.isActive {
          ForEach(activity, id: \.self) {
            Label($0, systemImage: "gearshape.2").font(.caption).foregroundStyle(.secondary)
          }
          ProgressView().controlSize(.small)
        }
        if message.status == "awaiting_approval" {
          Text(
            "This reply may use \(message.approvalTools?.joined(separator: ", ") ?? "an interactive tool") to take action."
          )
          .font(.caption)
          HStack {
            if message.allowedActions?.contains("reject") == true {
              Button("Don’t allow", role: .destructive) { Task { await model.reject(message) } }
                .buttonStyle(.bordered)
            }
            if message.allowedActions?.contains("approveOnce") == true {
              Button("Allow once") { Task { await model.approve(message, always: false) } }
                .buttonStyle(.borderedProminent)
            }
            if message.allowedActions?.contains("approveAlways") == true {
              Button("Always allow") { Task { await model.approve(message, always: true) } }
                .buttonStyle(.bordered)
            }
          }
        }
        if message.allowedActions?.contains("saveDecision") == true {
          Button("Save decision", systemImage: "bookmark") {
            Task { await model.saveDecision(message) }
          }
          .buttonStyle(.bordered)
        }
        HStack {
          Text(message.status.replacingOccurrences(of: "_", with: " ").capitalized)
          Text(message.createdAt.froggyDate?.formatted(date: .omitted, time: .shortened) ?? "")
        }
        .font(.caption2).foregroundStyle(.secondary)
      }
      .padding(13)
      .background(
        message.isUser ? FrogTheme.green.opacity(0.14) : Color.primary.opacity(0.055),
        in: RoundedRectangle(cornerRadius: 18)
      )
      .frame(maxWidth: 720, alignment: message.isUser ? .trailing : .leading)
      if !message.isUser { Spacer(minLength: 50) }
    }.frame(maxWidth: .infinity)
  }
  private func markdownText(_ markdown: String) -> Text {
    (try? AttributedString(
      markdown: markdown, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))).map(
        SwiftUI.Text.init) ?? SwiftUI.Text(markdown)
  }
  private func open(_ attachment: Attachment) {
    Task {
      do {
        if let url = try await model.api?.downloadURL(
          fileId: attachment.id, groupId: model.selectedGroup?.id)
        {
          openURL(url)
        }
      } catch { model.present(error) }
    }
  }
}

private struct Composer: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var importing: Bool
  var body: some View {
    VStack(spacing: 8) {
      if model.selectedGroup != nil { replyPicker }
      if !model.pendingAttachments.isEmpty {
        ScrollView(.horizontal) {
          HStack {
            ForEach(model.pendingAttachments) { item in
              HStack(spacing: 5) {
                Label(item.name, systemImage: "paperclip")
                Button {
                  model.removeAttachment(item.id)
                } label: {
                  Image(systemName: "xmark.circle.fill")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove \(item.name)")
              }
              .padding(7)
              .background(.quaternary, in: Capsule())
            }
          }
        }
      }
      HStack(alignment: .bottom, spacing: 8) {
        Button {
          importing = true
        } label: {
          Image(systemName: "paperclip")
        }.buttonStyle(.bordered).accessibilityLabel("Attach files")
        TextField("Message \(model.title)", text: $model.composerText, axis: .vertical)
          .textFieldStyle(.plain).lineLimit(1...6).padding(10)
          .background(.background, in: RoundedRectangle(cornerRadius: 14)).overlay(
            RoundedRectangle(cornerRadius: 14).stroke(FrogTheme.border)
          )
          .onSubmit { if !model.composerText.isEmpty { Task { await model.send() } } }
        Button {
          dictation.toggle()
        } label: {
          Image(systemName: dictation.isRecording ? "waveform.circle.fill" : "mic.circle")
        }
        .buttonStyle(.bordered).tint(dictation.isRecording ? .red : FrogTheme.green)
        .accessibilityLabel("Dictate on device")
        Button {
          Task {
            if model.canStop && model.composerText.isEmpty {
              await model.stop()
            } else {
              await model.send()
            }
          }
        } label: {
          Image(systemName: model.canStop && model.composerText.isEmpty ? "stop.fill" : "arrow.up")
        }
        .buttonStyle(.borderedProminent).tint(FrogTheme.green).disabled(model.isSending)
        .accessibilityLabel(
          model.canStop && model.composerText.isEmpty ? "Stop reply" : "Send message")
      }
      if let error = dictation.errorMessage { Text(error).font(.caption).foregroundStyle(.red) }
    }.padding().background(.bar)
  }

  private var replyPicker: some View {
    ScrollView(.horizontal) {
      HStack(spacing: 8) {
        replyButton(id: nil, title: "Just the group", systemImage: "person.2")
        if let group = model.selectedGroup {
          if group.bots.count > 1 {
            replyButton(id: "all", title: "Bring in the team", systemImage: "person.3")
          }
          ForEach(group.bots) { bot in
            replyButton(id: bot.id, title: "\(bot.name) replies", systemImage: "bubble.left")
          }
        }
      }
    }
    .accessibilityLabel("Who should reply")
  }

  private func replyButton(id: String?, title: String, systemImage: String) -> some View {
    let selected = model.activeGroupReplyBotId == id
    return Button {
      model.groupReplyBotId = id
    } label: {
      Label(title, systemImage: systemImage)
        .font(.caption.bold())
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
          selected ? FrogTheme.green.opacity(0.18) : Color.secondary.opacity(0.1), in: Capsule()
        )
        .overlay(Capsule().stroke(selected ? FrogTheme.green : .clear))
    }
    .buttonStyle(.plain)
    .accessibilityAddTraits(selected ? .isSelected : [])
  }
}
