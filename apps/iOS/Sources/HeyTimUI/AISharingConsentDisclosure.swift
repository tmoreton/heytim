import SwiftUI

struct AISharingConsentDisclosure: View {
  let isWorking: Bool
  let allowTitle: String
  let onAllow: () -> Void
  let onCancel: () -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        Image(systemName: "hand.raised.circle")
          .font(.system(size: 34))
          .accessibilityHidden(true)
        Text("Allow third-party AI processing?")
          .font(.title2.weight(.semibold))
        Text("To answer you, Hey Tim sends your message, attachments, selected files, relevant conversation history and memory, bot instructions, and connected tool results to OpenRouter, which routes text requests to DeepSeek or Z.AI (GLM). Image prompts and reference images may be routed through OpenRouter to OpenAI's image model.")
        Text("In a room, relevant messages, memory, decisions, and member names can be included. A room run requires permission from everyone whose content it uses.")
        Text("You can turn this off in Settings. New AI work will stop, and a running task will stop before its next provider request.")
        Link("Read the Privacy Policy", destination: URL(string: "https://heytim.ai/privacy")!)
        HStack {
          Button("Not Now", action: onCancel)
            .disabled(isWorking)
          Spacer()
          Button(action: onAllow) {
            if isWorking {
              ProgressView()
            } else {
              Text(allowTitle)
            }
          }
          .buttonStyle(.borderedProminent)
          .disabled(isWorking)
        }
      }
      .padding(24)
      .frame(maxWidth: 520)
    }
    .interactiveDismissDisabled(isWorking)
  }
}
