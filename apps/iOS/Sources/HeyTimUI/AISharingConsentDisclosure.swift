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

struct AIProcessingSetupView: View {
  let isWorking: Bool
  let errorMessage: String?
  let onAllow: () -> Void
  let onLater: () -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 22) {
        Image(systemName: "sparkles")
          .font(.system(size: 28, weight: .medium))
          .frame(width: 56, height: 56)
          .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 17))
          .accessibilityHidden(true)

        VStack(alignment: .leading, spacing: 10) {
          Text("Finish setting up Hey Tim")
            .font(.largeTitle.bold())
          Text("Choose whether bots can use outside AI services.")
            .foregroundStyle(.secondary)
        }

        VStack(alignment: .leading, spacing: 13) {
          Text("What gets shared")
            .font(.headline)
          Text("To answer you, Hey Tim shares messages, attachments, selected files, relevant conversation history and memory, bot instructions, and connected tool results with OpenRouter. It routes text to DeepSeek or Z.AI (GLM), and may route image requests to OpenAI.")
          Text("Room messages, decisions, memory, and member names may be included. This can contain personal information. You can turn AI processing off in Settings at any time.")
        }
        .font(.body)
        .lineSpacing(3)

        Link("Read the Privacy Policy", destination: URL(string: "https://heytim.ai/privacy")!)

        if let errorMessage {
          Text(errorMessage)
            .font(.footnote)
            .foregroundStyle(FrogTheme.danger)
            .accessibilityLabel("Error: \(errorMessage)")
        }

        Button("Allow AI Processing", action: onAllow)
          .buttonStyle(.borderedProminent)
          .frame(maxWidth: .infinity)
          .disabled(isWorking)
          .accessibilityIdentifier("setup.ai-processing.allow")

        Button("Not Now", action: onLater)
          .buttonStyle(.plain)
          .frame(maxWidth: .infinity, minHeight: 44)
          .disabled(isWorking)
          .accessibilityIdentifier("setup.ai-processing.later")
      }
      .frame(maxWidth: 520, alignment: .leading)
      .padding(28)
      .frame(maxWidth: .infinity)
    }
    .foregroundStyle(FrogTheme.text)
    .background(FrogTheme.canvas.ignoresSafeArea())
  }
}
