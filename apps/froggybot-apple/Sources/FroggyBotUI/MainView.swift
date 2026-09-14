import SwiftUI
import CoreTransferable
import PhotosUI
import QuickLook
import UniformTypeIdentifiers

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

public struct MainView: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  @State private var dictation = DictationModel()
  @State private var columns: NavigationSplitViewVisibility = .all
  @State private var presentedSheet: AppSheet?
  @State private var pendingSheet: AppSheet?

  public init(model: AppModel, auth: AuthSession) {
    self.model = model
    self.auth = auth
    _presentedSheet = State(initialValue: model.sheet)
  }

  public var body: some View {
    layout
    .tint(FrogTheme.accent)
    .sheet(item: $presentedSheet, onDismiss: sheetDidDismiss) { sheet in
      FeatureSheet(sheet: sheet, model: model, auth: auth)
    }
    .onChange(of: model.sheet) { _, sheet in
      synchronizePresentedSheet(with: sheet)
    }
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
    .onDisappear { dictation.shutDown() }
  }

  private var layout: some View {
    NavigationSplitView(columnVisibility: $columns) {
      ConversationSidebar(model: model, auth: auth) { selection in
        dictation.cancel()
        model.select(selection)
      } present: { sheet in
        model.sheet = sheet
      }
      .navigationSplitViewColumnWidth(min: 270, ideal: 290, max: 320)
    } detail: {
      if model.selection != nil {
        ConversationView(model: model, dictation: dictation) { sheet in
          model.sheet = sheet
        }
      } else {
        EmptyPanel(
          icon: "bubble.left.and.bubble.right", title: "Choose a chat",
          detail: "Select a person, group, or FroggyBot from the chat list.")
      }
    }
    .navigationSplitViewStyle(.balanced)
  }

  private func synchronizePresentedSheet(with requestedSheet: AppSheet?) {
    guard presentedSheet != requestedSheet else { return }
    guard let requestedSheet else {
      pendingSheet = nil
      presentedSheet = nil
      return
    }
    if presentedSheet == nil {
      presentedSheet = requestedSheet
    } else {
      // Replacing an active sheet's item in place can make SwiftUI dismiss both views.
      // Finish the current dismissal before presenting the requested destination.
      pendingSheet = requestedSheet
      presentedSheet = nil
    }
  }

  private func sheetDidDismiss() {
    guard let nextSheet = pendingSheet else {
      model.sheet = nil
      return
    }
    pendingSheet = nil
    Task { @MainActor in
      await Task.yield()
      guard model.sheet == nextSheet else { return }
      presentedSheet = nextSheet
    }
  }
}

private struct ConversationSidebar: View {
  @Bindable var model: AppModel
  let auth: AuthSession
  let select: (ConversationSelection) -> Void
  let present: (AppSheet) -> Void
  @State private var search = ""
  @Environment(\.colorScheme) private var colorScheme

  private var conversations: [ConversationListItem] {
    guard let bootstrap = model.bootstrap else { return [] }
    return ConversationListItem.recentFirst(bots: bootstrap.bots, groups: bootstrap.groups)
      .filter { searchMatch($0.name, $0.lastMessage) }
      .sorted {
        let left = latestActivityDate(for: $0)
        let right = latestActivityDate(for: $1)
        if left != right { return left > right }
        return $0.name.localizedStandardCompare($1.name) == .orderedAscending
      }
  }

  var body: some View {
    List(
      selection: Binding(
        get: { model.selection },
        set: { value in if let value { select(value) } })
    ) {
      ForEach(conversations) { item in
        let processing = isProcessing(item)
        NavigationLink(value: item.selection) {
          conversationRow(
            selection: item.selection, name: item.name,
            preview: latestPreview(for: item), date: latestActivityDate(for: item),
            processing: processing, processingName: processingName(for: item)
          ) {
            switch item {
            case .group(let group):
              GroupAvatar(group: group, size: 42)
            case .bot(let bot):
              BotAvatar(name: bot.name, color: bot.color, size: 42)
            }
          }
        }
      }
      if conversations.isEmpty {
        ContentUnavailableView(
          search.isEmpty ? "No chats yet" : "No matches",
          systemImage: search.isEmpty ? "bubble.left.and.bubble.right" : "magnifyingglass",
          description: Text(
            search.isEmpty ? "Your chats will appear here." : "Try a different search."))
      }
    }
    .listStyle(.sidebar)
    .navigationTitle("FroggyBot")
    .toolbarTitleDisplayMode(.inline)
    .searchable(text: $search, placement: .sidebar, prompt: "Search chats")
    .toolbar {
      #if os(iOS)
        ToolbarItem(placement: .topBarLeading) {
          settingsButton
        }
        ToolbarItem(placement: .principal) {
          ViewThatFits(in: .horizontal) {
            HStack(spacing: 6) {
              FrogMark(size: 26)
              Text("FroggyBot").font(.headline).lineLimit(1)
            }
            FrogMark(size: 26)
          }
          .accessibilityElement(children: .ignore)
          .accessibilityLabel("FroggyBot")
        }
        ToolbarItem(placement: .primaryAction) {
          createMenu
        }
      #else
        ToolbarItemGroup(placement: .primaryAction) {
          settingsButton
          createMenu
        }
      #endif
    }
    .overlay { if model.isLoading { ProgressView().tint(FrogTheme.accent) } }
  }

  private var createMenu: some View {
    Menu {
      Button("Add a bot", systemImage: "plus.circle") { present(.botLibrary) }
      Button("Create a custom bot", systemImage: "slider.horizontal.3") {
        present(.botEditor(nil))
      }
      Button("New group", systemImage: "person.3") { present(.groupEditor(nil)) }
    } label: {
      Label("Create bot or group", systemImage: "plus")
        .foregroundStyle(createButtonColor)
    }
    .labelStyle(.iconOnly)
    .tint(createButtonColor)
    .accessibilityIdentifier("sidebar.create")
    .help("Add a bot or create a group")
  }

  private var settingsButton: some View {
    Button("Settings", systemImage: "gearshape") {
      present(.account)
    }
    .labelStyle(.iconOnly)
    .accessibilityIdentifier("sidebar.settings")
    .accessibilityHint("Opens account settings in this window")
    .help("Settings")
  }

  private func conversationRow<Avatar: View>(
    selection: ConversationSelection, name: String, preview: String, date: Date,
    processing: Bool, processingName: String?, @ViewBuilder avatar: () -> Avatar
  ) -> some View {
    HStack(spacing: 11) {
      avatar()
      VStack(alignment: .leading, spacing: 3) {
        HStack(spacing: 7) {
          Text(name).font(.headline).lineLimit(1)
          Spacer(minLength: 4)
          if processing {
            HStack(spacing: 5) {
              ProgressView().controlSize(.mini).tint(FrogTheme.accent)
              Text("Working").font(.caption2.weight(.semibold))
            }
            .foregroundStyle(FrogTheme.accent)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(FrogTheme.accent.opacity(colorScheme == .dark ? 0.18 : 0.11), in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(processingName ?? name) is working")
            .accessibilityIdentifier(
              "sidebar.processing.\(selection.kind.rawValue).\(selection.id)")
          } else if date != .distantPast {
            Text(date.formatted(.dateTime.month().day()))
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        }
        Text(processing ? "\(processingName ?? name) is working…" : preview)
          .font(.caption)
          .foregroundStyle(processing ? FrogTheme.accent : .secondary)
          .lineLimit(1)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .frame(minHeight: 48)
    .accessibilityAddTraits(model.selection == selection ? .isSelected : [])
  }

  private func searchMatch(_ values: String...) -> Bool {
    search.isEmpty || values.contains { $0.localizedCaseInsensitiveContains(search) }
  }

  private func isProcessing(_ item: ConversationListItem) -> Bool {
    if item.processing || model.sendingSelection == item.selection { return true }
    return model.selection == item.selection && model.messages.contains(where: \.isActive)
  }

  private func processingName(for item: ConversationListItem) -> String? {
    if model.selection == item.selection,
      let activeName = model.messages.last(where: {
        !$0.isUser && ["running", "processing", "in_progress", "streaming"].contains($0.status)
      })?.authorName
    {
      return activeName
    }
    if let name = item.processingBotName { return name }
    return item.selection.kind == .bot ? item.name : "A FroggyBot"
  }

  private func latestPreview(for item: ConversationListItem) -> String {
    guard model.selection == item.selection,
      let message = model.messages.last(where: { !$0.text.isEmpty })
    else { return item.lastMessage }
    return message.text
  }

  private func latestActivityDate(for item: ConversationListItem) -> Date {
    let sidebarDate = item.lastMessageAt.froggyDate ?? .distantPast
    guard model.selection == item.selection else { return sidebarDate }
    let visibleDate = model.messages.flatMap { message in
      [message.createdAt, message.startedAt, message.completedAt, message.activityUpdatedAt]
        .compactMap { $0?.froggyDate }
    }.max() ?? .distantPast
    return max(sidebarDate, visibleDate)
  }

  private var createButtonColor: Color {
    colorScheme == .dark ? .white : FrogTheme.brand
  }
}

private struct ConversationView: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  let present: (AppSheet) -> Void
  @State private var importing = false
  @State private var showDelete = false
  @State private var showClear = false
  @State private var showInspector = false
  @State private var previewURL: URL?
  @State private var previewTask: Task<Void, Never>?
  @State private var previewRequestID = UUID()
  @State private var pendingInspectorAction: InspectorAction?
  @State private var hasNewerMessages = false
  @State private var isFollowingLatest = true
  @State private var transcriptHeight: CGFloat = 0
  @State private var pendingScroll: Task<Void, Never>?
  @FocusState private var composerFocused: Bool

  private let bottomID = "froggy-conversation-bottom"
  private let scrollSpace = "froggy-conversation-scroll"
  private struct MessageRevision: Equatable {
    let id: String
    let fingerprint: Int
  }
  private struct TranscriptIdentity: Hashable {
    enum ContentState: Hashable {
      case loading
      case empty
      case populated
    }

    let selection: ConversationSelection?
    let contentState: ContentState
  }
  private enum InspectorAction {
    case open(AppSheet)
    case clear
    case delete
  }

  private var messageRevisions: [MessageRevision] {
    model.messages.map { MessageRevision(id: $0.id, fingerprint: $0.hashValue) }
  }

  private var transcriptIdentity: TranscriptIdentity {
    let contentState: TranscriptIdentity.ContentState
    if !model.messages.isEmpty {
      contentState = .populated
    } else if model.isLoadingMessages {
      contentState = .loading
    } else {
      contentState = .empty
    }
    return TranscriptIdentity(selection: model.selection, contentState: contentState)
  }

  var body: some View {
    ScrollViewReader { proxy in
      ScrollView {
        LazyVStack(spacing: 0) {
          if model.nextToken != nil {
            Button("Load Earlier Messages", systemImage: "arrow.up") {
              Task { await model.loadEarlier() }
            }
            .controlSize(.small)
            .frame(minHeight: 44)
            .padding(.bottom, 8)
          }
          if model.isLoadingMessages && model.messages.isEmpty {
            ProgressView("Loading conversation…")
              .tint(FrogTheme.accent)
              .containerRelativeFrame(.vertical, alignment: .center)
          } else if model.messages.isEmpty {
            emptyConversation
              .containerRelativeFrame(.vertical, alignment: .center)
          }
          ForEach(model.messages) { message in
            MessageBubble(message: message, model: model, preview: preview)
              .id(message.id)
          }
          Color.clear
            .frame(height: 1)
            .id(bottomID)
            .onGeometryChange(for: CGFloat.self) { geometry in
              geometry.frame(in: .named(scrollSpace)).minY
            } action: { bottomY in
              if bottomY >= 0, bottomY <= transcriptHeight + 80 {
                isFollowingLatest = true
                hasNewerMessages = false
              }
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, model.messages.isEmpty ? 0 : 24)
        .padding(.bottom, model.messages.isEmpty ? 0 : 16)
        .frame(maxWidth: 780)
        .frame(maxWidth: .infinity)
        .onGeometryChange(for: CGFloat.self) { geometry in
          geometry.size.height
        } action: { _ in
          if isFollowingLatest { scheduleScrollToBottom(using: proxy, animated: false) }
        }
      }
      .coordinateSpace(name: scrollSpace)
      .onGeometryChange(for: CGFloat.self) { geometry in
        geometry.size.height
      } action: { transcriptHeight = $0 }
      .accessibilityIdentifier("chat.transcript")
      .defaultScrollAnchor(.bottom)
      .scrollDismissesKeyboard(.interactively)
      .contentShape(Rectangle())
      .simultaneousGesture(
        TapGesture().onEnded {
          composerFocused = false
        })
      .simultaneousGesture(
        DragGesture(minimumDistance: 8).onChanged { _ in
          pendingScroll?.cancel()
          isFollowingLatest = false
        })
      .onAppear { scheduleScrollToBottom(using: proxy, animated: false) }
      .onChange(of: model.selection) { _, _ in
        cancelPreview()
        hasNewerMessages = false
        isFollowingLatest = true
        composerFocused = false
        scheduleScrollToBottom(using: proxy, animated: false)
      }
      .onChange(of: messageRevisions) { previous, current in
        let following = isFollowingLatest || previous.isEmpty
        if following {
          isFollowingLatest = true
          scheduleScrollToBottom(using: proxy, animated: !previous.isEmpty)
        } else if current.last != previous.last {
          hasNewerMessages = true
        }
      }
      .overlay(alignment: .bottomTrailing) {
        if hasNewerMessages {
          Button("Jump to Latest", systemImage: "arrow.down") {
            scheduleScrollToBottom(using: proxy, animated: true)
          }
          .labelStyle(.iconOnly)
          .froggyGlassButton(tint: FrogTheme.accent)
          .buttonBorderShape(.circle)
          .padding(16)
        }
      }
    }
    .id(transcriptIdentity)
    .safeAreaInset(edge: .bottom, spacing: 0) {
      Composer(
        model: model, dictation: dictation, importing: $importing,
        composerFocused: $composerFocused)
    }
    .navigationTitle(model.title)
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      #if os(iOS)
        ToolbarItem(placement: .principal) {
          conversationIdentity
        }
      #endif
      ToolbarItem(placement: .primaryAction) {
        Button {
          showInspector.toggle()
        } label: {
          Label("Details", systemImage: "info.circle")
        }
        #if os(iOS)
          .labelStyle(.iconOnly)
        #endif
        .accessibilityLabel("Conversation Details")
        .accessibilityHint("Shows tasks, history, sharing, memory, and editing options")
        .accessibilityIdentifier("chat.details")
        .help("Details, tasks, history, sharing, memory, and editing")
      }
    }
    .background(FrogTheme.appBackground)
    .froggyInspector(isPresented: $showInspector, onDismiss: finishInspectorAction) {
      ConversationInspector(
        model: model,
        open: openFromInspector,
        clear: {
          confirmClearFromInspector()
        },
        delete: {
          confirmDeleteFromInspector()
        })
        .inspectorColumnWidth(min: 260, ideal: 300, max: 360)
    }
    .quickLookPreview($previewURL)
    .onChange(of: previewURL) { previous, current in
      if previous != current { FrogBotAPI.removeDownloadedPreview(at: previous) }
    }
    .onDisappear {
      pendingScroll?.cancel()
      cancelPreview()
    }
    .fileImporter(
      isPresented: $importing, allowedContentTypes: [.image, .pdf, .plainText, .data],
      allowsMultipleSelection: true
    ) { result in
      if case .success(let urls) = result {
        _ = model.enqueueUpload(urls: urls, for: model.selection)
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

  private func scheduleScrollToBottom(using proxy: ScrollViewProxy, animated: Bool) {
    pendingScroll?.cancel()
    isFollowingLatest = true
    hasNewerMessages = false
    let requestedTranscript = transcriptIdentity
    pendingScroll = Task { @MainActor in
      // Let SwiftUI finish measuring newly loaded or expanded message content first.
      await Task.yield()
      guard !Task.isCancelled, transcriptIdentity == requestedTranscript else { return }
      let scroll = { proxy.scrollTo(bottomID, anchor: .bottom) }
      if animated {
        withAnimation(.snappy) { scroll() }
      } else {
        scroll()
        // Lazy message content can finish sizing on the following display pass.
        // Confirm the initial anchor so a reused offset cannot sit below the transcript.
        try? await Task.sleep(for: .milliseconds(32))
        guard !Task.isCancelled, transcriptIdentity == requestedTranscript, isFollowingLatest
        else { return }
        scroll()
      }
    }
  }

  private var conversationIdentity: some View {
    HStack(spacing: 9) {
      if let group = model.selectedGroup {
        GroupAvatar(group: group, size: 31)
      } else if let bot = model.selectedBot {
        BotAvatar(name: bot.name, color: bot.color, size: 31)
      }
      VStack(alignment: .leading, spacing: 1) {
        Text(model.title).font(.headline).lineLimit(1)
        Text(model.subtitle).font(.caption).foregroundStyle(FrogTheme.accent).lineLimit(1)
      }
    }
  }

  private func openFromInspector(_ sheet: AppSheet) {
    #if os(iOS)
      pendingInspectorAction = .open(sheet)
      showInspector = false
    #else
      present(sheet)
    #endif
  }

  private func confirmClearFromInspector() {
    #if os(iOS)
      pendingInspectorAction = .clear
      showInspector = false
    #else
      showClear = true
    #endif
  }

  private func confirmDeleteFromInspector() {
    #if os(iOS)
      pendingInspectorAction = .delete
      showInspector = false
    #else
      showDelete = true
    #endif
  }

  private func finishInspectorAction() {
    guard let action = pendingInspectorAction else { return }
    pendingInspectorAction = nil
    switch action {
    case .open(let sheet): present(sheet)
    case .clear: showClear = true
    case .delete: showDelete = true
    }
  }

  private func preview(_ attachment: Attachment) {
    cancelPreview()
    let requestID = UUID()
    previewRequestID = requestID
    let selection = model.selection
    let api = model.api
    let groupId = model.selectedGroup?.id
    previewTask = Task {
      do {
        guard let downloaded = try await api?.downloadFile(
          fileId: attachment.id, name: attachment.name, groupId: groupId)
        else { return }
        guard !Task.isCancelled, previewRequestID == requestID, model.selection == selection else {
          FrogBotAPI.removeDownloadedPreview(at: downloaded)
          return
        }
        previewURL = downloaded
      } catch {
        if !Task.isCancelled { model.present(error) }
      }
    }
  }

  private func cancelPreview() {
    previewRequestID = UUID()
    previewTask?.cancel()
    previewTask = nil
    let currentPreview = previewURL
    previewURL = nil
    FrogBotAPI.removeDownloadedPreview(at: currentPreview)
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
    .frame(maxWidth: .infinity)
  }
}

private struct ConversationInspector: View {
  @Environment(\.dismiss) private var dismiss
  @Bindable var model: AppModel
  let open: (AppSheet) -> Void
  let clear: () -> Void
  let delete: () -> Void
  @State private var botDraft = BotDraft()
  @State private var loadedBotID: String?
  @State private var savingBot = false

  var body: some View {
    NavigationStack {
      Form {
        Section {
          HStack(spacing: 12) {
            if let group = model.selectedGroup {
              GroupAvatar(group: group, size: 52)
            } else if let bot = model.selectedBot {
              BotAvatar(name: bot.name, color: bot.color, size: 52)
            }
            VStack(alignment: .leading, spacing: 3) {
              Text(model.title).font(.headline)
              Text(model.subtitle).font(.subheadline).foregroundStyle(.secondary)
            }
          }
        }

        if editingBot != nil, actions.contains("edit") {
          botEditorSections
        }

        if let group = model.selectedGroup {
          Section("People") {
            ForEach(group.members) { member in
              LabeledContent(member.name, value: member.role.capitalized)
            }
          }
          Section("Bots") {
            ForEach(group.bots) { bot in
              Label(bot.name, systemImage: "bubble.left.and.sparkles")
            }
          }
        }

        Section("Conversation") { conversationActions }

        if canClear || canDelete {
          Section {
            if canClear {
              Button("Clear Conversation", systemImage: "eraser", role: .destructive) {
                clear()
              }
              .tint(FrogTheme.danger)
              .foregroundStyle(FrogTheme.danger)
            }
            if canDelete {
              Button("Delete \(model.selectedGroup == nil ? "Bot" : "Group")", systemImage: "trash", role: .destructive) {
                delete()
              }
              .tint(FrogTheme.danger)
              .foregroundStyle(FrogTheme.danger)
            }
          }
        }
      }
      .formStyle(.grouped)
      .navigationTitle("Details")
      .toolbarTitleDisplayMode(.inline)
      .toolbar {
        #if os(iOS)
          ToolbarItem(placement: .cancellationAction) {
            Button("Close", systemImage: "xmark") { dismiss() }
              .labelStyle(.iconOnly)
          }
        #endif
        if let bot = editingBot, actions.contains("edit") {
          ToolbarItem(placement: .confirmationAction) {
            Button("Save") { save(bot) }
              .disabled(!canSaveBot)
          }
        }
      }
      .onAppear { loadBotDraftIfNeeded() }
      .onChange(of: model.selectedBot?.id) { _, _ in loadBotDraftIfNeeded(force: true) }
    }
  }

  @ViewBuilder private var botEditorSections: some View {
    Section {
      TextField("Name", text: $botDraft.name)
      TextField("What this bot does", text: $botDraft.tagline)
      VStack(alignment: .leading, spacing: 4) {
        Text("Color").font(.subheadline)
        BotColorPicker(selection: $botDraft.color, options: colorOptions)
      }
    } header: {
      Text("Identity")
    } footer: {
      Text(
        identityIssue ?? "Use a short name and a one-line description people can scan quickly."
      )
      .foregroundStyle(
        identityIssue == nil
          || botDraft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
          ? Color.secondary : Color.red)
    }

    Section {
      NavigationLink {
        BotPromptEditor(
          prompt: $botDraft.prompt,
          maximumLength: model.constraints.botPromptMaxLength)
      } label: {
        VStack(alignment: .leading, spacing: 6) {
          Label("Edit Prompt", systemImage: "text.alignleft")
            .font(.headline)
          Text(
            botDraft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              ? "Add the bot’s role, tone, boundaries, and definition of success."
              : botDraft.prompt
          )
          .font(.callout)
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
        Text(instructionsIssue ?? "Open the full prompt editor to make changes.")
        Spacer(minLength: 12)
        Text(
          "\(botDraft.prompt.count.formatted()) / \(model.constraints.botPromptMaxLength.formatted())"
        )
        .monospacedDigit()
      }
      .foregroundStyle(
        instructionsIssue == nil
          || botDraft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
          ? Color.secondary : Color.red)
    }
  }

  @ViewBuilder private var conversationActions: some View {
    if let selection = model.selection, actions.contains("schedule") {
      Button("Scheduled Tasks", systemImage: "calendar") { open(.schedules(selection)) }
      Button("Run History", systemImage: "clock.arrow.circlepath") {
        open(.scheduleRuns(selection))
      }
    }
    if let selection = model.selection, actions.contains("share") {
      Button("Share", systemImage: "square.and.arrow.up") { open(.share(selection)) }
    }
    if let bot = model.selectedBot {
      if actions.contains("documents") {
        Button("Documents", systemImage: "doc") { open(.documents(bot.id)) }
      }
      if actions.contains("browser") {
        Button("Browser", systemImage: "globe") {
          open(.browser(botId: bot.id, groupId: nil))
        }
      }
      Button("Memory", systemImage: "brain.head.profile") { open(.memories(nil)) }
      if actions.contains("edit") {
        NavigationLink {
          BotToolsAndSkillsEditor(
            draft: $botDraft,
            skills: model.bootstrap?.skills ?? [],
            tools: model.bootstrap?.tools ?? [],
            providers: model.bootstrap?.connectionProviders ?? [])
        } label: {
          Label("Tools & Skills", systemImage: "wrench.and.screwdriver")
        }
        .accessibilityIdentifier("bot.tools-and-skills")
      }
    } else if let group = model.selectedGroup {
      if actions.contains("viewMemory") || actions.contains("manageMemory") {
        Button("Group Memory", systemImage: "brain.head.profile") {
          open(.memories(group.id))
        }
      }
      if actions.contains("edit") {
        Button("Edit Group", systemImage: "pencil") { open(.groupEditor(group.id)) }
      }
    }
  }

  private var actions: Set<String> {
    Set(model.selectedBot?.allowedActions ?? model.selectedGroup?.allowedActions ?? [])
  }
  private var canClear: Bool { actions.contains("clear") }
  private var canDelete: Bool { actions.contains("delete") }

  private var editingBot: Bot? { model.selectedBot }

  private var colorOptions: [BotColorOption] {
    editingBot?.systemRole == "chief"
      ? [BotColorOption(value: "#007A3D", name: "FroggyBot green")]
      : customBotColors
  }

  private var identityIssue: String? {
    let name = botDraft.name.trimmingCharacters(in: .whitespacesAndNewlines)
    if name.isEmpty { return "Enter a bot name." }
    if botDraft.name.count > model.constraints.botNameMaxLength {
      return "Keep the name under \(model.constraints.botNameMaxLength) characters."
    }
    if botDraft.tagline.count > model.constraints.botTaglineMaxLength {
      return "Keep the description under \(model.constraints.botTaglineMaxLength) characters."
    }
    return nil
  }

  private var instructionsIssue: String? {
    if botDraft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      return "Add instructions so the bot knows how to help."
    }
    if botDraft.prompt.count > model.constraints.botPromptMaxLength {
      return "Instructions are longer than the supported limit."
    }
    return nil
  }

  private var canSaveBot: Bool {
    identityIssue == nil && instructionsIssue == nil && !savingBot
  }

  private func loadBotDraftIfNeeded(force: Bool = false) {
    guard let bot = editingBot, force || loadedBotID != bot.id else { return }
    var draft = BotDraft(bot: bot)
    let availableToolIDs = Set((model.bootstrap?.tools ?? []).map(\.id))
    draft.toolIds.removeAll { !availableToolIDs.contains($0) }
    draft.alwaysAllowedToolIds.removeAll { !availableToolIDs.contains($0) }
    botDraft = draft
    loadedBotID = bot.id
  }

  private func save(_ bot: Bot) {
    savingBot = true
    Task {
      let saved = await model.saveBot(botDraft, id: bot.id)
      if saved, let refreshed = model.bootstrap?.bots.first(where: { $0.id == bot.id }) {
        botDraft = BotDraft(bot: refreshed)
        loadedBotID = refreshed.id
      }
      savingBot = false
    }
  }
}

private struct MessageBubble: View {
  let message: ChatMessage
  @Bindable var model: AppModel
  let preview: (Attachment) -> Void
  @State private var reviewingApproval = false

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
  private var activity: [String] {
    (message.activity ?? []).filter {
      !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
  }
  private var hasBubbleContent: Bool {
    awaitingApproval || !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      || !(message.attachments ?? []).isEmpty
      || message.allowedActions?.contains("saveDecision") == true
  }
  private var showsActivity: Bool {
    let needsStandaloneStatus = !hasBubbleContent && message.status != "complete"
    return !mine && (message.isActive || !activity.isEmpty || needsStandaloneStatus)
  }
  private var isProgressOnly: Bool {
    showsActivity && !hasBubbleContent
  }
  private var timestamp: String {
    message.createdAt.froggyDate?.formatted(date: .omitted, time: .shortened) ?? ""
  }

  var body: some View {
    HStack(alignment: isProgressOnly ? .top : .bottom, spacing: 7) {
      if groupMode && !mine {
        avatar
          .padding(.top, isProgressOnly ? 2 : 0)
      }
      if mine { Spacer(minLength: 50) }
      VStack(alignment: mine ? .trailing : .leading, spacing: 3) {
        if groupMode {
          Text(mine ? "You" : authorLabel)
            .font(.caption.weight(.semibold))
            .foregroundStyle(mine ? FrogTheme.accent : FrogTheme.statusText)
            .padding(.horizontal, 6)
        } else if message.source == "schedule" {
          Text("Scheduled · \(message.scheduleName ?? "Recurring task")")
            .font(.caption.weight(.bold)).foregroundStyle(FrogTheme.statusText)
            .padding(.horizontal, 6)
        }

        if showsActivity {
          MessageActivityView(
            steps: activity,
            status: message.status,
            timestamp: isProgressOnly ? timestamp : nil)
        }

        if hasBubbleContent {
          VStack(alignment: .leading, spacing: 8) {
            if awaitingApproval {
              Label("Approval Needed", systemImage: "checkmark.shield")
                .font(.headline)
              Text(
                "This reply may use \(message.approvalTools?.joined(separator: ", ") ?? "an interactive tool") to take action."
              )
              .font(.callout).foregroundStyle(.secondary)
              Button("Review Action", systemImage: "checkmark.shield") {
                reviewingApproval = true
              }
              .buttonStyle(.borderedProminent)
            } else if !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
              MarkdownMessageView(
                message.text, expandsToFill: !mine,
                baseColor: mine ? .white : FrogTheme.textSoft)
            }

            ForEach(message.attachments ?? []) { attachment in
              Button { open(attachment) } label: {
                Label(
                  attachment.name, systemImage: attachment.kind == "image" ? "photo" : "doc")
              }
              .buttonStyle(.plain).font(.callout.weight(.semibold)).foregroundStyle(FrogTheme.accent)
            }
            if message.allowedActions?.contains("saveDecision") == true {
              Button("Save decision", systemImage: "bookmark") {
                Task { await model.saveDecision(message) }
              }
              .buttonStyle(.bordered)
              .controlSize(.small)
            }
          }
          .padding(.horizontal, 14).padding(.vertical, 10)
          .background(bubbleColor, in: bubbleShape)
          .overlay { if bubbleBorder != .clear { bubbleShape.stroke(bubbleBorder) } }
          .accessibilityIdentifier("chat.message.content.\(message.id)")
        }

        if !isProgressOnly {
          HStack(spacing: 5) {
            if message.status != "complete" {
              Label(
                message.status.replacingOccurrences(of: "_", with: " ").capitalized,
                systemImage: message.status == "error" ? "exclamationmark.circle" : "clock")
            }
            Text(timestamp)
          }
          .font(.caption).foregroundStyle(FrogTheme.statusText)
          .padding(.horizontal, 6).padding(.top, 1)
        }
      }
      .frame(maxWidth: mine ? 650 : 720, alignment: mine ? .trailing : .leading)
      if !mine { Spacer(minLength: 50) }
    }
    .frame(maxWidth: .infinity)
    .padding(.bottom, 8)
    .contextMenu {
      if !message.text.isEmpty {
        Button("Copy", systemImage: "doc.on.doc") { copyText(message.text) }
        ShareLink(item: message.text) {
          Label("Share", systemImage: "square.and.arrow.up")
        }
      }
      ForEach(message.attachments ?? []) { attachment in
        Button("Preview \(attachment.name)", systemImage: "eye") { preview(attachment) }
      }
      if message.allowedActions?.contains("saveDecision") == true {
        Button("Save Decision", systemImage: "bookmark") {
          Task { await model.saveDecision(message) }
        }
      }
    }
    .confirmationDialog(
      "Allow this action?", isPresented: $reviewingApproval, titleVisibility: .visible
    ) {
      if message.allowedActions?.contains("approveOnce") == true {
        Button("Allow Once") { Task { await model.approve(message, always: false) } }
      }
      if message.allowedActions?.contains("approveAlways") == true {
        Button("Always Allow") { Task { await model.approve(message, always: true) } }
      }
      if message.allowedActions?.contains("reject") == true {
        Button("Don’t Allow", role: .destructive) { Task { await model.reject(message) } }
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text(
        "Allowing once applies only to this reply. Always Allow saves this permission for future replies from this bot."
      )
    }
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
    if message.status == "error" { return Color.red.opacity(0.12) }
    if message.roundRole == "synthesizer" { return FrogTheme.teamBubble }
    return mine ? FrogTheme.brand : FrogTheme.assistantBubble
  }
  private var bubbleBorder: Color {
    if awaitingApproval { return FrogTheme.approvalBorder }
    if message.roundRole == "synthesizer" { return FrogTheme.teamBorder }
    return .clear
  }
  private func open(_ attachment: Attachment) {
    preview(attachment)
  }
  private func copyText(_ text: String) {
    #if os(iOS)
      UIPasteboard.general.string = text
    #else
      NSPasteboard.general.clearContents()
      NSPasteboard.general.setString(text, forType: .string)
    #endif
  }
}

enum MessageActivityPhase: Equatable {
  case running
  case queued
  case waiting
  case completed
  case failed
  case paused
  case other(String)

  init(status: String) {
    switch status.lowercased() {
    case "running", "processing", "in_progress", "streaming": self = .running
    case "pending", "queued": self = .queued
    case "waiting": self = .waiting
    case "complete", "completed", "succeeded": self = .completed
    case "error", "failed": self = .failed
    case "cancelled", "canceled", "stopped", "needs_input", "awaiting_approval": self = .paused
    default: self = .other(status)
    }
  }

  var isIndeterminate: Bool { self == .running }

  var systemImage: String {
    switch self {
    case .running: "circle.dotted"
    case .queued: "clock"
    case .waiting: "hourglass"
    case .completed: "checkmark.circle.fill"
    case .failed: "exclamationmark.circle.fill"
    case .paused: "pause.circle.fill"
    case .other: "circle"
    }
  }

  func title(stepCount: Int) -> String {
    switch self {
    case .running:
      stepCount == 0
        ? "Working…"
        : "Working · \(stepCount) \(stepCount == 1 ? "update" : "updates")"
    case .queued: "Queued"
    case .waiting: "Waiting for its turn"
    case .completed:
      "\(stepCount) \(stepCount == 1 ? "step" : "steps") completed"
    case .failed: "Couldn’t finish"
    case .paused: "Paused"
    case .other(let status):
      status.replacingOccurrences(of: "_", with: " ").capitalized
    }
  }
}

private struct MessageActivityView: View {
  let steps: [String]
  let status: String
  let timestamp: String?
  @State private var isExpanded: Bool

  init(steps: [String], status: String, timestamp: String? = nil) {
    self.steps = steps
    self.status = status
    self.timestamp = timestamp
    _isExpanded = State(initialValue: MessageActivityPhase(status: status) == .running)
  }

  private var phase: MessageActivityPhase { MessageActivityPhase(status: status) }

  var body: some View {
    Group {
      if steps.isEmpty {
        activityHeader
      } else {
        DisclosureGroup(isExpanded: $isExpanded) {
          VStack(alignment: .leading, spacing: 9) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
              HStack(alignment: .top, spacing: 8) {
                Circle()
                  .fill(stepColor(at: index))
                  .frame(width: 5, height: 5)
                  .padding(.top, 6)
                Text(formattedActivityStep(step))
                  .font(.caption)
                  .lineSpacing(2)
                  .foregroundStyle(
                    phase == .running && index == steps.indices.last
                      ? FrogTheme.textSoft : FrogTheme.statusText
                  )
                  .frame(maxWidth: .infinity, alignment: .leading)
                  .textSelection(.enabled)
                  .accessibilityIdentifier("chat.activity.step.\(index)")
              }
            }
          }
          .padding(.top, 9)
        } label: {
          activityHeader
        }
      }
    }
    .tint(FrogTheme.accent)
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .frame(maxWidth: 520, alignment: .leading)
    .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    .overlay(
      RoundedRectangle(cornerRadius: 14, style: .continuous)
        .stroke(FrogTheme.border.opacity(0.55), lineWidth: 0.5)
    )
    .padding(.horizontal, 6)
    .padding(.bottom, 4)
    .onChange(of: phase) { previous, current in
      if current == .running, !steps.isEmpty {
        withAnimation(.snappy) { isExpanded = true }
      } else if previous == .running && current != .running {
        withAnimation(.snappy) { isExpanded = false }
      }
    }
  }

  private var activityHeader: some View {
    HStack(spacing: 8) {
      if phase.isIndeterminate {
        ProgressView().controlSize(.small).tint(FrogTheme.accent)
      } else {
        Image(systemName: phase.systemImage)
      }
      Text(phase.title(stepCount: steps.count)).font(.caption.weight(.semibold))
      Spacer(minLength: 0)
      if let timestamp, !timestamp.isEmpty {
        Text(timestamp)
          .font(.caption)
          .foregroundStyle(FrogTheme.statusText)
      }
    }
    .foregroundStyle(headerColor)
    .accessibilityIdentifier("chat.progress.\(status.lowercased())")
  }

  private func stepColor(at index: Int) -> Color {
    phase == .running && index == steps.indices.last
      ? FrogTheme.accent : FrogTheme.muted.opacity(0.55)
  }

  private var headerColor: Color {
    switch phase {
    case .running: FrogTheme.accent
    case .failed: FrogTheme.danger
    default: FrogTheme.statusText
    }
  }
}

func formattedActivityStep(_ markdown: String) -> AttributedString {
  (try? AttributedString(
    markdown: markdown, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
    ?? AttributedString(markdown)
}

private struct ImportedPhoto: Transferable, Sendable {
  let url: URL

  static var transferRepresentation: some TransferRepresentation {
    FileRepresentation(importedContentType: .image) { received in
      let sourceExtension = received.file.pathExtension
      var destination = FileManager.default.temporaryDirectory
        .appendingPathComponent("FroggyBot-Photo-Source-\(UUID().uuidString)")
      if !sourceExtension.isEmpty { destination.appendPathExtension(sourceExtension) }
      do {
        try FileManager.default.copyItem(at: received.file, to: destination)
        return ImportedPhoto(url: destination)
      } catch {
        try? FileManager.default.removeItem(at: destination)
        throw error
      }
    }
  }
}

private struct Composer: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var importing: Bool
  var composerFocused: FocusState<Bool>.Binding
  @State private var showingPhotoPicker = false
  @State private var selectedPhotos: [PhotosPickerItem] = []
  @State private var dictationPrefix = ""
  @State private var dictationSelection: ConversationSelection?
  @State private var photoImportTask: Task<Void, Never>?

  var body: some View {
    VStack(spacing: 0) {
      if model.selectedGroup != nil { replyPicker }
      if !model.pendingAttachments.isEmpty { attachmentPicker }
      #if os(macOS)
        macComposer
      #else
        mobileComposer
      #endif

      if let error = dictation.errorMessage {
        Label(error, systemImage: "exclamationmark.triangle")
          .font(.caption).foregroundStyle(.red).padding(.top, 5)
      }
    }
    .padding(.horizontal, composerHorizontalPadding)
    .padding(.top, composerTopPadding)
    .padding(.bottom, composerBottomPadding)
    .frame(maxWidth: .infinity)
    .background(FrogTheme.appBackground)
    .photosPicker(
      isPresented: $showingPhotoPicker,
      selection: $selectedPhotos,
      maxSelectionCount: max(1, model.remainingAttachmentSlots),
      matching: .images,
      preferredItemEncoding: .compatible)
    .onChange(of: selectedPhotos) { _, items in
      guard !items.isEmpty else { return }
      guard let target = model.selection else {
        selectedPhotos = []
        return
      }
      let acceptedCount = model.reserveAttachmentSlots(items.count, for: target)
      guard acceptedCount > 0 else {
        selectedPhotos = []
        return
      }
      let session = model.sessionIdentifier
      photoImportTask = Task {
        await importPhotos(
          Array(items.prefix(acceptedCount)), for: target, reservedCount: acceptedCount,
          session: session)
        photoImportTask = nil
      }
    }
    .onChange(of: dictation.transcript) { _, value in
      guard !value.isEmpty, dictationSelection == model.selection, !model.isSending else { return }
      model.composerText = dictationPrefix + value
    }
    .onChange(of: dictation.isRecording) { wasRecording, isRecording in
      guard wasRecording && !isRecording else { return }
      _ = dictation.consumeTranscript()
      dictationSelection = nil
      dictationPrefix = model.composerText
    }
    .onChange(of: model.selection) { _, selection in
      guard dictationSelection != nil, dictationSelection != selection else { return }
      cancelDictation()
    }
    .dropDestination(for: URL.self) { urls, _ in
      guard !urls.isEmpty, !model.isSending, !model.isUploading,
        model.remainingAttachmentSlots > 0
      else { return false }
      return model.enqueueUpload(urls: urls, for: model.selection)
    }
    .onDisappear {
      photoImportTask?.cancel()
      photoImportTask = nil
    }
  }

  #if os(macOS)
    private var macComposer: some View {
      HStack(alignment: .bottom, spacing: 6) {
        attachmentMenu
          .menuIndicator(.hidden)
          .buttonStyle(.plain)
          .foregroundStyle(FrogTheme.accent)
          .background(.quaternary, in: Circle())
          .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
          .frame(width: 44, height: 44)

        composerTextField
          .padding(.leading, 7)
          .padding(.vertical, 10)

        if model.isSending || model.isUploading {
          sendingProgress
            .frame(width: 44, height: 44)
        }

        HStack(alignment: .bottom, spacing: 10) {
          dictationButton
            .font(.system(size: 18, weight: .medium))

          if model.canStop {
            Button {
              Task { await model.stop() }
            } label: {
              macComposerIcon("stop.fill")
            }
            .accessibilityLabel("Stop reply")
            .buttonStyle(.plain)
            .foregroundStyle(.red)
            .background(.quaternary, in: Circle())
            .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
            .frame(width: 44, height: 44)
          } else {
            Button {
              submitMessage()
            } label: {
              macComposerIcon("arrow.up")
            }
            .accessibilityLabel("Send message")
            .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
            .buttonBorderShape(.circle)
            .controlSize(.large)
            .frame(width: 44, height: 44)
            .accessibilityIdentifier("chat.send")
            .disabled(!canSubmit)
          }
        }
      }
      .padding(6)
      .frame(minHeight: 56)
      .frame(maxWidth: composerMaxWidth)
      .froggyComposerSurface()
      .animation(.snappy, value: model.canStop)
    }

    private func macComposerIcon(_ systemName: String) -> some View {
      Image(systemName: systemName)
        .font(.system(size: 18, weight: .bold))
        .frame(width: 40, height: 40)
        .contentShape(Circle())
    }
  #else
    private var mobileComposer: some View {
      HStack(alignment: .bottom, spacing: 8) {
        attachmentMenu
          .froggyGlassButton(tint: FrogTheme.accent)
          .buttonBorderShape(.circle)
          .controlSize(.large)

        HStack(alignment: .bottom, spacing: 2) {
          composerTextField
            .padding(.leading, 13)
            .padding(.vertical, 12)

          if model.isSending || model.isUploading {
            sendingProgress
              .frame(width: 32, height: 44)
          }

          dictationButton
        }
        .frame(minHeight: 51)
        .froggyComposerSurface()
        .layoutPriority(1)

        if model.canStop {
          Button("Stop reply", systemImage: "stop.circle.fill") {
            Task { await model.stop() }
          }
          .labelStyle(.iconOnly)
          .buttonStyle(.bordered)
          .buttonBorderShape(.circle)
          .controlSize(.large)
        }

        if canSubmit {
          Button("Send message", systemImage: "arrow.up") {
            submitMessage()
          }
          .labelStyle(.iconOnly)
          .font(.system(size: 17, weight: .bold))
          .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
          .buttonBorderShape(.circle)
          .controlSize(.large)
          .accessibilityIdentifier("chat.send")
          .transition(.scale.combined(with: .opacity))
        }
      }
      .frame(minHeight: 51)
      .frame(maxWidth: composerMaxWidth)
      .animation(.snappy, value: canSubmit)
    }
  #endif

  private var attachmentMenu: some View {
    Menu {
      Button("Photo Library", systemImage: "photo.on.rectangle") {
        showingPhotoPicker = true
      }
      .disabled(model.remainingAttachmentSlots == 0 || model.isSending || model.isUploading)
      Button("Choose Files", systemImage: "folder") { importing = true }
        .disabled(model.remainingAttachmentSlots == 0 || model.isSending || model.isUploading)
    } label: {
      Label("Add attachment", systemImage: "plus")
        #if os(macOS)
          .font(.system(size: 18, weight: .semibold))
          .frame(width: 40, height: 40)
          .contentShape(Circle())
        #endif
    }
    .accessibilityIdentifier("chat.attachments")
    .labelStyle(.iconOnly)
    .disabled(model.remainingAttachmentSlots == 0 || model.isSending || model.isUploading)
  }

  private var composerTextField: some View {
    TextField("Message \(model.title)", text: $model.composerText, axis: .vertical)
      .textFieldStyle(.plain)
      .font(.body)
      .lineLimit(1...6)
      .focused(composerFocused)
      .accessibilityIdentifier("chat.composer")
      .submitLabel(.send)
      .onSubmit { if canSubmit { submitMessage() } }
  }

  private var sendingProgress: some View {
    ProgressView()
      .controlSize(.small)
      .accessibilityLabel(model.isUploading ? "Uploading attachments" : "Sending")
  }

  private var composerMaxWidth: CGFloat {
    #if os(macOS)
      720
    #else
      780
    #endif
  }

  private var composerHorizontalPadding: CGFloat {
    #if os(macOS)
      18
    #else
      12
    #endif
  }

  private var composerTopPadding: CGFloat {
    #if os(macOS)
      10
    #else
      8
    #endif
  }

  private var composerBottomPadding: CGFloat {
    #if os(macOS)
      12
    #else
      9
    #endif
  }

  private var canSend: Bool {
    !model.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      || !model.pendingAttachments.isEmpty
  }

  private var canSubmit: Bool {
    canSend && !model.isSending && !model.isUploading
  }
  private var attachmentPicker: some View {
    ScrollView(.horizontal) {
      HStack(spacing: 7) {
        ForEach(model.pendingAttachments) { item in
          HStack(spacing: 7) {
            Image(systemName: "paperclip")
            Text(item.name).font(.caption.weight(.semibold)).lineLimit(1)
            Button { model.removeAttachment(item.id) } label: {
              Image(systemName: "xmark.circle.fill")
                .frame(minWidth: 44, minHeight: 44)
            }
            .buttonStyle(.plain).accessibilityLabel("Remove \(item.name)")
          }
          .padding(.leading, 11).padding(.trailing, 2).frame(minHeight: 44)
          .background(.quaternary, in: Capsule())
        }
      }
    }
    .frame(maxWidth: 780).padding(.bottom, 7)
  }
  private var replyPicker: some View {
    HStack(spacing: 10) {
      Label("Who should answer?", systemImage: "person.2")
        .font(.callout.weight(.medium))
        .foregroundStyle(FrogTheme.statusText)
      Spacer(minLength: 14)
      Picker("Who should reply", selection: replySelection) {
        Text("No Bot Reply").tag(String?.none)
        if let group = model.selectedGroup {
          if group.bots.count > 1 {
            Text("All Bots").tag(String?.some("all"))
          }
          ForEach(group.bots) { bot in
            Text(bot.name).tag(String?.some(bot.id))
          }
        }
      }
      .labelsHidden()
      .pickerStyle(.menu)
      .controlSize(.large)
      .fixedSize(horizontal: true, vertical: false)
      .tint(FrogTheme.accent)
      .accessibilityLabel("Who should reply")
      .accessibilityIdentifier("chat.replyPicker")
    }
    .frame(minHeight: 44)
    .padding(.horizontal, 12)
    .padding(.vertical, 4)
    .frame(maxWidth: composerMaxWidth)
    .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
    .overlay(
      RoundedRectangle(cornerRadius: 15, style: .continuous)
        .stroke(FrogTheme.border.opacity(0.65), lineWidth: 0.5)
    )
    .padding(.bottom, 8)
  }

  private var replySelection: Binding<String?> {
    Binding(
      get: { model.activeGroupReplyBotId },
      set: { model.groupReplyBotId = $0 })
  }

  private var dictationActionTitle: String {
    if dictation.isStarting { return "Cancel On-Device Transcription" }
    return dictation.isRecording ? "Stop On-Device Transcription" : "Start On-Device Transcription"
  }

  private var dictationButton: some View {
    Button(action: toggleDictation) {
      Group {
        if dictation.isStarting {
          ProgressView().controlSize(.small)
        } else {
          Image(systemName: dictation.isRecording ? "stop.fill" : "mic.fill")
        }
      }
      .frame(width: dictationButtonSize, height: dictationButtonSize)
      .contentShape(Circle())
    }
    #if os(macOS)
      .buttonStyle(.plain)
      .background(.quaternary, in: Circle())
      .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
    #else
      .buttonStyle(.plain)
    #endif
    .foregroundStyle(dictation.isRecording ? Color.red : Color.secondary)
    .accessibilityLabel(dictationActionTitle)
    .accessibilityValue(dictation.isRecording ? "Recording" : "")
    .accessibilityIdentifier("chat.microphone")
    .disabled(
      !dictation.isRecording && !dictation.isStarting
        && (model.isSending || model.isUploading))
  }

  private var dictationButtonSize: CGFloat {
    #if os(macOS)
      44
    #else
      44
    #endif
  }

  private func toggleDictation() {
    if !dictation.isRecording && !dictation.isStarting {
      let draft = model.composerText
      dictationPrefix = draft.isEmpty || draft.last?.isWhitespace == true ? draft : draft + " "
      dictationSelection = model.selection
    } else if dictation.isStarting {
      dictationSelection = nil
    }
    dictation.toggle()
  }

  private func submitMessage() {
    cancelDictation()
    Task { await model.send() }
  }

  private func cancelDictation() {
    dictationSelection = nil
    dictation.cancel()
    dictationPrefix = ""
  }

  @MainActor private func importPhotos(
    _ items: [PhotosPickerItem], for target: ConversationSelection, reservedCount: Int,
    session: UInt
  ) async {
    defer {
      model.releaseAttachmentSlots(reservedCount, session: session)
      selectedPhotos = []
    }
    let constraints = model.constraints
    for (index, item) in items.enumerated() {
      do {
        try Task.checkCancellation()
        guard model.sessionIdentifier == session else { return }
        guard let source = try await item.loadTransferable(type: ImportedPhoto.self) else {
          continue
        }
        defer { try? FileManager.default.removeItem(at: source.url) }
        try Task.checkCancellation()
        let displayName = items.count == 1 ? "Photo.jpg" : "Photo \(index + 1).jpg"
        let preparationTask = Task.detached(priority: .userInitiated) {
          try Task.checkCancellation()
          let data = try PhotoUploadPreparer.jpegData(
            from: source.url, maxDimension: constraints.maxPhotoDimension,
            maxBytes: constraints.imageMaxBytes)
          try Task.checkCancellation()
          let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("FroggyBot-Photo-Prepared-\(UUID().uuidString)")
          do {
            try FileManager.default.createDirectory(
              at: folder, withIntermediateDirectories: true)
            let url = folder.appendingPathComponent(displayName)
            try data.write(to: url, options: .atomic)
            try Task.checkCancellation()
            return url
          } catch {
            try? FileManager.default.removeItem(at: folder)
            throw error
          }
        }
        let prepared = try await withTaskCancellationHandler {
          try await preparationTask.value
        } onCancel: {
          preparationTask.cancel()
        }
        defer { try? FileManager.default.removeItem(at: prepared.deletingLastPathComponent()) }
        try Task.checkCancellation()
        await model.uploadReserved(urls: [prepared], for: target, session: session)
      } catch {
        if !Task.isCancelled, model.sessionIdentifier == session { model.present(error) }
        return
      }
    }
  }
}

private extension View {
  @ViewBuilder func froggyInspector<Content: View>(
    isPresented: Binding<Bool>, onDismiss: @escaping () -> Void,
    @ViewBuilder content: @escaping () -> Content
  ) -> some View {
    #if os(iOS)
      sheet(isPresented: isPresented, onDismiss: onDismiss, content: content)
    #else
      inspector(isPresented: isPresented, content: content)
    #endif
  }
}
