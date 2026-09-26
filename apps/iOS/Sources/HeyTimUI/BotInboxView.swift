import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

struct BotInboxView: View {
  @Bindable var model: AppModel
  let botId: String
  var showsDismissButton = true

  @State private var page: BotInboxPage?
  @State private var loading = false
  @State private var working = false
  @State private var errorMessage: String?
  @State private var showsDisableConfirmation = false
  @State private var showsRotateConfirmation = false
  @State private var showsDraftConfirmation = false
  @State private var showsDeleteConfirmation = false
  @State private var showsProcessedEmail = false
  @State private var pendingDiscussion: BotInboxMessage?
  @State private var pendingDeletion: BotInboxMessage?
  @State private var incomingMode = "review"
  @State private var responseMode = "appOnly"

  var body: some View {
    Form {
      Section {
        if let page, page.available, page.enabled, let address = page.address {
          Text(address).textSelection(.enabled).froggyFont(.body)
          Button("Copy address", systemImage: "doc.on.doc") { copy(address) }
          Button("Replace address", systemImage: "arrow.triangle.2.circlepath") {
            showsRotateConfirmation = true
          }
          .disabled(working)
          Button("Turn off inbox", systemImage: "envelope.badge.shield.half.filled", role: .destructive) {
            showsDisableConfirmation = true
          }
          .disabled(working)
        } else if page?.available == true {
          Button("Turn on inbox", systemImage: "envelope") { Task { await enable() } }
            .disabled(working)
        } else if page != nil {
          Text("Bot email is being set up. You can review email here once it is ready.")
            .foregroundStyle(.secondary)
        }
      } header: {
        Text("Address")
      } footer: {
        Text("Incoming email is saved here. Choose below whether your bot uses verified messages automatically. Replacing the address stops delivery to the old address.")
      }

      if page?.enabled == true {
        Section {
          Picker("New email conversations", selection: $incomingMode) {
            Text("Review before using").tag("review")
            Text("Send to bot automatically").tag("automatic")
          }
          Picker("Bot responses", selection: $responseMode) {
            Text("In the app only").tag("appOnly")
            Text("Reply to email conversations").tag("emailReplies")
            Text("Email every response").tag("allResponses")
          }
          if let sender = page?.allowedSender {
            LabeledContent("Allowed sender", value: sender)
          }
          Button("Save email preferences") {
            Task { await savePreferences() }
          }
          .disabled(working || !preferencesChanged)
        } header: {
          Text("Email behavior")
        } footer: {
          Text("Replies to an existing bot email continue automatically when they come from your verified sign-in email and pass email authentication. This setting controls new email conversations. Enabled tools follow the bot’s Action approvals setting.")
        }
      }

      if page != nil {
        Section {
          if pendingMessages.isEmpty {
            ContentUnavailableView(
              "All Caught Up", systemImage: "checkmark.circle",
              description: Text("No email needs review. Processed conversations appear in chat history."))
              .frame(maxWidth: .infinity, minHeight: 220)
          } else {
            ForEach(pendingMessages) { message in
              inboxMessageRow(message)
            }
          }
        } header: {
          Text("Needs review")
        } footer: {
          if !pendingMessages.isEmpty {
            Text("Open an email in chat to create a draft you can review before sending to the bot.")
          }
        }

        if !processedMessages.isEmpty {
          Section {
            DisclosureGroup(isExpanded: $showsProcessedEmail) {
              ForEach(processedMessages) { message in
                inboxMessageRow(message)
              }
            } label: {
              Label(
                "Processed email (\(processedMessages.count))",
                systemImage: "checkmark.circle.fill")
            }
          } footer: {
            Text("These messages are already part of chat history. This collapsed list is an inbox audit copy.")
          }
        }

        if page?.nextToken != nil {
          Section {
            Button("Load earlier email") { Task { await load(earlier: true) } }
              .disabled(loading)
          }
        }
      } else if !loading {
        Section("Needs review") {
          ContentUnavailableView(
            "Inbox Unavailable", systemImage: "tray",
            description: Text("Refresh to load this bot’s email inbox."))
            .frame(maxWidth: .infinity, minHeight: 260)
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle("Bot Inbox")
    .toolbarTitleDisplayMode(.inline)
    .toolbar {
      if showsDismissButton { CloseButton { model.sheet = nil } }
      ToolbarItem(placement: .automatic) {
        Button("Refresh", systemImage: "arrow.clockwise") { Task { await load() } }
          .disabled(loading)
      }
    }
    .overlay {
      if loading && page == nil {
        ProgressView("Loading inbox…")
      } else if let errorMessage, page == nil {
        ContentUnavailableView {
          Label("Couldn’t Load Inbox", systemImage: "wifi.exclamationmark")
        } description: {
          Text(errorMessage)
        } actions: {
          Button("Try Again") { Task { await load() } }
        }
      }
    }
    .confirmationDialog("Turn off this inbox?", isPresented: $showsDisableConfirmation) {
      Button("Turn off inbox", role: .destructive) { Task { await disable() } }
    } message: {
      Text("New email to this address will stop appearing. Existing email stays in your inbox.")
    }
    .confirmationDialog("Replace this email address?", isPresented: $showsRotateConfirmation) {
      Button("Replace address", role: .destructive) { Task { await rotate() } }
    } message: {
      Text("People using the old address will need the new one to reach this bot.")
    }
    .confirmationDialog("Replace your unsent draft?", isPresented: $showsDraftConfirmation) {
      Button("Replace draft", role: .destructive) {
        if let pendingDiscussion { useInChat(pendingDiscussion) }
        pendingDiscussion = nil
      }
      Button("Keep draft", role: .cancel) { pendingDiscussion = nil }
    } message: {
      Text("Your current draft will be replaced with the email text.")
    }
    .confirmationDialog("Delete this inbox copy?", isPresented: $showsDeleteConfirmation) {
      Button("Delete inbox copy", role: .destructive) {
        if let pendingDeletion {
          Task {
            await delete(pendingDeletion)
            self.pendingDeletion = nil
          }
        }
      }
      Button("Cancel", role: .cancel) { pendingDeletion = nil }
    } message: {
      Text(
        pendingDeletion?.linkedTurnId == nil
          ? "This email has not been added to chat."
          : "The related bot conversation will stay in chat history.")
    }
    .refreshable { await load() }
    .task { await load() }
  }

  private static func displayDate(_ value: String) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let date = formatter.date(from: value) else { return value }
    return date.formatted(date: .abbreviated, time: .shortened)
  }

  private var preferencesChanged: Bool {
    incomingMode != (page?.incomingMode ?? "review")
      || responseMode != (page?.responseMode ?? "appOnly")
  }

  private var pendingMessages: [BotInboxMessage] {
    page?.messages.filter { $0.linkedTurnId == nil } ?? []
  }

  private var processedMessages: [BotInboxMessage] {
    page?.messages.filter { $0.linkedTurnId != nil } ?? []
  }

  private func inboxMessageRow(_ message: BotInboxMessage) -> some View {
    DisclosureGroup {
      VStack(alignment: .leading, spacing: 12) {
        Text("From: \(message.from)").froggyFont(.subheadline)
        if message.linkedTurnId == nil {
          Label(reviewExplanation(for: message), systemImage: "exclamationmark.shield")
            .froggyFont(.caption).foregroundStyle(.secondary)
        }
        Text(message.body).textSelection(.enabled).froggyFont(.body)
        if !message.attachmentNames.isEmpty {
          Text("Attachments: \(message.attachmentNames.joined(separator: ", "))")
            .froggyFont(.caption).foregroundStyle(.secondary)
          Text("Attachments are listed but cannot be opened here yet.")
            .froggyFont(.caption).foregroundStyle(.secondary)
        }
        if message.linkedTurnId != nil {
          Label(
            message.disposition == "automatic"
              ? "Sent to bot automatically" : "Added to bot conversation",
            systemImage: message.disposition == "automatic" ? "bolt.fill" : "checkmark.circle.fill"
          )
          .froggyFont(.caption).foregroundStyle(.secondary)
          Button("View in chat", systemImage: "bubble.left.and.bubble.right") {
            openChat()
          }
        } else {
          Button("Open in chat", systemImage: "bubble.left") {
            discuss(message)
          }
          Text("Creates a draft for you to review before sending.")
            .froggyFont(.caption).foregroundStyle(.secondary)
        }
        Button("Delete inbox copy", systemImage: "trash", role: .destructive) {
          pendingDeletion = message
          showsDeleteConfirmation = true
        }
        .disabled(working)
      }
      .padding(.vertical, 8)
    } label: {
      VStack(alignment: .leading, spacing: 3) {
        Text(message.subject).froggyFont(.headline)
        Text(message.from).froggyFont(.subheadline).foregroundStyle(.secondary)
        Text(Self.displayDate(message.receivedAt))
          .froggyFont(.caption).foregroundStyle(.secondary)
      }
      .padding(.vertical, 3)
    }
  }

  private func reviewExplanation(for message: BotInboxMessage) -> String {
    if message.authentication != "verified" {
      return "Sender identity could not be verified"
    }
    switch message.reviewReason {
    case "browser_active":
      return "Waiting because this bot was active in the browser"
    case "bot_busy":
      return "Waiting because the bot stayed busy"
    case "settings_changed":
      return "Waiting because email settings changed"
    default:
      return "Waiting for your review"
    }
  }

  private func copy(_ address: String) {
    #if os(iOS)
      UIPasteboard.general.string = address
    #elseif os(macOS)
      NSPasteboard.general.clearContents()
      NSPasteboard.general.setString(address, forType: .string)
    #endif
  }

  private func discuss(_ message: BotInboxMessage) {
    model.select(.init(kind: .bot, id: botId))
    if !model.composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      pendingDiscussion = message
      showsDraftConfirmation = true
    } else {
      useInChat(message)
    }
  }

  private func openChat() {
    model.select(.init(kind: .bot, id: botId))
    model.sheet = nil
  }

  private func useInChat(_ message: BotInboxMessage) {
    model.composerText = message.draftText
    model.composerInboxMessageId = message.id
    model.sheet = nil
  }

  private func load(earlier: Bool = false) async {
    guard let api = model.api else { return }
    loading = true
    defer { loading = false }
    do {
      let next = try await api.botInbox(botId, cursor: earlier ? page?.nextToken : nil)
      if earlier, let current = page {
        page = BotInboxPage(
          available: next.available, enabled: next.enabled, address: next.address,
          messages: current.messages + next.messages, nextToken: next.nextToken,
          incomingMode: next.incomingMode, responseMode: next.responseMode,
          allowedSender: next.allowedSender)
      } else {
        page = next
        incomingMode = next.incomingMode ?? "review"
        responseMode = next.responseMode ?? "appOnly"
      }
      errorMessage = nil
    } catch {
      if page == nil { errorMessage = error.localizedDescription }
      else { model.present(error) }
    }
  }

  private func enable() async {
    await change { try await $0.enableBotInbox(botId) }
  }

  private func disable() async {
    await change { try await $0.disableBotInbox(botId) }
  }

  private func rotate() async {
    await change { try await $0.rotateBotInbox(botId) }
  }

  private func savePreferences() async {
    await change {
      try await $0.updateBotEmailPreferences(
        botId, incomingMode: incomingMode, responseMode: responseMode)
    }
  }

  private func change(_ action: (HeyTimAPI) async throws -> BotInboxState) async {
    guard let api = model.api else { return }
    working = true
    defer { working = false }
    do {
      _ = try await action(api)
      await load()
      await model.refreshBootstrap()
    } catch { model.present(error) }
  }

  private func delete(_ message: BotInboxMessage) async {
    guard let api = model.api else { return }
    working = true
    defer { working = false }
    do {
      try await api.deleteBotInboxMessage(message.id, botId: botId)
      await load()
    } catch { model.present(error) }
  }
}
