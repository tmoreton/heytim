import Foundation
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct MessageBubble: View {
  let message: ChatMessage
  @Bindable var model: AppModel
  let preview: (Attachment) -> Void
  let revise: (InlineMessageElement) -> Void
  let reply: () -> Void
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
    false
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
              .foregroundStyle(FrogTheme.statusText)
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
            timestamp: isProgressOnly ? timestamp : nil)
        }

        if hasBubbleContent {
          VStack(alignment: .leading, spacing: 8) {
            if awaitingApproval {
              Label(message.allowedActions?.contains("approveAlways") == true
                ? "Allow This Bot’s Tools" : "Approve This Action", systemImage: "checkmark.shield")
                .froggyFont(.headline)
              Text(
                message.allowedActions?.contains("approveAlways") == true
                  ? "This bot is set to Ask before acting. Always Allow will cover: \(message.approvalTools?.joined(separator: ", ") ?? "this tool"). The action below will run now; later actions won’t ask again."
                  : "Review the exact action below. Each new email or schedule needs approval; an active schedule sends future results automatically."
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
              Button(message.allowedActions?.contains("approveAlways") == true
                ? "Review Tool Access" : "Review Action", systemImage: "checkmark.shield") {
                reviewingApproval = true
              }
              .froggyGlassButton(prominent: true)
            } else if !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
              MarkdownMessageView(
                message.text, expandsToFill: !mine,
                baseColor: FrogTheme.textSoft,
                accentColor: FrogTheme.accent,
                onRevise: revise)
            }

            ForEach(message.attachments ?? []) { attachment in
              Button { open(attachment) } label: {
                Label(
                  attachment.name, systemImage: attachment.kind == "image" ? "photo" : "doc")
              }
              .buttonStyle(.plain).froggyFont(.callout, weight: .semibold)
              .foregroundStyle(FrogTheme.accent)
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

        if let usage = message.usageSummary, !mine {
          ModelUsageCaption(usage: usage)
            .padding(.horizontal, 6)
            .padding(.top, 2)
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
        Button("Reply", systemImage: "arrowshape.turn.up.left") { reply() }
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
      message.allowedActions?.contains("approveAlways") == true
        ? "Always allow these tools?" : "Approve this action?",
      isPresented: $reviewingApproval, titleVisibility: .visible
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
    botMessage ? Color(hex: messageAccentHex) : FrogTheme.accent
  }
  private var messageReadableAccent: Color {
    botMessage
      ? FrogTheme.botReadableColor(messageAccentHex, scheme: colorScheme)
      : FrogTheme.accent
  }
  private var messageAccentHex: String {
    if groupMode, botMessage, let authorColor = message.authorColor { return authorColor }
    return model.conversationAccentHex
  }
  private var bubbleShape: UnevenRoundedRectangle {
    UnevenRoundedRectangle(
      topLeadingRadius: mine ? 18 : 6, bottomLeadingRadius: 18,
      bottomTrailingRadius: mine ? 6 : 18, topTrailingRadius: 18)
  }
  private var bubbleColor: Color {
    if awaitingApproval { return FrogTheme.approval }
    if message.status == "error" { return Color.red.opacity(0.12) }
    if botMessage { return messageAccent.opacity(colorScheme == .dark ? 0.18 : 0.10) }
    return FrogTheme.assistantBubble
  }
  private var bubbleBorder: Color {
    if awaitingApproval { return FrogTheme.approvalBorder }
    if message.status == "error" { return Color.red.opacity(0.35) }
    if botMessage { return messageReadableAccent.opacity(colorScheme == .dark ? 0.52 : 0.75) }
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

private struct ModelUsageCaption: View {
  let usage: ChatUsageSummary

  private var costLabel: String {
    guard let amount = Decimal(string: usage.costUsd) else { return "Cost unavailable" }
    let cost = NSDecimalNumber(decimal: amount).doubleValue
    if usage.costIncomplete { return "Partial provider cost" }
    if cost > 0 && cost < 0.0001 { return "Est. provider cost < $0.0001" }
    return String(format: "Est. provider cost $%.4f", cost)
  }

  var body: some View {
    Text("\(effortLabel) · \(costLabel)")
      .froggyFont(.caption)
      .foregroundStyle(FrogTheme.statusText)
      .textSelection(.enabled)
      .accessibilityLabel("Latest model run: \(effortLabel), \(costLabel)")
      .help(usage.costBasis == "provider_reported"
        ? "Provider reported cost for the latest model run."
        : "Estimated model cost for the latest model run.")
      .accessibilityIdentifier("chat.message.usage")
  }

  private var effortLabel: String {
    guard let effort = usage.reasoningEffort else { return "Reasoning" }
    return "\(effort.capitalized) reasoning"
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
  @State private var isExpanded: Bool
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  init(steps: [String], status: String, timestamp: String? = nil) {
    self.steps = steps
    self.status = status
    self.timestamp = timestamp
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
    .tint(FrogTheme.activity)
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
        withAnimation(reduceMotion ? nil : .snappy) { isExpanded = true }
      }
    }
    .onChange(of: steps.isEmpty) { wasEmpty, isEmpty in
      if wasEmpty, !isEmpty, phase.isActive {
        withAnimation(reduceMotion ? nil : .snappy) { isExpanded = true }
      }
    }
  }

  private var activityHeader: some View {
    HStack(spacing: 8) {
      if phase.isIndeterminate {
        ProgressView().controlSize(.small).tint(FrogTheme.activity)
      } else {
        Image(systemName: phase.systemImage)
          .foregroundStyle(phase == .failed ? FrogTheme.danger : FrogTheme.activity)
      }
      Text(formattedActivityStep(phase.title(steps: steps)))
        .froggyFont(.caption, weight: .semibold)
        .foregroundStyle(FrogTheme.textSoft)
      Spacer(minLength: 0)
      if let timestamp, !timestamp.isEmpty {
        Text(timestamp)
          .froggyFont(.caption)
          .foregroundStyle(FrogTheme.statusText)
      }
    }
    .accessibilityIdentifier("chat.progress.\(status.lowercased())")
  }

  private func stepColor(at index: Int) -> Color {
    phase == .running && index == steps.indices.last
      ? FrogTheme.activity : FrogTheme.statusText
  }
}

func formattedActivityStep(_ markdown: String) -> AttributedString {
  (try? AttributedString(
    markdown: markdown, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
    ?? AttributedString(markdown)
}

struct ImportedPhoto: Transferable, Sendable {
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
