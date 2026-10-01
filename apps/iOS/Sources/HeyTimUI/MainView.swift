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
  @State private var showConversationInspector = false
  #if os(macOS)
    @State private var detailPath = NavigationPath()
  #endif

  public init(model: AppModel, auth: AuthSession) {
    self.model = model
    self.auth = auth
    _presentedSheet = State(initialValue: model.sheet)
  }

  public var body: some View {
    layout
    .tint(FrogTheme.accent)
    .onChange(of: model.sheet) { _, sheet in
      if sheet != nil, presentedSheet != nil || showConversationInspector {
        resetDetailNavigation()
      }
      if sheet != nil { showConversationInspector = false }
      synchronizePresentedSheet(with: sheet)
    }
    .onChange(of: model.notificationFocusRevision) { _, revision in
      guard revision > 0 else { return }
      showConversationInspector = false
      resetDetailNavigation()
      #if os(iOS)
        columns = .detailOnly
      #endif
    }
    .onChange(of: model.selection) { previous, current in
      guard previous != current else { return }
      showConversationInspector = false
      resetDetailNavigation()
    }
    .onAppear {
      guard model.notificationFocusRevision > 0 else { return }
      #if os(iOS)
        columns = .detailOnly
      #endif
    }
    .alert(
      "Hey Tim",
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
    .sheet(isPresented: $model.showAISharingConsent) {
      AISharingConsentDisclosure(
        isWorking: model.isUpdatingAISharingConsent,
        allowTitle: "Allow and Send",
        onAllow: { Task { await model.allowAISharing(sendPendingMessage: true) } },
        onCancel: { model.showAISharingConsent = false })
    }
    .onDisappear { dictation.shutDown() }
  }

  private var layout: some View {
    NavigationSplitView(columnVisibility: $columns) {
      ConversationSidebar(model: model, auth: auth) { selection in
        if presentedSheet != nil || showConversationInspector { resetDetailNavigation() }
        dictation.cancel()
        // A sidebar switch replaces the conversation and its cover together.
        // Do not animate the old Details cover across the new conversation.
        withTransaction(Transaction(animation: nil)) {
          showConversationInspector = false
          model.sheet = nil
          model.select(selection)
        }
      } present: { sheet in
        model.sheet = sheet
      }
      .navigationSplitViewColumnWidth(min: 270, ideal: 290, max: 320)
    } detail: {
      #if os(macOS)
        NavigationStack(path: $detailPath) {
          conversationDetail
            .navigationDestination(for: FeatureDestination.self) { $0.content() }
        }
        .background(FrogTheme.appBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
          RoundedRectangle(cornerRadius: 16, style: .continuous)
            .stroke(FrogTheme.subtleBorder, lineWidth: 1)
        }
        .padding(.top, 4)
        .padding(.trailing, 8)
        .padding(.bottom, 8)
        .background(FrogTheme.drawer)
      #else
        conversationDetail
      #endif
    }
    .navigationSplitViewStyle(.balanced)
    #if os(macOS)
      .toolbarBackground(FrogTheme.appBackground, for: .windowToolbar)
      .toolbarBackground(.visible, for: .windowToolbar)
    #endif
  }

  private var conversationDetail: some View {
    Group {
      if model.selection != nil {
        ConversationView(
          model: model, dictation: dictation,
          showInspector: $showConversationInspector,
          isCoveredByFeature: presentedSheet != nil)
          .id(model.selection)
      } else {
        EmptyPanel(
          icon: "bubble.left.and.bubble.right", title: "Choose a chat",
          detail: "Select a person, group, or a bot from the chat list.")
      }
    }
    .froggyFeaturePresentation(item: $presentedSheet, onDismiss: sheetDidDismiss) { sheet in
      FeatureSheet(sheet: sheet, model: model, auth: auth)
        .id(sheet.id)
    }
  }

  private func resetDetailNavigation() {
    #if os(macOS)
      // Leave any nested page when the user explicitly changes context.
      // Ordinary Back/close keeps the mounted chat and its position.
      if !detailPath.isEmpty { detailPath = NavigationPath() }
    #endif
  }

  private func synchronizePresentedSheet(with requestedSheet: AppSheet?) {
    guard presentedSheet != requestedSheet else { return }
    #if os(macOS)
      pendingSheet = nil
      presentedSheet = requestedSheet
    #else
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
    #endif
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
    return ConversationListItem.recentFirst(
      bots: bootstrap.bots, groups: bootstrap.groups,
      activeSelections: model.sidebarActiveSelections)
      .filter { searchMatch($0.name, $0.lastMessage) }
  }

  var body: some View {
    List(
      selection: Binding(
        get: { model.selection },
        set: { value in if let value { select(value) } })
    ) {
      Section("Chats") {
        ForEach(conversations) { item in
          #if os(macOS)
            // Explicit selection also closes a covered feature on a repeated click.
            Button { select(item.selection) } label: { sidebarRow(item) }
              .buttonStyle(.plain)
              .tag(item.selection)
              .accessibilityIdentifier("sidebar.title.\(item.selection.kind.rawValue).\(item.selection.id)")
          #else
            NavigationLink(value: item.selection) { sidebarRow(item) }
          #endif
        }
      }
    }
    .listStyle(.sidebar)
    .scrollContentBackground(.hidden)
    .background(FrogTheme.drawer)
    #if os(macOS)
      .safeAreaInset(edge: .bottom, spacing: 0) {
        Button { present(.account) } label: {
          Label("Settings", systemImage: "gearshape")
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            .padding(.vertical, 11)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(FrogTheme.text)
        .accessibilityIdentifier("sidebar.settings")
        .background(FrogTheme.drawer)
        .overlay(alignment: .top) { Divider() }
      }
    #endif
    .overlay {
      if conversations.isEmpty {
        ContentUnavailableView(
          search.isEmpty ? "No chats yet" : "No matches",
          systemImage: search.isEmpty ? "bubble.left.and.bubble.right" : "magnifyingglass",
          description: Text(
            search.isEmpty ? "Your chats will appear here." : "Try a different search."))
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .allowsHitTesting(false)
      }
    }
    #if os(iOS)
      .froggyNavigationTitle("Hey Tim")
      .toolbarTitleDisplayMode(.inline)
    #endif
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
              Text("Hey Tim").froggyFont(.headline).lineLimit(1)
            }
            FrogMark(size: 26)
          }
          .accessibilityElement(children: .ignore)
          .accessibilityLabel("Hey Tim")
        }
        ToolbarItem(placement: .primaryAction) {
          createMenu
        }
      #else
        ToolbarItemGroup(placement: .primaryAction) {
          createMenu
        }
      #endif
    }
    .overlay { if model.isLoading { ProgressView().tint(FrogTheme.activity) } }
  }

  private func sidebarRow(_ item: ConversationListItem) -> some View {
    conversationRow(
      selection: item.selection, name: item.name,
      preview: latestPreview(for: item), date: item.lastMessageAt.froggyDate ?? .distantPast,
      processing: isProcessing(item), processingName: processingName(for: item)
    ) {
      switch item {
      case .group(let group): GroupAvatar(group: group, size: sidebarAvatarSize)
      case .bot(let bot): BotAvatar(name: bot.name, color: bot.color, size: sidebarAvatarSize)
      }
    }
  }

  private var sidebarAvatarSize: CGFloat {
    #if os(macOS)
      28
    #else
      42
    #endif
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
        .foregroundStyle(sidebarToolbarButtonColor)
    }
    .labelStyle(.iconOnly)
    .tint(sidebarToolbarButtonColor)
    .accessibilityIdentifier("sidebar.create")
    .help("Add a bot or create a group")
  }

  private var settingsButton: some View {
    Button("Settings", systemImage: "gearshape") {
      present(.account)
    }
    .labelStyle(.iconOnly)
    .foregroundStyle(sidebarToolbarButtonColor)
    .tint(sidebarToolbarButtonColor)
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
      #if os(macOS)
        Text(name)
          .froggyFont(.body, weight: model.selection == selection ? .semibold : .regular)
          .lineLimit(1)
          .accessibilityIdentifier("sidebar.title.\(selection.kind.rawValue).\(selection.id)")
        Spacer(minLength: 4)
        if processing {
          ProgressView()
            .controlSize(.mini)
            .tint(FrogTheme.activity)
          Text("Working")
            .froggyFont(.caption)
            .foregroundStyle(FrogTheme.muted)
        }
      #else
      VStack(alignment: .leading, spacing: 3) {
        HStack(spacing: 7) {
          Text(name)
            .froggyFont(.headline)
            .lineLimit(1)
            .accessibilityIdentifier(
              "sidebar.title.\(selection.kind.rawValue).\(selection.id)")
          Spacer(minLength: 4)
          if processing {
            HStack(spacing: 5) {
              ProgressView().controlSize(.mini).tint(FrogTheme.activity)
              Text("Working").froggyFont(.caption2, weight: .semibold)
            }
            .foregroundStyle(FrogTheme.activity)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(FrogTheme.activity.opacity(colorScheme == .dark ? 0.18 : 0.11), in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(processingName ?? name) is working")
            .accessibilityIdentifier(
              "sidebar.processing.\(selection.kind.rawValue).\(selection.id)")
          } else if date != .distantPast {
            Text(date.formatted(.dateTime.month().day()))
              .froggyFont(.caption)
              .foregroundStyle(.secondary)
          }
        }
        Text(processing ? "\(processingName ?? name) is working…" : preview)
          .froggyFont(.caption)
          .foregroundStyle(processing ? FrogTheme.activity : .secondary)
          .lineLimit(1)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      #endif
    }
    .frame(minHeight: sidebarAvatarSize + 8)
    .contentShape(Rectangle())
    .accessibilityAddTraits(model.selection == selection ? .isSelected : [])
  }

  private func searchMatch(_ values: String...) -> Bool {
    search.isEmpty || values.contains { $0.localizedCaseInsensitiveContains(search) }
  }

  private func isProcessing(_ item: ConversationListItem) -> Bool {
    model.sidebarActiveSelections.contains(item.selection)
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
    return item.selection.kind == .bot ? item.name : "A bot"
  }

  private func latestPreview(for item: ConversationListItem) -> String {
    guard model.selection == item.selection,
      let message = model.messages.last(where: { !$0.text.isEmpty })
    else { return item.lastMessage }
    return message.text
  }

  private var sidebarToolbarButtonColor: Color {
    FrogTheme.accent
  }
}

struct ConversationMessageRevision: Equatable {
  let id: String
  let fingerprint: Int

  init(id: String, fingerprint: Int) {
    self.id = id
    self.fingerprint = fingerprint
  }

  init(_ message: ChatMessage) {
    id = message.id
    fingerprint = message.hashValue
  }
}

enum ConversationTranscriptUpdate: Equatable {
  case none
  case initial
  case newLatest
  case revisedLatest

  static func classify(
    previous: [ConversationMessageRevision], current: [ConversationMessageRevision]
  ) -> Self {
    guard let currentLatest = current.last else { return .none }
    guard let previousLatest = previous.last else { return .initial }
    if currentLatest.id != previousLatest.id { return .newLatest }
    if currentLatest.fingerprint != previousLatest.fingerprint { return .revisedLatest }
    return .none
  }
}

extension AppModel {
  var conversationAccentHex: String {
    ConversationStyle.accentHex(
      bot: selectedBot, group: selectedGroup, activeGroupBotID: activeGroupReplyBotId)
  }

}

#if os(macOS)
  /// Covers the detail column without adding a resizable NSSplitView inspector.
  /// An overlay does not participate in the sidebar's width negotiation, and the
  /// mounted conversation retains its draft and scroll position behind the page.
  private struct ChatCoverModifier<Cover: View>: ViewModifier {
    let isPresented: Bool
    @ViewBuilder let cover: () -> Cover
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
      content
        .opacity(isPresented ? 0 : 1)
        .allowsHitTesting(!isPresented)
        .accessibilityElement(children: .contain)
        .accessibilityHidden(isPresented)
        .overlay {
          if isPresented {
            cover()
              .frame(maxWidth: .infinity, maxHeight: .infinity)
              .background(FrogTheme.appBackground)
              .transition(reduceMotion ? .opacity : .move(edge: .trailing))
          }
        }
        .clipped()
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.22), value: isPresented)
    }
  }
#endif

private extension View {
  @ViewBuilder func froggyFeaturePresentation<Item: Identifiable, Content: View>(
    item: Binding<Item?>, onDismiss: @escaping () -> Void,
    @ViewBuilder content: @escaping (Item) -> Content
  ) -> some View {
    #if os(iOS)
      sheet(item: item, onDismiss: onDismiss, content: content)
    #else
      modifier(ChatCoverModifier(isPresented: item.wrappedValue != nil) {
        if let value = item.wrappedValue { content(value) }
      })
    #endif
  }

  @ViewBuilder func froggyUserScrollInteraction(_ action: @escaping () -> Void) -> some View {
    if #available(iOS 18.0, macOS 15.0, *) {
      onScrollPhaseChange { _, phase in
        if phase == .tracking || phase == .interacting { action() }
      }
    } else {
      simultaneousGesture(DragGesture(minimumDistance: 8).onChanged { _ in action() })
    }
  }

  @ViewBuilder func froggyScrollBottomTracking(_ action: @escaping (Bool) -> Void) -> some View {
    if #available(iOS 18.0, macOS 15.0, *) {
      onScrollGeometryChange(for: Bool.self) { geometry in
        let visibleBottom = geometry.contentOffset.y + geometry.containerSize.height
        let contentBottom = geometry.contentSize.height + geometry.contentInsets.bottom
        return visibleBottom >= contentBottom - 80
      } action: { _, isAtBottom in
        action(isAtBottom)
      }
    } else {
      self
    }
  }

  @ViewBuilder func froggyInspector<Content: View>(
    isPresented: Binding<Bool>, onDismiss: @escaping () -> Void,
    @ViewBuilder content: @escaping () -> Content
  ) -> some View {
    #if os(iOS)
      sheet(isPresented: isPresented, onDismiss: onDismiss, content: content)
    #else
      modifier(ChatCoverModifier(isPresented: isPresented.wrappedValue, cover: content))
    #endif
  }
}

private struct ConversationView: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var showInspector: Bool
  @State private var inspectorSelection: ConversationSelection?
  var isCoveredByFeature = false
  @State private var importing = false
  @State private var showDelete = false
  @State private var showClear = false
  @State private var showBrowserPanel = false
  @State private var previewURL: URL?
  @State private var previewTask: Task<Void, Never>?
  @State private var previewRequestID = UUID()
  @State private var pendingInspectorAction: InspectorAction?
  @State private var showsScrollToLatest = false
  @State private var isFollowingLatest = true
  @State private var bottomIsVisible = true
  @State private var transcriptHeight: CGFloat = 0
  @State private var pendingScroll: Task<Void, Never>?
  @FocusState private var composerFocused: Bool
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  private let bottomID = "froggy-conversation-bottom"
  private let scrollSpace = "froggy-conversation-scroll"
  private enum InspectorAction {
    case clear
    case delete
  }

  private var messageRevisions: [ConversationMessageRevision] {
    transcriptMessages.map(ConversationMessageRevision.init)
  }

  private var transcriptMessages: [ChatMessage] {
    model.messages
  }

  var body: some View {
    ScrollViewReader { proxy in
      ScrollView {
        transcriptStack
          .padding(.horizontal, 14)
          .padding(.top, transcriptMessages.isEmpty ? 0 : 24)
          .padding(.bottom, transcriptMessages.isEmpty ? 0 : 16)
          #if os(macOS)
            .frame(maxWidth: 780)
          #endif
          .frame(maxWidth: .infinity)
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
      .froggyUserScrollInteraction(stopFollowingLatest)
      .froggyScrollBottomTracking(updateBottomVisibility)
      .onAppear { scheduleScrollToBottom(using: proxy, animated: false) }
      .onChange(of: model.selection) { _, _ in
        cancelPreview()
        showBrowserPanel = false
        showsScrollToLatest = false
        isFollowingLatest = true
        composerFocused = false
        scheduleScrollToBottom(using: proxy, animated: false)
      }
      .onChange(of: messageRevisions) { previous, current in
        let update = ConversationTranscriptUpdate.classify(previous: previous, current: current)
        guard update != .none else { return }
        let userSentMessage = update == .newLatest && transcriptMessages.last?.isUser == true
        if isFollowingLatest || update == .initial || userSentMessage {
          isFollowingLatest = true
          scheduleScrollToBottom(using: proxy, animated: update == .newLatest)
        } else {
          showsScrollToLatest = true
        }
      }
      .onChange(of: model.isLoadingMessages) { wasLoading, isLoading in
        if wasLoading && !isLoading && !model.messages.isEmpty && isFollowingLatest {
          scheduleScrollToBottom(using: proxy, animated: false, settleAfterLoad: true)
        }
      }
      .overlay(alignment: .bottom) {
        if showsScrollToLatest {
          Button("Jump to Latest", systemImage: "arrow.down") {
            scheduleScrollToBottom(using: proxy, animated: true)
          }
          .labelStyle(.iconOnly)
          .froggyGlassButton()
          .buttonBorderShape(.circle)
          .controlSize(.large)
          .accessibilityIdentifier("chat.scroll-to-latest")
          .padding(.bottom, 16)
          .transition(reduceMotion ? .opacity : .scale.combined(with: .opacity))
        }
      }
      .safeAreaInset(edge: .bottom, spacing: 0) {
        Composer(
          model: model, dictation: dictation, importing: $importing,
          composerFocused: $composerFocused,
          onSubmit: {
            scheduleScrollToBottom(using: proxy, animated: true)
            Task { await model.send() }
          })
          .opacity(showsChatHeader ? 1 : 0)
          .allowsHitTesting(showsChatHeader)
          .accessibilityHidden(!showsChatHeader)
      }
    }
    .tint(FrogTheme.accent)
    .froggyNavigationTitle(model.title, isPresented: showsChatHeader, horizontalPadding: 8)
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      #if os(iOS)
        ToolbarItem(placement: .principal) {
          conversationIdentity
        }
      #endif
      #if os(macOS)
        if showsChatHeader {
          ToolbarItem(placement: .primaryAction) {
            Button("Compose", systemImage: "square.and.pencil") {
              composerFocused = true
            }
            .keyboardShortcut("k", modifiers: .command)
            .help("Compose a message (Command-K)")
          }
          if let bot = model.selectedBot, bot.allowedActions?.contains("browser") == true {
            ToolbarItem(placement: .primaryAction) { browserButton(botID: bot.id) }
          }
          ToolbarItem(placement: .primaryAction) { detailsButton }
        }
      #else
        if let bot = model.selectedBot, bot.allowedActions?.contains("browser") == true {
          ToolbarItem(placement: .primaryAction) { browserButton(botID: bot.id) }
        }
        ToolbarItem(placement: .primaryAction) { detailsButton }
      #endif
    }
    .background(FrogTheme.appBackground)
    .onChange(of: showsChatHeader) { _, isVisible in
      if !isVisible { composerFocused = false }
    }
    .froggyInspector(isPresented: $showInspector, onDismiss: finishInspectorAction) {
      if let inspectorSelection = inspectorSelection ?? model.selection {
        ConversationInspector(
          model: model, selection: inspectorSelection,
          close: { showInspector = false },
          clear: {
            confirmClearFromInspector()
          },
          delete: {
            confirmDeleteFromInspector()
          })
      }
    }
    .quickLookPreview($previewURL)
    .onChange(of: previewURL) { previous, current in
      if previous != current { HeyTimAPI.removeDownloadedPreview(at: previous) }
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
    #if os(macOS)
      .inspector(isPresented: $showBrowserPanel) {
        if let bot = model.selectedBot {
          VStack(spacing: 0) {
            HStack {
              Text("Live Browser").froggyFont(.headline)
              Spacer()
              Button("Close", systemImage: "xmark") { showBrowserPanel = false }
                .labelStyle(.iconOnly)
                .accessibilityLabel("Close browser panel")
            }
            .padding(12)
            Divider()
            BrowserHandoffView(
              model: model, botId: bot.id, groupId: nil, showsDismissButton: false)
          }
          .inspectorColumnWidth(min: 320, ideal: 440, max: 640)
        }
      }
    #endif
  }

  @ViewBuilder private var transcriptStack: some View {
    #if os(iOS)
      VStack(spacing: 0) { transcriptContent }
    #else
      LazyVStack(spacing: 0) { transcriptContent }
    #endif
  }

  @ViewBuilder private var transcriptContent: some View {
    if model.nextToken != nil {
      Button("Load Earlier Messages", systemImage: "arrow.up") {
        Task { await model.loadEarlier() }
      }
      .controlSize(.small)
      .frame(minHeight: 44)
      .padding(.bottom, 8)
    }
    if model.isLoadingMessages && transcriptMessages.isEmpty {
      ProgressView("Loading conversation…")
        .tint(FrogTheme.activity)
        .containerRelativeFrame(.vertical, alignment: .center)
    } else if transcriptMessages.isEmpty {
      emptyConversation
        .containerRelativeFrame(.vertical, alignment: .center)
    }
    ForEach(transcriptMessages) { message in
      MessageBubble(
        message: message, model: model, preview: preview,
        revise: { element in beginVisualRevision(element, from: message) },
        reply: { beginReply(to: message) })
        .id(message.id)
    }
    Color.clear
      .frame(height: 1)
      .id(bottomID)
      .onAppear { updateBottomVisibility(true) }
      .onDisappear { updateBottomVisibility(false) }
      .onGeometryChange(for: CGFloat.self) { geometry in
        geometry.frame(in: .named(scrollSpace)).minY
      } action: { bottomY in
        updateBottomVisibility(bottomY >= 0 && bottomY <= transcriptHeight + 80)
      }
  }

  private func beginVisualRevision(_ element: InlineMessageElement, from message: ChatMessage) {
    let prefix = "Revise the \(element.revisionLabel). Preserve its data unless I specify changes. "
    let available = max(
      0, min(5_500, model.constraints.messageMaxLength - model.composerText.count - prefix.count - 500))
    let visual = element.revisionContext
    let context = String(visual.prefix(available))
    let label = context.count < visual.count ? "Current visual excerpt" : "Current visual"
    let request = context.isEmpty ? prefix : "\(prefix)\n\(label): \(context)\nRequested changes: "
    model.composerText += model.composerText.isEmpty ? request : "\n\n" + request
    if model.selectedGroup != nil, message.authorType == "bot" {
      model.groupReplyBotId = message.authorId
    }
    composerFocused = true
  }

  private func beginReply(to message: ChatMessage) {
    let author = message.isUser ? "You" : (message.authorName ?? model.title)
    let excerpt = String(message.text.replacingOccurrences(of: "\n", with: " ").prefix(180))
    let quote = "> \(author): \(excerpt)\n\n"
    model.composerText += model.composerText.isEmpty ? quote : "\n\n" + quote
    if model.selectedGroup != nil, message.authorType == "bot" {
      model.groupReplyBotId = message.authorId
    }
    composerFocused = true
  }

  private func scheduleScrollToBottom(
    using proxy: ScrollViewProxy, animated: Bool, settleAfterLoad: Bool = false
  ) {
    pendingScroll?.cancel()
    isFollowingLatest = true
    let requestedSelection = model.selection
    pendingScroll = Task { @MainActor in
      // On Mac, scrollTo during the same AppKit layout cycle as a sidebar
      // selection can recursively request constraints and terminate the app.
      #if os(macOS)
        try? await Task.sleep(for: .milliseconds(60))
      #else
        await Task.yield()
      #endif
      guard !Task.isCancelled, model.selection == requestedSelection else { return }
      let scroll = {
        #if os(iOS)
          proxy.scrollTo(bottomID, anchor: .bottom)
        #else
        if let latestMessageID = transcriptMessages.last?.id {
          proxy.scrollTo(latestMessageID, anchor: .bottom)
        } else {
          proxy.scrollTo(bottomID, anchor: .bottom)
        }
        #endif
      }
      if animated && !reduceMotion {
        withAnimation(.easeOut(duration: 0.18)) { scroll() }
      } else {
        scroll()
      }
      // Newly inserted Markdown and activity rows can finish measuring after the
      // first anchor. Settle once after that layout pass without animating every
      // incremental AI update.
      try? await Task.sleep(for: .milliseconds(animated ? 220 : 40))
      guard !Task.isCancelled, model.selection == requestedSelection, isFollowingLatest
      else { return }
      scroll()
      if settleAfterLoad {
        try? await Task.sleep(for: .milliseconds(260))
        guard !Task.isCancelled, model.selection == requestedSelection, isFollowingLatest
        else { return }
        scroll()
      }
    }
  }

  private func stopFollowingLatest() {
    pendingScroll?.cancel()
    isFollowingLatest = false
    showsScrollToLatest = !bottomIsVisible
  }

  private func updateBottomVisibility(_ isAtBottom: Bool) {
    bottomIsVisible = isAtBottom
    if isAtBottom {
      isFollowingLatest = true
      showsScrollToLatest = false
    } else if !isFollowingLatest {
      showsScrollToLatest = true
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
        Text(model.title).froggyFont(.headline).lineLimit(1)
        Text(model.subtitle).froggyFont(.caption).foregroundStyle(FrogTheme.muted).lineLimit(1)
      }
    }
  }

  private var detailsButton: some View {
    Button {
      inspectorSelection = model.selection
      showInspector = true
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

  private func browserButton(botID: String) -> some View {
    Button {
      #if os(macOS)
        showBrowserPanel.toggle()
      #else
      model.sheet = .browser(botId: botID, groupId: nil)
      #endif
    } label: {
      Label("Browser", systemImage: "globe")
    }
    #if os(iOS)
      .labelStyle(.iconOnly)
    #endif
    .accessibilityLabel("Secure Browser")
    .accessibilityHint("Open the bot's live browser and take control when needed")
    .accessibilityIdentifier("chat.browser")
    .help("Secure Browser")
    #if os(macOS)
      .keyboardShortcut("b", modifiers: [.command, .shift])
    #endif
  }

  private var showsChatHeader: Bool {
    #if os(macOS)
      !showInspector && !isCoveredByFeature
    #else
      true
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
          HeyTimAPI.removeDownloadedPreview(at: downloaded)
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
    HeyTimAPI.removeDownloadedPreview(at: currentPreview)
  }

  private var emptyConversation: some View {
    VStack(spacing: 0) {
      if let bot = model.selectedBot { BotAvatar(name: bot.name, color: bot.color, size: 70) }
      Text("Start a conversation")
        .froggyFont(.title, weight: .semibold).tracking(-0.4).padding(.top, 18)
      Text("Ask \(model.title) what you would like to move forward.")
        .froggyFont(.callout).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center).padding(.top, 7)
    }
    .frame(maxWidth: .infinity)
    .padding(.horizontal, 24)
  }
}

private struct ConversationInspector: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  let close: () -> Void
  let clear: () -> Void
  let delete: () -> Void
  @Environment(\.colorScheme) private var colorScheme

  var body: some View {
    FeatureNavigation {
      Form {
        Section {
          HStack(spacing: 12) {
            if let group = selectedGroup {
              GroupAvatar(group: group, size: 52)
            } else if let bot = selectedBot {
              BotAvatar(name: bot.name, color: bot.color, size: 52)
            }
            VStack(alignment: .leading, spacing: 3) {
              Text(title).froggyFont(.headline)
              Text(subtitle).froggyFont(.subheadline).foregroundStyle(.secondary)
            }
          }
        }

        if let bot = selectedBot, actions.contains("edit") {
          Section("Bot") {
            FeatureLink {
              BotEditor(model: model, id: bot.id, showsDismissButton: false)
            } label: {
              Label {
                VStack(alignment: .leading, spacing: 3) {
                  Text("Edit Bot")
                  Text("Name, prompt, tools, and skills")
                    .froggyFont(.caption)
                    .foregroundStyle(.secondary)
                }
              } icon: {
                Image(systemName: "pencil")
              }
            }
            .accessibilityIdentifier("conversation.edit-bot")
          }
        }

        if let group = selectedGroup {
          if actions.contains("edit") {
            Section("Group") {
              FeatureLink {
                GroupEditor(model: model, id: group.id, showsDismissButton: false)
              } label: {
                Label {
                  VStack(alignment: .leading, spacing: 3) {
                    Text("Edit Group")
                    Text("Name, shared context, bots, and members")
                      .froggyFont(.caption)
                      .foregroundStyle(.secondary)
                  }
                } icon: {
                  Image(systemName: "pencil")
                }
              }
              .accessibilityIdentifier("conversation.edit-group")
            }
          }
          Section("People") {
            ForEach(group.members) { member in
              HStack(spacing: 10) {
                PersonAvatar(name: member.name, size: 28)
                Text(member.name)
                Spacer()
                Text(member.role.capitalized).foregroundStyle(.secondary)
              }
            }
          }
          Section("Bots") {
            ForEach(group.bots) { bot in
              BotIdentityLabel(
                name: bot.name, color: bot.color, detail: bot.tagline, avatarSize: 30)
                .accessibilityIdentifier("group.detail.bot.\(bot.id)")
            }
          }
        }

        Section("Conversation") { conversationActions }

        if let bot = selectedBot, actions.contains("edit") {
          Section {
            Button("Fork Conversation", systemImage: "arrow.triangle.branch") {
              Task { _ = await model.forkBotConversation(bot) }
            }
            .accessibilityIdentifier("conversation.fork")
          } footer: {
            Text("Creates a separate bot with the same settings and up to 25 recent completed text exchanges. Files and learned memory stay in this conversation.")
          }
        }

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
              Button("Delete \(selectedGroup == nil ? "Bot" : "Group")", systemImage: "trash", role: .destructive) {
                delete()
              }
              .tint(FrogTheme.danger)
              .foregroundStyle(FrogTheme.danger)
            }
          }
        }
      }
      .formStyle(.grouped)
      .froggyListSurface()
      .froggyNavigationTitle("Details")
      .toolbarTitleDisplayMode(.inline)
      .toolbar {
        #if os(macOS)
          ToolbarItem(placement: .navigation) { detailsBackButton }
        #else
          ToolbarItem(placement: .cancellationAction) { detailsBackButton }
        #endif
      }
    }
  }

  private var detailsBackButton: some View {
    Button("Back", systemImage: "chevron.backward", action: close)
      .labelStyle(.iconOnly)
      .foregroundStyle(inspectorToolbarButtonColor)
      .tint(inspectorToolbarButtonColor)
      .accessibilityIdentifier("inspector.back")
      .help("Back to chat")
  }

  private var inspectorToolbarButtonColor: Color {
    FrogTheme.accent
  }

  @ViewBuilder private var conversationActions: some View {
    FeatureLink {
      WorkspaceFilesView(model: model, selection: selection)
    } label: {
      Label("Workspace Files", systemImage: "folder")
    }
    .accessibilityIdentifier("conversation.workspace-files")
    if actions.contains("schedule") {
      FeatureLink {
        SchedulesView(model: model, selection: selection, showsDismissButton: false)
      } label: {
        Label("Scheduled Tasks", systemImage: "calendar")
      }
      .accessibilityIdentifier("conversation.schedules")
      FeatureLink {
        ScheduleRunsView(model: model, selection: selection, showsDismissButton: false)
      } label: {
        Label("Run History", systemImage: "clock.arrow.circlepath")
      }
      .accessibilityIdentifier("conversation.runs")
    }
    if actions.contains("share") {
      FeatureLink {
        ShareView(model: model, selection: selection, showsDismissButton: false)
      } label: {
        Label("Share", systemImage: "square.and.arrow.up")
      }
      .accessibilityIdentifier("conversation.share")
    }
    if let bot = selectedBot {
      FeatureLink {
        BotInboxView(model: model, botId: bot.id, showsDismissButton: false)
      } label: {
        Label("Bot Inbox", systemImage: "tray")
      }
      .accessibilityIdentifier("conversation.bot-inbox")
      if actions.contains("documents") {
        FeatureLink {
          DocumentsView(model: model, botId: bot.id, showsDismissButton: false)
        } label: {
          Label("Documents", systemImage: "doc")
        }
        .accessibilityIdentifier("conversation.documents")
      }
      if actions.contains("browser") {
        FeatureLink {
          BrowserHandoffView(
            model: model, botId: bot.id, groupId: nil, showsDismissButton: false)
        } label: {
          Label("Browser", systemImage: "globe")
        }
        .accessibilityIdentifier("conversation.browser")
      }
      FeatureLink {
        MemoriesView(
          model: model, botId: bot.id, botName: bot.name, groupId: nil,
          showsDismissButton: false)
      } label: {
        Label("Memory", systemImage: "brain.head.profile")
      }
      .accessibilityIdentifier("conversation.memory")
    } else if let group = selectedGroup {
      FeatureLink {
        GroupRoutinesView(model: model, groupId: group.id)
      } label: {
        Label("Event Routines", systemImage: "bolt.badge.clock")
      }
      .accessibilityIdentifier("conversation.event-routines")
      if actions.contains("viewMemory") || actions.contains("manageMemory") {
        FeatureLink {
          MemoriesView(model: model, groupId: group.id, showsDismissButton: false)
        } label: {
          Label("Group Memory", systemImage: "brain.head.profile")
        }
        .accessibilityIdentifier("conversation.group-memory")
      }
    }
  }

  private var selectedBot: Bot? {
    guard selection.kind == .bot else { return nil }
    return model.bootstrap?.bots.first { $0.id == selection.id }
  }
  private var selectedGroup: BotGroup? {
    guard selection.kind == .group else { return nil }
    return model.bootstrap?.groups.first { $0.id == selection.id }
  }
  private var title: String { selectedBot?.name ?? selectedGroup?.name ?? "Hey Tim" }
  private var subtitle: String {
    selectedBot?.tagline ?? selectedGroup.map {
      "\($0.bots.count) bots · \($0.members.count) people"
    } ?? ""
  }
  private var actions: Set<String> {
    Set(selectedBot?.allowedActions ?? selectedGroup?.allowedActions ?? [])
  }
  private var canClear: Bool { actions.contains("clear") }
  private var canDelete: Bool { actions.contains("delete") }

}

private struct Composer: View {
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var importing: Bool
  var composerFocused: FocusState<Bool>.Binding
  let onSubmit: () -> Void
  @State private var showingPhotoPicker = false
  @State private var showingWorkspacePicker = false
  @State private var selectedPhotos: [PhotosPickerItem] = []
  @State private var dictationPrefix = ""
  @State private var dictationSelection: ConversationSelection?
  @State private var photoImportTask: Task<Void, Never>?
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorScheme) private var colorScheme

  var body: some View {
    VStack(spacing: 0) {
      if model.selectedGroup != nil { replyPicker }
      if !model.queuedMessages.isEmpty { queuedMessageTray }
      if !model.pendingAttachments.isEmpty || !model.pendingWorkspaceFiles.isEmpty {
        attachmentPicker
      }
      #if os(macOS)
        macComposer
      #else
        mobileComposer
      #endif

      if let error = dictation.errorMessage {
        Label(error, systemImage: "exclamationmark.triangle")
          .froggyFont(.caption).foregroundStyle(.red).padding(.top, 5)
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
    .sheet(isPresented: $showingWorkspacePicker) {
      if let selection = model.selection {
        WorkspaceFilePickerView(model: model, selection: selection) { file in
          if model.selection == selection { model.addWorkspaceFile(file) }
        }
      }
    }
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
    .onChange(of: dictation.isRecording) { wasRecording, isRecording in
      guard wasRecording && !isRecording else { return }
      let transcript = dictation.consumeTranscript()
      if !transcript.isEmpty, let target = dictationSelection,
        target == model.selection, !model.isSending
      {
        let inlineLimit = max(
          0, model.constraints.messageMaxLength - dictationPrefix.count)
        if transcript.count <= inlineLimit {
          model.composerText = dictationPrefix + transcript
        } else {
          attachLongMeetingTranscript(transcript, to: target)
        }
      }
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
    private let macComposerControlSize: CGFloat = 44

    private var macComposer: some View {
      HStack(alignment: .bottom, spacing: 6) {
        attachmentMenu
          .menuIndicator(.hidden)
          .buttonStyle(.plain)
          .foregroundStyle(FrogTheme.text)
          .background(.quaternary, in: Circle())
          .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
          .frame(width: 44, height: 44)

        composerInput
          .padding(.leading, 7)
          .padding(.vertical, 10)

        if model.isSending || model.isUploading {
          sendingProgress
            .frame(width: 44, height: 44)
        }

        HStack(alignment: .bottom, spacing: 10) {
          dictationButton
            .froggyFont(size: 18, weight: .medium)

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
            .accessibilityIdentifier("chat.stop")
          }

          Button {
            submitMessage()
          } label: {
            macComposerIcon("arrow.up")
          }
          .accessibilityLabel(sendActionTitle)
          .buttonStyle(.plain)
          .foregroundStyle(
            canSubmit ? FrogTheme.brandInk : Color.secondary)
          .background(
            canSubmit ? FrogTheme.accent : Color.primary.opacity(0.08), in: Circle())
          .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
          .accessibilityIdentifier("chat.send")
          .disabled(!canSubmit)
          .keyboardShortcut(.return, modifiers: .command)
        }
      }
      .padding(6)
      .frame(minHeight: 56)
      .frame(maxWidth: composerMaxWidth)
      .froggyComposerSurface(
        tint: composerOutlineColor, backgroundTint: conversationAccent,
        focused: composerFocused.wrappedValue)
      .animation(reduceMotion ? nil : .snappy, value: model.canStop)
    }

    private func macComposerIcon(_ systemName: String) -> some View {
      Image(systemName: systemName)
        .froggyFont(size: 18, weight: .bold)
        .frame(width: macComposerControlSize, height: macComposerControlSize)
        .contentShape(Circle())
    }
  #else
    private var mobileComposer: some View {
      HStack(alignment: .bottom, spacing: 8) {
        attachmentMenu
          .froggyGlassButton()
          .buttonBorderShape(.circle)
          .controlSize(.large)

        HStack(alignment: .bottom, spacing: 2) {
          composerInput
            .padding(.leading, 13)
            .padding(.vertical, 12)

          if model.isSending || model.isUploading {
            sendingProgress
              .frame(width: 32, height: 44)
          }

          dictationButton
        }
        .frame(minHeight: 51)
        .froggyComposerSurface(
          tint: composerOutlineColor, backgroundTint: conversationAccent,
          focused: composerFocused.wrappedValue)
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
          Button(sendActionTitle, systemImage: "arrow.up") {
            submitMessage()
          }
          .labelStyle(.iconOnly)
          .froggyFont(size: 17, weight: .bold)
          .buttonStyle(.plain)
          .foregroundStyle(FrogTheme.brandInk)
          .frame(width: 44, height: 44)
          .background(FrogTheme.accent, in: Circle())
          .accessibilityIdentifier("chat.send")
          .transition(reduceMotion ? .opacity : .scale.combined(with: .opacity))
        }
      }
      .frame(minHeight: 51)
      .frame(maxWidth: composerMaxWidth)
      .animation(reduceMotion ? nil : .snappy, value: canSubmit)
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
      Button("Saved Workspace File", systemImage: "folder.badge.plus") {
        showingWorkspacePicker = true
      }
      .disabled(model.remainingAttachmentSlots == 0 || model.isSending || model.isUploading)
    } label: {
      Label("Add attachment", systemImage: "plus")
        #if os(macOS)
          .froggyFont(size: 18, weight: .semibold)
          .frame(width: macComposerControlSize, height: macComposerControlSize)
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
      .froggyFont(.body)
      .lineLimit(1...6)
      .focused(composerFocused)
      .accessibilityIdentifier("chat.composer")
      .submitLabel(.send)
      .onSubmit { if canSubmit { submitMessage() } }
  }

  @ViewBuilder private var composerInput: some View {
    if dictation.isRecording {
      DictationWaveform(levels: dictation.audioLevels)
        .frame(maxWidth: .infinity)
        .frame(height: 24)
        .accessibilityLabel("Listening to your voice")
        .accessibilityIdentifier("chat.dictation.waveform")
    } else {
      composerTextField
    }
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
      || !model.pendingWorkspaceFiles.isEmpty
  }

  private var canSubmit: Bool {
    let available = canSend && !model.isUploading
      && !dictation.isRecording && !dictation.isStarting
    return available
  }
  private var sendActionTitle: String {
    model.willQueueNextMessage ? "Queue message" : "Send message"
  }
  private var conversationAccent: Color { Color(hex: model.conversationAccentHex) }
  private var composerOutlineColor: Color {
    FrogTheme.botReadableColor(model.conversationAccentHex, scheme: colorScheme)
  }
  private var queuedMessageTray: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack(spacing: 6) {
        Image(systemName: "text.line.first.and.arrowtriangle.forward")
        Text(
          model.queuedMessages.count == 1
            ? "1 queued message" : "\(model.queuedMessages.count) queued messages"
        )
        Spacer(minLength: 8)
        Text("Sends after this reply")
          .foregroundStyle(.secondary)
      }
      .froggyFont(.caption, weight: .semibold)

      ScrollView(.horizontal) {
        HStack(spacing: 8) {
          ForEach(Array(model.queuedMessages.enumerated()), id: \.element.id) { index, message in
            queuedMessageCard(message, position: index + 1)
          }
        }
      }
      .scrollIndicators(.hidden)
    }
    .frame(maxWidth: composerMaxWidth)
    .padding(.horizontal, 10)
    .padding(.vertical, 8)
    .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
    .overlay(
      RoundedRectangle(cornerRadius: 15, style: .continuous)
        .stroke(FrogTheme.border, lineWidth: 0.75)
    )
    .padding(.bottom, 8)
    .accessibilityIdentifier("chat.queue")
  }

  private func queuedMessageCard(
    _ message: QueuedChatMessage, position: Int
  ) -> some View {
    HStack(spacing: 8) {
      VStack(alignment: .leading, spacing: 3) {
        Text("Next \(position)")
          .froggyFont(.caption, weight: .semibold)
          .foregroundStyle(FrogTheme.statusText)
        Text(message.text.isEmpty ? "Attached files" : message.text)
          .froggyFont(.callout)
          .lineLimit(2)
        if message.attachmentCount > 0 {
          Label(
            "\(message.attachmentCount) attachment\(message.attachmentCount == 1 ? "" : "s")",
            systemImage: "paperclip")
            .froggyFont(.caption)
            .foregroundStyle(.secondary)
        }
      }
      .frame(width: 170, alignment: .leading)

      Button("Edit queued message", systemImage: "pencil") {
        model.editQueuedMessage(message.id)
      }
      .labelStyle(.iconOnly)
      .buttonStyle(.plain)
      .frame(minWidth: 44, minHeight: 44)
      .accessibilityIdentifier("chat.queue.edit.\(message.id.uuidString)")

      Button("Send now and steer", systemImage: "arrow.turn.up.right") {
        Task { await model.steerQueuedMessage(message.id) }
      }
      .labelStyle(.iconOnly)
      .buttonStyle(.plain)
      .foregroundStyle(FrogTheme.accent)
      .frame(minWidth: 44, minHeight: 44)
      .disabled(model.isSending || model.isUploading)
      .accessibilityHint("Stops the current reply and sends this message now")
      .accessibilityIdentifier("chat.queue.steer.\(message.id.uuidString)")

      Button("Remove queued message", systemImage: "xmark") {
        model.discardQueuedMessage(message.id)
      }
      .labelStyle(.iconOnly)
      .buttonStyle(.plain)
      .foregroundStyle(.secondary)
      .frame(minWidth: 44, minHeight: 44)
      .accessibilityIdentifier("chat.queue.remove.\(message.id.uuidString)")
    }
    .padding(.leading, 11)
    .padding(.trailing, 3)
    .padding(.vertical, 4)
    .background(.quaternary, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    .accessibilityIdentifier("chat.queue.message.\(message.id.uuidString)")
  }
  private var attachmentPicker: some View {
    ScrollView(.horizontal) {
      HStack(spacing: 7) {
        ForEach(model.pendingAttachments) { item in
          HStack(spacing: 7) {
            Image(systemName: "paperclip")
            Text(item.name).froggyFont(.caption, weight: .semibold).lineLimit(1)
            Button { model.removeAttachment(item.id) } label: {
              Image(systemName: "xmark.circle.fill")
                .frame(minWidth: 44, minHeight: 44)
            }
            .buttonStyle(.plain).accessibilityLabel("Remove \(item.name)")
          }
          .padding(.leading, 11).padding(.trailing, 2).frame(minHeight: 44)
          .background(.quaternary, in: Capsule())
        }
        ForEach(model.pendingWorkspaceFiles) { item in
          HStack(spacing: 7) {
            Image(systemName: "folder")
            Text(item.name).froggyFont(.caption, weight: .semibold).lineLimit(1)
            Button { model.removeWorkspaceFile(item.id) } label: {
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
        .froggyFont(.callout, weight: .medium)
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
        .stroke(FrogTheme.border, lineWidth: 0.75)
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
      macComposerControlSize
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
    onSubmit()
  }

  private func cancelDictation() {
    dictationSelection = nil
    dictation.cancel()
    dictationPrefix = ""
  }

  private func attachLongMeetingTranscript(
    _ transcript: String, to target: ConversationSelection
  ) {
    let request = dictationPrefix.trimmingCharacters(in: .whitespacesAndNewlines)
    model.composerText = request.isEmpty
      ? "Turn the attached meeting transcript into concise notes, a summary outline, decisions, action items with stated owners and dates, and open questions. Separate confirmed facts from uncertain transcription. Then ask which durable takeaways I want saved to bot context."
      : request

    let directory = FileManager.default.temporaryDirectory
      .appendingPathComponent("HeyTim-Meeting-\(UUID().uuidString)", isDirectory: true)
    let file = directory.appendingPathComponent("Meeting Transcript.txt")
    let header = """
      HeyTim on-device meeting transcript
      Recorded: \(Date().formatted(.iso8601))
      Model: NVIDIA Parakeet TDT 0.6B v3

      """
    do {
      try FileManager.default.createDirectory(
        at: directory, withIntermediateDirectories: true)
      try (header + transcript).write(to: file, atomically: true, encoding: .utf8)
    } catch {
      model.composerText = dictationPrefix + transcript
      dictation.errorMessage =
        "The long transcript could not be attached. It remains in the message field so you can copy it."
      return
    }

    Task { @MainActor in
      defer { try? FileManager.default.removeItem(at: directory) }
      await model.upload(urls: [file], for: target)
    }
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
            .appendingPathComponent("Hey Tim-Photo-Prepared-\(UUID().uuidString)")
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

private struct DictationWaveform: View {
  let levels: [Float]

  var body: some View {
    Canvas { context, size in
      let barCount = max(1, Int(size.width / 7))
      let barSpacing = size.width / CGFloat(barCount)
      let recentLevels = Array(levels.suffix(barCount))
      let firstRecordedBar = barCount - recentLevels.count

      for index in 0..<barCount {
        let level = index < firstRecordedBar ? 0 : recentLevels[index - firstRecordedBar]
        let height = max(3, CGFloat(level) * size.height)
        let bar = CGRect(
          x: CGFloat(index) * barSpacing + (barSpacing - 3) / 2,
          y: (size.height - height) / 2,
          width: 3, height: height)
        context.fill(
          Path(roundedRect: bar, cornerRadius: 1.5),
          with: .color(FrogTheme.statusText.opacity(level > 0.05 ? 0.95 : 0.6)))
      }
    }
  }
}
