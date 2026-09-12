import SwiftUI

public struct AuthView: View {
  @Bindable var auth: AuthSession
  let invitation: PendingInvitation?
  @State private var email = ""
  @State private var code = ""

  public init(auth: AuthSession, invitation: PendingInvitation?) {
    self.auth = auth
    self.invitation = invitation
  }

  public var body: some View {
    ZStack {
      FrogTheme.background.ignoresSafeArea()
      ScrollView {
        VStack(spacing: 26) {
          VStack(spacing: 8) {
            Text("🐸").font(.system(size: 72))
            Text("FroggyBot").font(.system(size: 36, weight: .heavy, design: .rounded))
            Text("The AI that helps your group decide and follow through.")
              .foregroundStyle(FrogTheme.secondary).multilineTextAlignment(.center)
          }
          VStack(alignment: .leading, spacing: 16) {
            Text(eyebrow).font(.caption.bold()).tracking(1.2).foregroundStyle(FrogTheme.green)
            Text(title).font(.title2.bold())
            Text(copy).foregroundStyle(.secondary)
            if case .codeSent(_, let purpose) = auth.phase {
              TextField("\(purpose == .signIn ? 8 : 6)-digit code", text: $code)
                .textFieldStyle(.roundedBorder)
                #if os(iOS)
                  .keyboardType(.numberPad).textContentType(.oneTimeCode)
                #endif
              Button("Sign in") { Task { await auth.confirm(code: code) } }
                .buttonStyle(.borderedProminent).tint(FrogTheme.green).frame(maxWidth: .infinity)
              Button("Use a different email address") {
                code = ""
                auth.useDifferentEmail()
              }
              .frame(maxWidth: .infinity)
            } else {
              TextField("you@example.com", text: $email)
                .textFieldStyle(.roundedBorder)
                #if os(iOS)
                  .keyboardType(.emailAddress).textContentType(.emailAddress)
                  .textInputAutocapitalization(.never)
                #endif
                .onSubmit { Task { await auth.begin(email: email, invitation: invitation) } }
              Button(invitation == nil ? "Continue" : "Accept invitation") {
                Task { await auth.begin(email: email, invitation: invitation) }
              }.buttonStyle(.borderedProminent).tint(FrogTheme.green).frame(maxWidth: .infinity)
            }
            if auth.isBusy { ProgressView().frame(maxWidth: .infinity) }
            if let error = auth.errorMessage {
              Text(error).font(.footnote).foregroundStyle(.red).accessibilityLabel(
                "Error: \(error)")
            }
            Divider()
            Label(
              invitation == nil
                ? "Existing members can always sign back in."
                : "This invite unlocks your FroggyBot account.", systemImage: "lock.shield"
            )
            .font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity)
          }
          .padding(26).frame(maxWidth: 420, alignment: .leading)
          .background(.background, in: RoundedRectangle(cornerRadius: 26))
          .overlay(RoundedRectangle(cornerRadius: 26).stroke(FrogTheme.border))
          .shadow(color: .black.opacity(0.06), radius: 30, y: 14)
        }.padding(24).frame(maxWidth: .infinity)
      }
    }
  }

  private var eyebrow: String {
    if case .codeSent = auth.phase { return "ONE LAST STEP" }
    return invitation == nil ? "MEMBER SIGN IN" : "YOU'RE INVITED"
  }
  private var title: String {
    if case .codeSent = auth.phase { return "Check your email" }
    return invitation == nil ? "Welcome back" : "Join FroggyBot"
  }
  private var copy: String {
    if case .codeSent(let email, let purpose) = auth.phase {
      return "We sent a \(purpose == .signIn ? 8 : 6)-digit code to \(email)."
    }
    return invitation == nil
      ? "Sign in with your email. New accounts need an invitation from a member."
      : "Use your email to accept this invitation. No password needed."
  }
}
