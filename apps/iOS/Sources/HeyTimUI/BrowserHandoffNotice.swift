import SwiftUI

#if os(macOS)
  struct ConversationBrowserLayout<Content: View>: View {
    @Bindable var model: AppModel
    @Binding var isPresented: Bool
    @ViewBuilder let content: () -> Content

    var body: some View {
      GeometryReader { geometry in
        let panelWidth = min(400, max(320, geometry.size.width * 0.42))
        HStack(spacing: 0) {
          content()
            .frame(
              width: max(0, geometry.size.width - (isPresented ? panelWidth : 0)),
              height: geometry.size.height)
          if isPresented, let bot = model.selectedBot {
            VStack(spacing: 0) {
              HStack {
                Text("Live Browser").froggyFont(.headline)
                Spacer()
                Button("Hide Browser Panel", systemImage: "xmark") { isPresented = false }
                  .labelStyle(.iconOnly)
                  .accessibilityLabel("Hide browser panel")
              }
              .padding(12)
              Divider()
              BrowserHandoffView(
                model: model, botId: bot.id, groupId: nil,
                showsDismissButton: false, isEmbedded: true)
                .id(bot.id)
            }
            .frame(width: panelWidth, height: geometry.size.height)
            .overlay(alignment: .leading) { Divider() }
          }
        }
      }
    }
  }
#endif

struct BrowserHandoffNotice: View {
  @Bindable var model: AppModel
  let botId: String
  let openBrowser: () -> Void

  private var state: BrowserState? { model.browserStates[botId] }
  private var closing: Bool { model.closingBrowserBotIDs.contains(botId) }
  private var operationInProgress: Bool {
    model.busyBrowserBotIDs.contains(botId)
      || (["opening", "resuming"].contains(state?.status ?? "") && state?.recoveryRequired == false)
  }
  private var explanation: String {
    if operationInProgress {
      return
        "A browser operation is in progress. Open Browser to check its status. Your draft is saved."
    }
    if state?.status == "expired" {
      return
        "End the expired handoff to send your message, or open Browser to reconnect. Your draft and saved logins are kept."
    }
    if state?.status == "human_control" {
      return
        "Resume the bot in Browser, or end the handoff to send your message. Your draft and saved logins are kept."
    }
    return
      "Open Browser to review the handoff, or end it before sending. Ending the handoff does not resend any task. Your draft and saved logins are kept."
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Label(
        state?.status == "expired" ? "Browser handoff expired" : "Browser handoff needs attention",
        systemImage: "globe"
      )
      .froggyFont(.callout, weight: .semibold)
      Text(explanation)
        .froggyFont(.caption)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
      HStack(spacing: 12) {
        Button("Open Browser", action: openBrowser)
          .accessibilityIdentifier("chat.browser-handoff.open")
        Button(closing ? "Ending Handoff…" : "End Browser Handoff") {
          Task { await model.endBrowserHandoff(botId: botId) }
        }
        .disabled(closing || operationInProgress)
        .accessibilityIdentifier("chat.browser-handoff.end")
      }
      .froggyFont(.caption, weight: .semibold)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding(12)
    .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 12))
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier("chat.browser-handoff")
  }
}
