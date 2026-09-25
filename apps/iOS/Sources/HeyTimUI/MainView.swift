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
      #else
        conversationDetail
      #endif
    }
    .navigationSplitViewStyle(.balanced)
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
        #if os(macOS)
          // An explicit action also runs when the already-selected chat is
          // clicked, allowing it to leave a covered feature or nested page.
          Button { select(item.selection) } label: { sidebarRow(item) }
            .buttonStyle(.plain)
            .tag(item.selection)
            .accessibilityIdentifier("sidebar.title.\(item.selection.kind.rawValue).\(item.selection.id)")
        #else
          NavigationLink(value: item.selection) { sidebarRow(item) }
        #endif
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
          settingsButton
          createMenu
        }
      #endif
    }
    .overlay { if model.isLoading { ProgressView().tint(FrogTheme.activity) } }
  }

  private func sidebarRow(_ item: ConversationListItem) -> some View {
    conversationRow(
      selection: item.selection, name: item.name,
      preview: latestPreview(for: item), date: latestActivityDate(for: item),
      processing: isProcessing(item), processingName: processingName(for: item)
    ) {
      switch item {
      case .group(let group): GroupAvatar(group: group, size: 42)
      case .bot(let bot): BotAvatar(name: bot.name, color: bot.color, size: 42)
      }
    }
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
    }
    .frame(minHeight: 48)
    .contentShape(Rectangle())
    .accessibilityAddTraits(model.selection == selection ? .isSelected : [])
  }

  private func searchMatch(_ values: String...) -> Bool {
    search.isEmpty || values.contains { $0.localizedCaseInsensitiveContains(search) }
  }

  private func isProcessing(_ item: ConversationListItem) -> Bool {
    if model.sendingSelection == item.selection { return true }
    if model.selection == item.selection && model.loadedMessagesSelection == item.selection {
      return model.messages.contains(where: \.isActive)
    }
    return item.processing
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

  private func latestActivityDate(for item: ConversationListItem) -> Date {
    let sidebarDate = item.lastMessageAt.froggyDate ?? .distantPast
    guard model.selection == item.selection else { return sidebarDate }
    let visibleDate = model.messages.flatMap { message in
      [message.createdAt, message.startedAt, message.completedAt, message.activityUpdatedAt]
        .compactMap { $0?.froggyDate }
    }.max() ?? .distantPast
    return max(sidebarDate, visibleDate)
  }

  private var sidebarToolbarButtonColor: Color {
    colorScheme == .dark ? .white : FrogTheme.conversationChrome
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

private extension AppModel {
  var conversationAccentHex: String {
    ConversationStyle.accentHex(
      bot: selectedBot, group: selectedGroup, activeGroupBotID: activeGroupReplyBotId)
  }

  var conversationAccent: Color { FrogTheme.conversationChrome }
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
  #if os(macOS)
    @Environment(DesktopControlCoordinator.self) private var desktopControl
  #endif
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var showInspector: Bool
  @State private var inspectorSelection: ConversationSelection?
  var isCoveredByFeature = false
  @State private var importing = false
  @State private var showDelete = false
  @State private var showClear = false
  @State private var previewURL: URL?
  @State private var previewTask: Task<Void, Never>?
  @State private var previewRequestID = UUID()
  @State private var pendingInspectorAction: InspectorAction?
  @State private var showsScrollToLatest = false
  @State private var isFollowingLatest = true
  @State private var bottomIsVisible = true
  @State private var transcriptHeight: CGFloat = 0
  @State private var pendingScroll: Task<Void, Never>?
  @State private var localDesktopMessages: [ChatMessage] = []
  @FocusState private var composerFocused: Bool

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
    #if os(macOS)
      return (model.messages + localDesktopMessages).enumerated()
        .sorted { left, right in
          left.element.createdAt == right.element.createdAt
            ? left.offset < right.offset
            : left.element.createdAt < right.element.createdAt
        }
        .map(\.element)
    #else
      return model.messages
    #endif
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
        localDesktopMessages = []
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
          .froggyGlassButton(tint: conversationAccent)
          .buttonBorderShape(.circle)
          .controlSize(.large)
          .accessibilityIdentifier("chat.scroll-to-latest")
          .padding(.bottom, 16)
          .transition(.scale.combined(with: .opacity))
        }
      }
      .safeAreaInset(edge: .bottom, spacing: 0) {
        Composer(
          model: model, dictation: dictation, importing: $importing,
          composerFocused: $composerFocused,
          onSubmit: {
            scheduleScrollToBottom(using: proxy, animated: true)
            Task { await model.send() }
          },
          onDesktopAction: { intent in
            #if os(macOS)
              Task { await prepareDesktopAction(intent) }
            #endif
          })
          .opacity(showsChatHeader ? 1 : 0)
          .allowsHitTesting(showsChatHeader)
          .accessibilityHidden(!showsChatHeader)
      }
    }
    .tint(conversationAccent)
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
          ToolbarItem(placement: .primaryAction) { detailsButton }
        }
      #else
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
        .tint(conversationAccent)
        .containerRelativeFrame(.vertical, alignment: .center)
    } else if transcriptMessages.isEmpty {
      emptyConversation
        .containerRelativeFrame(.vertical, alignment: .center)
    }
    ForEach(transcriptMessages) { message in
      #if os(macOS)
      if localDesktopMessages.contains(where: { $0.id == message.id }) {
        MessageBubble(
          message: message, model: model, preview: preview,
          onLocalApprove: { Task { await approveDesktopAction(message.id) } },
          onLocalReject: { rejectDesktopAction(message.id) })
          .id(message.id)
      } else {
        MessageBubble(message: message, model: model, preview: preview)
          .id(message.id)
      }
      #else
        MessageBubble(message: message, model: model, preview: preview)
          .id(message.id)
      #endif
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

  #if os(macOS)
    private func prepareDesktopAction(_ intent: String) async {
      let selection = model.selection
      guard model.composerText == intent else { return }
      guard let botID = selection?.id, desktopControl.isEnabled(for: botID) else {
        appendLocalDesktopResponse(
          intent: intent,
          response: "Mac app actions are off for this bot. Turn them on in Settings and in this bot’s Tools list.",
          status: "error")
        return
      }
      if !desktopControl.permissionGranted {
        guard model.selection == selection, model.composerText == intent else { return }
        appendLocalDesktopResponse(
          intent: intent,
          response: "Mac app actions need Accessibility access. Enable Hey Tim in Mac Settings, then reopen the app and try again.",
          status: "error")
        return
      }
      let preparation = await desktopControl.prepareForChat(intent: intent)
      guard model.selection == selection, model.composerText == intent else { return }
      switch preparation {
      case .clarification(let question):
        appendLocalDesktopResponse(intent: intent, response: question, status: "complete")
        return
      case .unavailable:
        await model.send()
        return
      case .automaticAction, .proposal:
        guard let botID = selection?.id, desktopControl.isEnabled(for: botID) else {
          appendLocalDesktopResponse(
            intent: intent,
            response: "Mac app actions are no longer enabled for this bot.",
            status: "error")
          return
        }
        let now = ISO8601DateFormatter().string(from: Date())
        let resultID = UUID().uuidString
        localDesktopMessages.append(
          ChatMessage(
            id: "\(resultID)-user", role: "user", text: intent,
            createdAt: now, status: "complete"))
        model.composerText = ""
        if model.selectedBot?.actionApprovalMode != "ask"
          || desktopControl.isAlwaysAllowed(for: botID)
        {
          localDesktopMessages.append(
            ChatMessage(
              id: resultID, role: "assistant", text: "Running Mac app action…",
              createdAt: now, status: "running"))
          let result = await desktopControl.executePreparedAction()
          finishDesktopAction(
            resultID, result: result,
            succeeded: result.hasPrefix("Created the note")
              || result.hasPrefix("Mac app action completed"))
        } else {
          localDesktopMessages.append(
            ChatMessage(
              id: resultID, role: "assistant", text: "",
              approvalTools: ["Mac app actions"],
              approvalInput: desktopControl.proposedActionDescription,
              createdAt: now, status: "awaiting_approval",
              allowedActions: ["approveAlways", "reject"]))
        }
        return
      }
    }

    private func appendLocalDesktopResponse(intent: String, response: String, status: String) {
      guard model.composerText == intent else { return }
      let now = ISO8601DateFormatter().string(from: Date())
      let resultID = UUID().uuidString
      localDesktopMessages.append(
        ChatMessage(
          id: "\(resultID)-user", role: "user", text: intent,
          createdAt: now, status: "complete"))
      localDesktopMessages.append(
        ChatMessage(
          id: resultID, role: "assistant", text: response,
          createdAt: now, status: status))
      model.composerText = ""
      persistDesktopAction(resultID, result: response, outcome: status)
    }

    private func approveDesktopAction(_ id: String) async {
      guard let index = localDesktopMessages.firstIndex(where: {
        $0.id == id && $0.status == "awaiting_approval"
      }) else { return }
      guard let botID = model.selection?.id, desktopControl.isEnabled(for: botID) else {
        finishDesktopAction(
          id, result: "Mac app actions are no longer enabled for this bot.",
          succeeded: false)
        return
      }
      let approval = localDesktopMessages[index]
      guard approval.approvalInput == desktopControl.proposedActionDescription else {
        finishDesktopAction(
          id, result: "The proposed Mac action changed. Ask again to review a fresh action.",
          succeeded: false)
        return
      }
      desktopControl.allowAlways(for: botID)
      localDesktopMessages[index].status = "running"
      localDesktopMessages[index].allowedActions = nil
      let result = await desktopControl.executePreparedAction()
      finishDesktopAction(
        id, result: result,
        succeeded: result.hasPrefix("Created the note")
          || result.hasPrefix("Mac app action completed"))
    }

    private func finishDesktopAction(
      _ id: String, result: String, succeeded: Bool, outcome: String? = nil
    ) {
      guard let index = localDesktopMessages.firstIndex(where: { $0.id == id }) else { return }
      localDesktopMessages[index].text = result
      localDesktopMessages[index].approvalInput = nil
      localDesktopMessages[index].allowedActions = nil
      localDesktopMessages[index].status = succeeded ? "complete" : "error"
      persistDesktopAction(id, result: result, outcome: outcome ?? (succeeded ? "complete" : "error"))
    }

    private func rejectDesktopAction(_ id: String) {
      guard localDesktopMessages.contains(where: {
        $0.id == id && $0.status == "awaiting_approval"
      }) else { return }
      desktopControl.proposal = nil
      desktopControl.pendingNoteText = nil
      finishDesktopAction(id, result: "Mac app action canceled.", succeeded: true, outcome: "cancelled")
    }

    private func persistDesktopAction(_ id: String, result: String, outcome: String) {
      guard let selection = model.selection, selection.kind == .bot,
        let user = localDesktopMessages.first(where: { $0.id == "\(id)-user" })
      else { return }
      Task {
        do {
          try await model.requireAPI().recordDesktopAction(
            bot: selection.id, actionID: id, intent: user.text, result: result,
            occurredAt: user.createdAt, outcome: outcome)
          guard model.selection == selection else { return }
          try await model.loadMessages()
          localDesktopMessages.removeAll { $0.id == id || $0.id == "\(id)-user" }
        } catch {
          // Keep the local result visible; never claim it reached conversation history.
          if model.selection == selection { model.present(error) }
        }
      }
    }
  #endif

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
      if animated {
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
        Text(model.subtitle).froggyFont(.caption).foregroundStyle(conversationAccent).lineLimit(1)
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

  private var showsChatHeader: Bool {
    #if os(macOS)
      !showInspector && !isCoveredByFeature
    #else
      true
    #endif
  }

  private var conversationAccent: Color { model.conversationAccent }

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
        .froggyFont(.title, weight: .heavy).tracking(-0.4).padding(.top, 18)
      Text("Ask \(model.title) what you would like to move forward.")
        .froggyFont(.callout).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center).padding(.top, 7)
    }
    .frame(maxWidth: .infinity)
  }
}

private struct ConversationInspector: View {
  @Bindable var model: AppModel
  let selection: ConversationSelection
  let close: () -> Void
  let clear: () -> Void
  let delete: () -> Void
  @Environment(\.colorScheme) private var colorScheme
  @State private var botDraft = BotDraft()
  @State private var loadedBotID: String?
  @State private var savingBot = false

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

        if editingBot != nil, actions.contains("edit") {
          botEditorSections
        }

        if let group = selectedGroup {
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
        if let bot = editingBot, actions.contains("edit") {
          #if os(macOS)
            ToolbarItem(placement: .primaryAction) { detailsSaveButton(for: bot) }
          #else
            ToolbarItem(placement: .confirmationAction) { detailsSaveButton(for: bot) }
          #endif
        }
      }
      .onAppear { loadBotDraftIfNeeded() }
      .onChange(of: selectedBot?.id) { _, _ in loadBotDraftIfNeeded(force: true) }
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

  private func detailsSaveButton(for bot: Bot) -> some View {
    Button("Save") { save(bot) }
      #if os(iOS)
        .foregroundStyle(inspectorToolbarButtonColor)
        .tint(inspectorToolbarButtonColor)
      #endif
      #if os(macOS)
        .froggyGlassButton(tint: FrogTheme.accent)
      #endif
      .disabled(!canSaveBot)
      .accessibilityIdentifier("inspector.save")
  }

  private var inspectorToolbarButtonColor: Color {
    colorScheme == .dark ? .white : FrogTheme.conversationChrome
  }

  @ViewBuilder private var botEditorSections: some View {
    Section {
      TextField("Name", text: $botDraft.name)
        .accessibilityLabel("Name")
      TextField("Description", text: $botDraft.tagline)
        .accessibilityLabel("What this bot does")
      VStack(alignment: .leading, spacing: 4) {
        Text("Color").froggyFont(.subheadline)
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
      FeatureLink {
        BotPromptEditor(
          prompt: $botDraft.prompt,
          maximumLength: model.constraints.botPromptMaxLength)
      } label: {
        VStack(alignment: .leading, spacing: 6) {
          Label("Edit Prompt", systemImage: "text.alignleft")
            .froggyFont(.headline)
          Text(
            botDraft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              ? "Add the bot’s role, tone, boundaries, and definition of success."
              : botDraft.prompt
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

    Section("Capabilities") {
      FeatureLink {
        BotToolsAndSkillsEditor(
          model: model, draft: $botDraft,
          botID: editingBot?.id,
          skills: model.bootstrap?.skills ?? [],
          tools: model.bootstrap?.tools ?? [],
          providers: model.bootstrap?.connectionProviders ?? [])
      } label: {
        Label("Assign Tools & Skills", systemImage: "wrench.and.screwdriver")
      }
      .accessibilityIdentifier("bot.tools-and-skills")
    }
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
      if actions.contains("edit") {
        FeatureLink {
          GroupEditor(model: model, id: group.id, showsDismissButton: false)
        } label: {
          Label("Edit Group", systemImage: "pencil")
        }
        .accessibilityIdentifier("conversation.edit-group")
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

  private var editingBot: Bot? { selectedBot }

  private var colorOptions: [BotColorOption] {
    editingBot?.systemRole == "chief"
      ? [BotColorOption(value: "#FFBC3B", name: "Tim yellow")]
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
    identityIssue == nil && instructionsIssue == nil
      && effectiveCatalogToolIDs(draft: botDraft, skills: model.bootstrap?.skills ?? []).count
        <= (model.constraints.maxToolsPerBot ?? 12)
      && !savingBot
  }

  private func loadBotDraftIfNeeded(force: Bool = false) {
    guard let bot = editingBot, force || loadedBotID != bot.id else { return }
    var draft = BotDraft(bot: bot)
    let availableToolIDs = Set((model.bootstrap?.tools ?? []).map(\.id))
    draft.toolIds.removeAll { !availableToolIDs.contains($0) }
    draft.alwaysAllowedToolIds.removeAll { !availableToolIDs.contains($0) }
    draft.githubRepositoryAccess = draft.githubRepositoryAccess.filter {
      availableToolIDs.contains($0.key)
    }
    draft.resourceAccess = draft.resourceAccess.filter {
      availableToolIDs.contains($0.key)
    }
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
  var onLocalApprove: (() -> Void)? = nil
  var onLocalReject: (() -> Void)? = nil
  @State private var reviewingApproval = false
  @Environment(\.colorScheme) private var colorScheme

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
  private var plainAssistantMessage: Bool {
    #if os(iOS)
      botMessage && !groupMode && !mine && !awaitingApproval && message.status != "error"
        && message.roundRole != "synthesizer"
    #else
      false
    #endif
  }

  var body: some View {
    HStack(alignment: isProgressOnly ? .top : .bottom, spacing: 7) {
      #if os(macOS)
      if groupMode && !mine {
        avatar
          .padding(.top, isProgressOnly ? 2 : 0)
      }
      #endif
      if mine { Spacer(minLength: 50) }
      VStack(alignment: mine ? .trailing : .leading, spacing: 3) {
        if groupMode {
          HStack(spacing: 6) {
            #if os(iOS)
              if !mine { avatar }
            #endif
            Text(mine ? "You" : authorLabel)
              .froggyFont(.caption, weight: .semibold)
              .foregroundStyle(mine || botMessage ? messageAccent : FrogTheme.statusText)
          }
          .padding(.horizontal, plainAssistantMessage ? 0 : 6)
        } else if message.source == "email" {
          Text(
            message.emailSubject.map { "Email · \($0)" } ?? "Email"
          )
            .froggyFont(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(1)
        } else if message.source == "schedule" {
          Text("Scheduled · \(message.scheduleName ?? "Recurring task")")
            .froggyFont(.caption, weight: .bold).foregroundStyle(FrogTheme.statusText)
            .padding(.horizontal, 6)
        } else if message.source == "desktop_action" && !mine {
          Text("Mac app action")
            .froggyFont(.caption, weight: .semibold).foregroundStyle(.secondary)
        }

        if showsActivity {
          MessageActivityView(
            steps: activity,
            status: message.status,
            timestamp: isProgressOnly ? timestamp : nil,
            tint: messageAccent)
        }

        if hasBubbleContent {
          VStack(alignment: .leading, spacing: 8) {
            if awaitingApproval {
              Label("Allow This Bot’s Tools", systemImage: "checkmark.shield")
                .froggyFont(.headline)
              Text(
                "This bot is set to Ask before acting. Always Allow will cover: \(message.approvalTools?.joined(separator: ", ") ?? "this tool"). The action below will run now; later actions won’t ask again."
              )
              .froggyFont(.callout).foregroundStyle(.secondary)
              if let input = message.approvalInput {
                ScrollView {
                  Text(input).font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                }
                .frame(maxHeight: 180)
                .accessibilityLabel("Proposed tool arguments")
              }
              Button("Review Tool Access", systemImage: "checkmark.shield") {
                reviewingApproval = true
              }
              .buttonStyle(.borderedProminent)
            } else if !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
              MarkdownMessageView(
                message.text, expandsToFill: !mine,
                baseColor: FrogTheme.textSoft)
            }

            ForEach(message.attachments ?? []) { attachment in
              Button { open(attachment) } label: {
                Label(
                  attachment.name, systemImage: attachment.kind == "image" ? "photo" : "doc")
              }
              .buttonStyle(.plain).froggyFont(.callout, weight: .semibold)
              .foregroundStyle(messageAccent)
            }
            if message.allowedActions?.contains("saveDecision") == true {
              Button("Save decision", systemImage: "bookmark") {
                Task { await model.saveDecision(message) }
              }
              .buttonStyle(.bordered)
              .controlSize(.small)
            }
          }
          .frame(maxWidth: mine ? nil : .infinity, alignment: .leading)
          .padding(.horizontal, plainAssistantMessage ? 0 : 14)
          .padding(.vertical, plainAssistantMessage ? 0 : 10)
          .background(plainAssistantMessage ? Color.clear : bubbleColor, in: bubbleShape)
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
          .froggyFont(.caption).foregroundStyle(FrogTheme.statusText)
          .padding(.horizontal, 6).padding(.top, 1)
        }
      }
      #if os(iOS)
        .frame(maxWidth: mine ? 650 : .infinity, alignment: mine ? .trailing : .leading)
      #else
        .frame(maxWidth: mine ? 650 : 720, alignment: mine ? .trailing : .leading)
      #endif
      #if os(macOS)
        if !mine { Spacer(minLength: 50) }
      #endif
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
      "Always allow these tools?", isPresented: $reviewingApproval, titleVisibility: .visible
    ) {
      if message.allowedActions?.contains("approveAlways") == true {
        Button("Always Allow") {
          if let onLocalApprove { onLocalApprove() }
          else { Task { await model.approve(message, always: true) } }
        }
      } else if message.allowedActions?.contains("approveOnce") == true {
        Button("Allow Once") {
          if let onLocalApprove { onLocalApprove() }
          else { Task { await model.approve(message, always: false) } }
        }
      }
      if message.allowedActions?.contains("reject") == true {
        Button("Don’t Allow", role: .destructive) {
          if let onLocalReject { onLocalReject() }
          else { Task { await model.reject(message) } }
        }
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("Always Allow covers the bot’s currently enabled interactive tools. You can make it ask again under Tools & Skills. Newly enabled tools still ask first while the stricter setting is active.")
    }
  }

  @ViewBuilder private var avatar: some View {
    let name = message.authorName ?? (botMessage ? model.title : "Person")
    if botMessage {
      BotAvatar(name: name, color: message.authorColor ?? model.conversationAccentHex, size: 31)
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
  private var messageAccent: Color {
    if groupMode, botMessage, let authorColor = message.authorColor {
      return Color(hex: authorColor)
    }
    return model.conversationAccent
  }
  private var bubbleShape: UnevenRoundedRectangle {
    UnevenRoundedRectangle(
      topLeadingRadius: mine ? 18 : 6, bottomLeadingRadius: 18,
      bottomTrailingRadius: mine ? 6 : 18, topTrailingRadius: 18)
  }
  private var bubbleColor: Color {
    if awaitingApproval { return FrogTheme.approval }
    if message.status == "error" { return Color.red.opacity(0.12) }
    if message.roundRole == "synthesizer" {
      return FrogTheme.brand.opacity(colorScheme == .dark ? 0.18 : 0.12)
    }
    if mine { return messageAccent.opacity(colorScheme == .dark ? 0.34 : 0.18) }
    if groupMode && botMessage {
      return messageAccent.opacity(colorScheme == .dark ? 0.18 : 0.10)
    }
    return FrogTheme.assistantBubble
  }
  private var bubbleBorder: Color {
    if awaitingApproval { return FrogTheme.approvalBorder }
    if message.status == "error" { return Color.red.opacity(0.35) }
    if message.roundRole == "synthesizer" { return FrogTheme.brand.opacity(0.5) }
    if mine { return messageAccent.opacity(0.65) }
    if groupMode && botMessage { return messageAccent.opacity(0.45) }
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

  var isIndeterminate: Bool { self == .running || self == .queued }
  var isActive: Bool { self == .running || self == .queued || self == .waiting }

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
        ? "Processing…"
        : "Processing · \(stepCount) \(stepCount == 1 ? "update" : "updates")"
    case .queued: "Processing…"
    case .waiting: "Waiting for its turn"
    case .completed:
      "\(stepCount) \(stepCount == 1 ? "step" : "steps") completed"
    case .failed: "Couldn’t finish"
    case .paused: "Paused"
    case .other(let status):
      status.replacingOccurrences(of: "_", with: " ").capitalized
    }
  }

  func title(steps: [String]) -> String {
    if self == .running,
      let latest = steps.last?.trimmingCharacters(in: .whitespacesAndNewlines),
      !latest.isEmpty
    {
      return latest
    }
    return title(stepCount: steps.count)
  }
}

private struct MessageActivityView: View {
  let steps: [String]
  let status: String
  let timestamp: String?
  let tint: Color
  @State private var isExpanded: Bool

  init(steps: [String], status: String, timestamp: String? = nil, tint: Color) {
    self.steps = steps
    self.status = status
    self.timestamp = timestamp
    self.tint = tint
    _isExpanded = State(initialValue: MessageActivityPhase(status: status).isActive)
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
                  .froggyFont(.caption)
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
    .tint(tint)
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
    .onChange(of: phase) { _, current in
      if current.isActive, !steps.isEmpty {
        withAnimation(.snappy) { isExpanded = true }
      }
    }
    .onChange(of: steps.isEmpty) { wasEmpty, isEmpty in
      if wasEmpty, !isEmpty, phase.isActive {
        withAnimation(.snappy) { isExpanded = true }
      }
    }
  }

  private var activityHeader: some View {
    HStack(spacing: 8) {
      if phase.isIndeterminate {
        ProgressView().controlSize(.small).tint(tint)
      } else {
        Image(systemName: phase.systemImage)
      }
      Text(formattedActivityStep(phase.title(steps: steps)))
        .froggyFont(.caption, weight: .semibold)
      Spacer(minLength: 0)
      if let timestamp, !timestamp.isEmpty {
        Text(timestamp)
          .froggyFont(.caption)
          .foregroundStyle(FrogTheme.statusText)
      }
    }
    .foregroundStyle(headerColor)
    .accessibilityIdentifier("chat.progress.\(status.lowercased())")
  }

  private func stepColor(at index: Int) -> Color {
    phase == .running && index == steps.indices.last
      ? tint : FrogTheme.muted.opacity(0.55)
  }

  private var headerColor: Color {
    switch phase {
    case .running, .queued: tint
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
        .appendingPathComponent("Hey Tim-Photo-Source-\(UUID().uuidString)")
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
  #if os(macOS)
    @Environment(DesktopControlCoordinator.self) private var desktopControl
  #endif
  @Bindable var model: AppModel
  @Bindable var dictation: DictationModel
  @Binding var importing: Bool
  var composerFocused: FocusState<Bool>.Binding
  let onSubmit: () -> Void
  let onDesktopAction: (String) -> Void
  @State private var showingPhotoPicker = false
  @State private var showingWorkspacePicker = false
  @State private var selectedPhotos: [PhotosPickerItem] = []
  @State private var dictationPrefix = ""
  @State private var dictationSelection: ConversationSelection?
  @State private var photoImportTask: Task<Void, Never>?

  var body: some View {
    VStack(spacing: 0) {
      if model.selectedGroup != nil { replyPicker }
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
          .foregroundStyle(conversationAccent)
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
          } else {
            Button {
              submitMessage()
            } label: {
              macComposerIcon("arrow.up")
            }
            .accessibilityLabel("Send message")
            .buttonStyle(.plain)
            .foregroundStyle(canSubmit ? Color.white : Color.secondary)
            .background(
              canSubmit ? conversationAccent : Color.primary.opacity(0.08), in: Circle())
            .overlay(Circle().stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5))
            .accessibilityIdentifier("chat.send")
            .disabled(!canSubmit)
          }
        }
      }
      .padding(6)
      .frame(minHeight: 56)
      .frame(maxWidth: composerMaxWidth)
      .froggyComposerSurface(tint: composerOutlineColor)
      .animation(.snappy, value: model.canStop)
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
          .froggyGlassButton(tint: conversationAccent)
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
        .froggyComposerSurface(tint: composerOutlineColor)
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
          .froggyFont(size: 17, weight: .bold)
          .froggyGlassButton(prominent: true, tint: conversationAccent)
          .foregroundStyle(.white)
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
    let available = canSend && !model.isSending && !model.isUploading
      && !dictation.isRecording && !dictation.isStarting
    return available
  }
  private var conversationAccent: Color { model.conversationAccent }
  private var composerOutlineColor: Color { Color(hex: model.conversationAccentHex) }
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
      .tint(conversationAccent)
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
        .stroke(conversationAccent.opacity(0.5), lineWidth: 0.75)
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
    #if os(macOS)
      let draft = model.composerText
      let destination = model.selection
      let explicitNotesAction = DesktopControlCoordinator.noteCreationCandidate(draft)
        && DesktopControlCoordinator.targetsAppleNotes(draft.lowercased())
      if destination?.kind == .bot,
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        model.pendingAttachments.isEmpty, model.pendingWorkspaceFiles.isEmpty,
        explicitNotesAction,
        let botID = destination?.id,
        !desktopControl.isEnabled(for: botID)
      {
        onDesktopAction(draft)
        return
      }
      if destination?.kind == .bot,
        let botID = destination?.id,
        desktopControl.isEnabled(for: botID),
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        model.pendingAttachments.isEmpty, model.pendingWorkspaceFiles.isEmpty
      {
        if DesktopControlCoordinator.shouldOfferDesktopAction(for: draft) {
          desktopControl.refreshApplications()
          onDesktopAction(draft)
          return
        }
      }
    #endif
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
