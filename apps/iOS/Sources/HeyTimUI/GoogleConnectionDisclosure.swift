import SwiftUI

struct GoogleConnectionRequest: Identifiable {
  let provider: ConnectionProvider
  let chooseAnotherAccount: Bool

  var id: String { provider.id }
}

struct GoogleConnectionDisclosure: View {
  let provider: ConnectionProvider
  let onContinue: () -> Void
  let onCancel: () -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        Image(systemName: "person.crop.circle.badge.checkmark")
          .font(.system(size: 34))
          .accessibilityHidden(true)
        Text("Before connecting \(provider.name)")
          .font(.title2.weight(.semibold))
        Text(accessDescription)
        Text("Only bots you assign to this connection can use it. For your requests, relevant results may be processed by Hey Tim on AWS and sent through OpenRouter to an AI provider. They may appear in saved conversations, generated files, or bot memory. In a room, other members may see information included in a bot’s answer or shared file.")
        Text("Disconnecting stops new access. Content already saved in conversations, files, or memory remains until you delete it. You can also revoke Hey Tim’s access in your Google Account.")
        Link("Read the Privacy Policy", destination: URL(string: "https://heytim.ai/privacy/")!)
        HStack {
          Button("Cancel", action: onCancel)
          Spacer()
          Button("Continue to Google", action: onContinue)
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier("connection.google.continue")
        }
      }
      .frame(maxWidth: 520, alignment: .leading)
      .padding(24)
      .frame(maxWidth: .infinity)
    }
    .foregroundStyle(FrogTheme.text)
    .background(FrogTheme.canvas.ignoresSafeArea())
    #if os(macOS)
      .frame(minWidth: 520, minHeight: 480)
    #endif
  }

  private var accessDescription: String {
    switch provider.id {
    case "gmail":
      "Assigned bots can search and read your Gmail messages, threads, labels, and drafts, and create drafts for you to review. Hey Tim does not offer a send action, although Google’s compose permission also allows sending."
    case "youtube":
      "Assigned bots can search videos and read your channel details and uploaded videos. Hey Tim requests read-only YouTube access and cannot change your channel."
    default:
      "Assigned bots can read the Google files and calendar information allowed by the requested permissions. Hey Tim does not offer an action to change those items."
    }
  }
}
