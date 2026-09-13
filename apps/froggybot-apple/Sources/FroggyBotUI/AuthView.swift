import SwiftUI

public struct AuthView: View {
  @Bindable var auth: AuthSession
  let invitation: PendingInvitation?
  @State private var email = ""
  @State private var code = ""
  @FocusState private var focusedField: Field?

  private enum Field { case email, code }

  public init(auth: AuthSession, invitation: PendingInvitation?) {
    self.auth = auth
    self.invitation = invitation
  }

  public var body: some View {
    ZStack {
      FrogTheme.canvas.ignoresSafeArea()
      ScrollView {
        VStack(spacing: 0) {
          brand
          card
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity, minHeight: 560)
      }
      .scrollIndicators(.hidden)
    }
    .foregroundStyle(FrogTheme.text)
  }

  private var brand: some View {
    VStack(spacing: 0) {
      FrogMark(size: 84).frame(height: 72).padding(.bottom, 12)
      Text("FroggyBot")
        .font(.system(size: 34, weight: .heavy, design: .rounded))
        .tracking(-1.3)
        .foregroundStyle(.primary)
    }
    .padding(.bottom, 24)
  }

  private var card: some View {
    VStack(alignment: .leading, spacing: 0) {
      Text(title)
        .font(.system(size: 25, weight: .bold))
        .tracking(-0.65)
      Text(copy)
        .font(.system(size: 15))
        .foregroundStyle(FrogTheme.mutedWarm)
        .lineSpacing(4)
        .padding(.top, 7)
        .padding(.bottom, invitation == nil ? 22 : 14)

      if invitation != nil { invitationSummary.padding(.bottom, 20) }
      field

      if let error = auth.errorMessage {
        Text(error)
          .font(.system(size: 13))
          .foregroundStyle(FrogTheme.danger)
          .padding(.top, 10)
          .accessibilityLabel("Error: \(error)")
      }

      Button {
        Task {
          if case .codeSent = auth.phase {
            await auth.confirm(code: code)
          } else {
            await auth.begin(email: email, invitation: invitation)
          }
        }
      } label: {
        Group {
          if auth.isBusy {
            ProgressView().tint(.white)
          } else {
            Text(primaryLabel).foregroundStyle(.white)
          }
        }
        .font(.system(size: 16, weight: .semibold))
        .frame(maxWidth: .infinity, minHeight: 44)
      }
      .froggyGlassButton(prominent: true, tint: FrogTheme.brand)
      .buttonBorderShape(.roundedRectangle(radius: 16))
      .disabled(auth.isBusy)
      .padding(.top, 16)

      if case .codeSent = auth.phase {
        Button("Use a different email address") {
          code = ""
          auth.useDifferentEmail()
          focusedField = .email
        }
        .buttonStyle(.plain)
        .font(.system(size: 14, weight: .semibold))
        .foregroundStyle(brandText)
        .frame(maxWidth: .infinity, minHeight: 44)
        .padding(.top, 5)
      }

      if invitation == nil, !isCodeSent {
        Link(
          "Need an invite? Request beta access",
          destination: URL(
            string: "mailto:tmoreton89@gmail.com?subject=FroggyBot%20beta%20access")!
        )
        .font(.system(size: 13, weight: .bold))
        .foregroundStyle(brandText)
        .underline()
        .frame(maxWidth: .infinity, minHeight: 44)
        .padding(.top, 4)
      }
    }
    .padding(24)
    .frame(maxWidth: 420, alignment: .leading)
    .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 26))
    .overlay(RoundedRectangle(cornerRadius: 26).stroke(FrogTheme.subtleBorder))
    .shadow(color: Color(hex: "#191812").opacity(0.07), radius: 30, y: 14)
  }

  @ViewBuilder private var field: some View {
    if case .codeSent(_, let purpose) = auth.phase {
      let length = purpose == .signIn ? 8 : 6
      HStack {
        Text("Verification code")
        Spacer()
        Text("\(length) digits").foregroundStyle(FrogTheme.muted)
      }
      .font(.system(size: 13, weight: .semibold))
      .padding(.bottom, 9)
      TextField(String(repeating: "0", count: length), text: $code)
        .textFieldStyle(.plain)
        .font(.system(size: 26, weight: .semibold))
        .multilineTextAlignment(.center)
        .tracking(9)
        .focused($focusedField, equals: .code)
        .froggyField(focused: focusedField == .code)
        #if os(iOS)
          .keyboardType(.numberPad).textContentType(.oneTimeCode)
        #endif
        .onChange(of: code) { _, value in
          code = String(value.filter(\.isNumber).prefix(length))
        }
        .onSubmit { Task { await auth.confirm(code: code) } }
    } else {
      Text("Email address")
        .font(.system(size: 13, weight: .semibold))
        .foregroundStyle(FrogTheme.textSoft)
        .padding(.bottom, 9)
      TextField("", text: $email)
        .textFieldStyle(.plain)
        .font(.system(size: 16))
        .focused($focusedField, equals: .email)
        .froggyField(focused: focusedField == .email)
        #if os(iOS)
          .keyboardType(.emailAddress).textContentType(.emailAddress)
          .textInputAutocapitalization(.never).submitLabel(.go)
        #endif
        .onSubmit { Task { await auth.begin(email: email, invitation: invitation) } }
        .accessibilityLabel("Email address")
        .overlay(alignment: .leading) {
          if email.isEmpty {
            Text("you@example.com")
              .font(.system(size: 16))
              .foregroundStyle(FrogTheme.text)
              .grayscale(1)
              .opacity(0.45)
              .padding(.horizontal, 16)
              .allowsHitTesting(false)
          }
        }
    }
  }

  private var invitationSummary: some View {
    HStack(spacing: 12) {
      FrogMark(size: 38)
      VStack(alignment: .leading, spacing: 2) {
        Text("FroggyBot invitation").font(.system(size: 14, weight: .bold))
        Text("Your invitation will be verified after email confirmation.")
          .font(.system(size: 12)).foregroundStyle(.secondary)
      }
    }
    .padding(12)
    .background(FrogTheme.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
    .overlay(RoundedRectangle(cornerRadius: 16).stroke(FrogTheme.accent.opacity(0.25)))
  }

  private var isCodeSent: Bool {
    if case .codeSent = auth.phase { return true }
    return false
  }
  private var brandText: Color { FrogTheme.accent }
  private var primaryLabel: String { isCodeSent ? "Sign in" : "Continue" }
  private var title: String {
    isCodeSent ? "Check your messages" : invitation == nil ? "Welcome back" : "Join FroggyBot"
  }
  private var copy: String {
    if case .codeSent(let email, let purpose) = auth.phase {
      return "We sent a \(purpose == .signIn ? 8 : 6)-digit code to \(email)."
    }
    return invitation == nil
      ? "Enter your email to continue."
      : "Use your email to accept this invitation. No password needed."
  }
}

private extension View {
  func froggyField(focused: Bool) -> some View {
    padding(.horizontal, 16)
      .frame(minHeight: 56)
      .foregroundStyle(FrogTheme.text)
      .background(
        focused ? FrogTheme.surface : FrogTheme.pageBackground,
        in: RoundedRectangle(cornerRadius: 16))
      .overlay(
        RoundedRectangle(cornerRadius: 16)
          .stroke(focused ? FrogTheme.accent : FrogTheme.subtleBorder))
  }
}
