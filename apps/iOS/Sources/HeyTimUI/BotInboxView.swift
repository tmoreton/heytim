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
  @State private var pendingDiscussion: BotInboxMessage?
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
          Picker("Incoming messages", selection: $incomingMode) {
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
          Text("Automatic messages run only when they come from your verified sign-in email and pass email authentication. Approvals still require the app.")
        }
      }

      Section("Received email") {
        if let messages = page?.messages, !messages.isEmpty {
          ForEach(messages) { message in
            DisclosureGroup {
              VStack(alignment: .leading, spacing: 12) {
                Text("From: \(message.from)").froggyFont(.subheadline)
                if message.authentication != "verified" {
                  Label("Sender identity could not be verified", systemImage: "exclamationmark.shield")
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
                } else {
                  Button("Discuss with bot", systemImage: "bubble.left") {
                    discuss(message)
                  }
                }
                Button("Delete email", systemImage: "trash", role: .destructive) {
                  Task { await delete(message) }
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
          if page?.nextToken != nil {
            Button("Load earlier email") { Task { await load(earlier: true) } }
              .disabled(loading)
          }
        } else if page != nil {
          ContentUnavailableView(
            "No Email Yet", systemImage: "tray",
            description: Text("Messages sent to this bot’s address will appear here."))
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
