import Foundation
import Observation
import Security

public enum AuthPhase: Equatable, Sendable {
  case checking, signedOut
  case codeSent(email: String, purpose: CodePurpose)
  case signedIn
}

public enum CodePurpose: String, Codable, Sendable { case signIn, signUp }

public struct PendingInvitation: Codable, Equatable, Sendable {
  public var kind: String
  public var token: String
  public init(kind: String, token: String) {
    self.kind = kind
    self.token = token
  }
}

private struct TokenSet: Codable, Sendable {
  var idToken: String
  var accessToken: String
  var refreshToken: String
  var expiresAt: Date
}

private struct PendingCode: Sendable {
  var email: String
  var purpose: CodePurpose
  var session: String?
  var signUpSession: String?
}

private struct CognitoResponse: Decodable {
  struct Result: Decodable {
    var accessToken: String?
    var expiresIn: Int?
    var idToken: String?
    var refreshToken: String?
    enum CodingKeys: String, CodingKey {
      case accessToken = "AccessToken"
      case expiresIn = "ExpiresIn"
      case idToken = "IdToken"
      case refreshToken = "RefreshToken"
    }
  }
  var authenticationResult: Result? = nil
  var challengeName: String? = nil
  var session: String? = nil
  enum CodingKeys: String, CodingKey {
    case authenticationResult = "AuthenticationResult"
    case challengeName = "ChallengeName"
    case session = "Session"
  }
}

private struct CognitoErrorBody: Decodable {
  var type: String?
  var message: String?
  enum CodingKeys: String, CodingKey {
    case type = "__type"
    case message
  }
}

public struct CognitoError: LocalizedError, Sendable {
  public var name: String
  public var message: String
  public var errorDescription: String? { message }
}

@MainActor @Observable
public final class AuthSession {
  public private(set) var phase: AuthPhase = .checking
  public var errorMessage: String?
  public private(set) var email = ""
  public var isBusy = false

  @ObservationIgnored private let configuration: AppConfiguration
  @ObservationIgnored private let network: URLSession
  @ObservationIgnored private var tokens: TokenSet?
  @ObservationIgnored private var pending: PendingCode?
  @ObservationIgnored private let keychain = TokenKeychain()

  public init(configuration: AppConfiguration, network: URLSession = .shared) {
    self.configuration = configuration
    self.network = network
  }

  public func restore() async {
    if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
      phase = .signedIn
      return
    }
    tokens = keychain.load()
    if tokens != nil {
      do {
        _ = try await idToken()
        phase = .signedIn
        return
      } catch {
        keychain.delete()
        tokens = nil
      }
    }
    phase = .signedOut
  }

  public func begin(email rawEmail: String, invitation: PendingInvitation?) async {
    let value = rawEmail.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    guard value.range(of: #"^[^\s@]+@[^\s@]+\.[^\s@]+$"#, options: .regularExpression) != nil else {
      errorMessage = "Enter a valid email address."
      return
    }
    isBusy = true
    errorMessage = nil
    defer { isBusy = false }
    do {
      if let invitation {
        do {
          let response = try await invoke(
            "SignUp",
            payload: [
              "ClientId": configuration.auth.userPoolClientId,
              "Username": value,
              "UserAttributes": [["Name": "email", "Value": value]],
              "ClientMetadata": ["inviteKind": invitation.kind, "inviteToken": invitation.token],
            ])
          email = value
          pending = PendingCode(
            email: value, purpose: .signUp, session: nil, signUpSession: response.session)
          phase = .codeSent(email: value, purpose: .signUp)
          return
        } catch let error as CognitoError where error.name == "UsernameExistsException" {
          // Existing invitees sign in normally.
        } catch let error as CognitoError where error.name == "UserLambdaValidationException" {
          throw CognitoError(
            name: error.name,
            message: "This invitation is no longer valid. Ask a friend for a fresh FroggyBot link.")
        }
      }
      try await beginSignIn(value)
    } catch let error as CognitoError where error.name == "UserNotFoundException" {
      errorMessage =
        "FroggyBot is invite-only right now. Open a link shared by a member to create your account."
    } catch let error as CognitoError where error.name == "UserNotConfirmedException" {
      do {
        _ = try await invoke(
          "ResendConfirmationCode",
          payload: ["ClientId": configuration.auth.userPoolClientId, "Username": value])
        email = value
        pending = PendingCode(email: value, purpose: .signUp, session: nil, signUpSession: nil)
        phase = .codeSent(email: value, purpose: .signUp)
      } catch { errorMessage = error.localizedDescription }
    } catch { errorMessage = error.localizedDescription }
  }

  public func confirm(code: String) async {
    guard let pending else { return }
    let normalized = code.filter(\.isNumber)
    let required = pending.purpose == .signIn ? 8 : 6
    guard normalized.count == required else {
      errorMessage = "Enter the \(required)-digit code from your email."
      return
    }
    isBusy = true
    errorMessage = nil
    defer { isBusy = false }
    do {
      if pending.purpose == .signIn {
        let response = try await invoke(
          "RespondToAuthChallenge",
          payload: [
            "ChallengeName": "EMAIL_OTP", "ClientId": configuration.auth.userPoolClientId,
            "Session": pending.session ?? "",
            "ChallengeResponses": ["USERNAME": pending.email, "EMAIL_OTP_CODE": normalized],
          ])
        try store(response.authenticationResult, preservingRefreshToken: nil)
      } else {
        var confirmationPayload: [String: Any] = [
          "ClientId": configuration.auth.userPoolClientId,
          "Username": pending.email, "ConfirmationCode": normalized,
        ]
        if let signUpSession = pending.signUpSession {
          confirmationPayload["Session"] = signUpSession
        }
        let confirmed = try await invoke("ConfirmSignUp", payload: confirmationPayload)
        do {
          var authPayload: [String: Any] = [
            "AuthFlow": "USER_AUTH", "ClientId": configuration.auth.userPoolClientId,
            "AuthParameters": ["USERNAME": pending.email],
          ]
          if let confirmedSession = confirmed.session {
            authPayload["Session"] = confirmedSession
          }
          let response = try await invoke("InitiateAuth", payload: authPayload)
          if response.authenticationResult != nil {
            try store(response.authenticationResult, preservingRefreshToken: nil)
          } else {
            throw CognitoError(
              name: "AutoSignInUnavailable",
              message: "Your email is confirmed. Request a new code to sign in.")
          }
        } catch {
          self.pending = nil
          phase = .signedOut
          throw error
        }
      }
      self.pending = nil
      phase = .signedIn
    } catch { errorMessage = error.localizedDescription }
  }

  public func useDifferentEmail() {
    pending = nil
    email = ""
    errorMessage = nil
    phase = .signedOut
  }

  public func signOut() async {
    if let refreshToken = tokens?.refreshToken {
      _ = try? await invoke(
        "RevokeToken",
        payload: [
          "ClientId": configuration.auth.userPoolClientId,
          "Token": refreshToken,
        ])
    }
    tokens = nil
    pending = nil
    keychain.delete()
    phase = .signedOut
  }

  public func idToken() async throws -> String? {
    if ProcessInfo.processInfo.arguments.contains("--ui-testing") { return "ui-test-token" }
    guard var current = tokens else { return nil }
    if current.expiresAt.timeIntervalSinceNow > 60 { return current.idToken }
    let response = try await invoke(
      "InitiateAuth",
      payload: [
        "AuthFlow": "REFRESH_TOKEN_AUTH", "ClientId": configuration.auth.userPoolClientId,
        "AuthParameters": ["REFRESH_TOKEN": current.refreshToken],
      ])
    try store(response.authenticationResult, preservingRefreshToken: current.refreshToken)
    current = tokens!
    return current.idToken
  }

  private func beginSignIn(_ email: String) async throws {
    let response = try await invoke(
      "InitiateAuth",
      payload: [
        "AuthFlow": "USER_AUTH", "ClientId": configuration.auth.userPoolClientId,
        "AuthParameters": ["USERNAME": email, "PREFERRED_CHALLENGE": "EMAIL_OTP"],
      ])
    if response.authenticationResult != nil {
      try store(response.authenticationResult, preservingRefreshToken: nil)
      phase = .signedIn
      return
    }
    guard response.challengeName == "EMAIL_OTP", let session = response.session else {
      throw CognitoError(
        name: "ChallengeUnavailable",
        message: "Email code sign-in is not available for this account.")
    }
    self.email = email
    pending = PendingCode(email: email, purpose: .signIn, session: session, signUpSession: nil)
    phase = .codeSent(email: email, purpose: .signIn)
  }

  private func store(_ result: CognitoResponse.Result?, preservingRefreshToken: String?) throws {
    guard let result, let id = result.idToken, let access = result.accessToken,
      let refresh = result.refreshToken ?? preservingRefreshToken
    else {
      throw CognitoError(
        name: "InvalidTokenResponse", message: "The sign-in service returned an incomplete session."
      )
    }
    let value = TokenSet(
      idToken: id, accessToken: access, refreshToken: refresh,
      expiresAt: Date().addingTimeInterval(TimeInterval(result.expiresIn ?? 3600)))
    tokens = value
    try keychain.save(value)
  }

  private func invoke(_ operation: String, payload: [String: Any]) async throws -> CognitoResponse {
    guard
      let url = URL(string: "https://cognito-idp.\(configuration.auth.awsRegion).amazonaws.com/")
    else {
      throw APIError.configuration("The sign-in region is invalid.")
    }
    var request = URLRequest(url: url, timeoutInterval: 30)
    request.httpMethod = "POST"
    request.setValue("application/x-amz-json-1.1", forHTTPHeaderField: "Content-Type")
    request.setValue(
      "AWSCognitoIdentityProviderService.\(operation)", forHTTPHeaderField: "X-Amz-Target")
    request.httpBody = try JSONSerialization.data(withJSONObject: payload)
    let (data, response) = try await network.data(for: request)
    guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
    if !(200..<300).contains(http.statusCode) {
      let body = try? JSONDecoder().decode(CognitoErrorBody.self, from: data)
      let name =
        (body?.type ?? "CognitoError").split(separator: "#").last.map(String.init) ?? "CognitoError"
      throw CognitoError(name: name, message: body?.message ?? "Sign in could not be completed.")
    }
    if data.isEmpty { return CognitoResponse() }
    return try JSONDecoder().decode(CognitoResponse.self, from: data)
  }
}

private final class TokenKeychain: @unchecked Sendable {
  private let service = "com.froggybot.app.auth"
  private let account = "cognito-session"

  func save(_ value: TokenSet) throws {
    let data = try JSONEncoder().encode(value)
    delete()
    let status = SecItemAdd(
      [
        kSecClass: kSecClassGenericPassword, kSecAttrService: service,
        kSecAttrAccount: account, kSecValueData: data,
        kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
      ] as CFDictionary, nil)
    guard status == errSecSuccess else {
      throw APIError.configuration("The secure session could not be saved.")
    }
  }

  func load() -> TokenSet? {
    var result: CFTypeRef?
    let status = SecItemCopyMatching(
      [
        kSecClass: kSecClassGenericPassword, kSecAttrService: service,
        kSecAttrAccount: account, kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne,
      ] as CFDictionary, &result)
    guard status == errSecSuccess, let data = result as? Data else { return nil }
    return try? JSONDecoder().decode(TokenSet.self, from: data)
  }

  func delete() {
    SecItemDelete(
      [kSecClass: kSecClassGenericPassword, kSecAttrService: service, kSecAttrAccount: account]
        as CFDictionary)
  }
}
