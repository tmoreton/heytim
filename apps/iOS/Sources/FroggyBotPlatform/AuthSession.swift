import Foundation
import Observation
import OSLog
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
  @ObservationIgnored private let keychain = TokenKeychain(
    service: AuthSession.keychainServiceForCurrentProcess)
  @ObservationIgnored private var sessionGeneration: UInt = 0

  static var keychainServiceForCurrentProcess: String {
    let process = ProcessInfo.processInfo
    let isRunningTests =
      process.environment["XCTestConfigurationFilePath"] != nil
      || process.environment["XCInjectBundleInto"] != nil
      || NSClassFromString("XCTestCase") != nil
    guard isRunningTests else { return "ai.heytim.app.auth" }
    return "ai.heytim.app.auth.tests.\(process.processIdentifier)"
  }

  public init(configuration: AppConfiguration, network: URLSession = .shared) {
    self.configuration = configuration
    self.network = network
  }

  public var sessionIdentifier: UInt { sessionGeneration }

  public func restore() async {
    if ProcessInfo.processInfo.arguments.contains("--ui-testing-auth") {
      phase = .signedOut
      return
    }
    if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
      phase = .signedIn
      return
    }
    tokens = keychain.load()
    if tokens != nil {
      sessionGeneration &+= 1
      do {
        _ = try await idToken()
        phase = .signedIn
        return
      } catch {
        if tokens != nil {
          // Preserve a refreshable session through transient network failures.
          phase = .signedIn
          errorMessage = error.localizedDescription
          return
        }
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
            message: "This invitation is no longer valid. Ask a friend for a fresh Hey Tim link.")
        }
      }
      try await beginSignIn(value)
    } catch let error as CognitoError where error.name == "UserNotFoundException" {
      errorMessage =
        "Hey Tim is invite-only right now. Open a link shared by a member to create your account."
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
    let refreshToken = tokens?.refreshToken
    // End the local session before suspending for best-effort revocation. A
    // delayed sign-out must never resume later and clear a replacement login.
    clearStoredSession()
    errorMessage = nil
    phase = .signedOut
    if let refreshToken {
      _ = try? await invoke(
        "RevokeToken",
        payload: [
          "ClientId": configuration.auth.userPoolClientId,
          "Token": refreshToken,
        ])
    }
  }

  public func expire(ifUsing rejectedToken: String, session: UInt) {
    guard sessionGeneration == session, tokens?.idToken == rejectedToken else { return }
    expireCurrentSession()
  }

  public func idToken(forSession expectedSession: UInt? = nil) async throws -> String? {
    if let expectedSession, expectedSession != sessionGeneration {
      throw APIError.sessionExpired
    }
    if ProcessInfo.processInfo.arguments.contains("--ui-testing") { return "ui-test-token" }
    guard var current = tokens else { return nil }
    if current.expiresAt.timeIntervalSinceNow > 60 { return current.idToken }
    let requestedSession = sessionGeneration
    let response: CognitoResponse
    do {
      response = try await invoke(
        "InitiateAuth",
        payload: [
          "AuthFlow": "REFRESH_TOKEN_AUTH", "ClientId": configuration.auth.userPoolClientId,
          "AuthParameters": ["REFRESH_TOKEN": current.refreshToken],
        ])
    } catch let error as CognitoError where Self.isTerminalSessionError(error) {
      if sessionMatches(requestedSession, refreshToken: current.refreshToken) {
        expireCurrentSession()
      }
      throw APIError.sessionExpired
    }
    guard sessionMatches(requestedSession, refreshToken: current.refreshToken) else {
      throw APIError.sessionExpired
    }
    do {
      try store(response.authenticationResult, preservingRefreshToken: current.refreshToken)
    } catch let error as CognitoError where error.name == "InvalidTokenResponse" {
      if sessionMatches(requestedSession, refreshToken: current.refreshToken) {
        expireCurrentSession()
      }
      throw APIError.sessionExpired
    }
    current = tokens!
    return current.idToken
  }

  private func expireCurrentSession() {
    clearStoredSession()
    errorMessage = APIError.sessionExpired.localizedDescription
    phase = .signedOut
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
    try keychain.save(value)
    tokens = value
    if preservingRefreshToken == nil { sessionGeneration &+= 1 }
  }

  private func clearStoredSession() {
    sessionGeneration &+= 1
    tokens = nil
    pending = nil
    keychain.delete()
  }

  private func sessionMatches(_ generation: UInt, refreshToken: String) -> Bool {
    sessionGeneration == generation && tokens?.refreshToken == refreshToken
  }

  private static func isTerminalSessionError(_ error: CognitoError) -> Bool {
    [
      "NotAuthorizedException", "PasswordResetRequiredException", "UserNotConfirmedException",
      "UserNotFoundException",
    ].contains(error.name)
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
  private static let logger = Logger(subsystem: "ai.heytim.app", category: "SecureSession")

  private let service: String
  private let account = "cognito-session"

  init(service: String) {
    self.service = service
  }

  func save(_ value: TokenSet) throws {
    let data = try JSONEncoder().encode(value)
    let values: [CFString: Any] = [
      kSecValueData: data,
      kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
    ]
    var status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
    if status == errSecItemNotFound {
      var attributes = query
      values.forEach { attributes[$0.key] = $0.value }
      status = SecItemAdd(attributes as CFDictionary, nil)
      if status == errSecDuplicateItem {
        status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
      }
    }
    guard status == errSecSuccess else {
      #if targetEnvironment(simulator)
        if status == errSecMissingEntitlement {
          // A bundle installed directly with simctl has no runtime keychain access group.
          // Keep simulator logins usable without weakening storage on Apple hardware.
          UserDefaults.standard.set(data, forKey: simulatorFallbackKey)
          return
        }
      #endif
      Self.logFailure(operation: "save", status: status)
      throw APIError.configuration(
        status == errSecMissingEntitlement
          ? "Secure storage is unavailable in this build. Reinstall Hey Tim and try again."
          : "The secure session could not be saved. Try again.")
    }
    #if targetEnvironment(simulator)
      UserDefaults.standard.removeObject(forKey: simulatorFallbackKey)
    #endif
  }

  func load() -> TokenSet? {
    var result: CFTypeRef?
    var request = query
    request[kSecReturnData] = true
    request[kSecMatchLimit] = kSecMatchLimitOne
    let status = SecItemCopyMatching(request as CFDictionary, &result)
    if status == errSecSuccess, let data = result as? Data {
      return try? JSONDecoder().decode(TokenSet.self, from: data)
    }
    #if targetEnvironment(simulator)
      if let data = UserDefaults.standard.data(forKey: simulatorFallbackKey),
        let value = try? JSONDecoder().decode(TokenSet.self, from: data)
      {
        return value
      }
    #endif
    #if targetEnvironment(simulator)
      if status != errSecItemNotFound && status != errSecMissingEntitlement {
        Self.logFailure(operation: "load", status: status)
      }
    #else
      if status != errSecItemNotFound { Self.logFailure(operation: "load", status: status) }
    #endif
    return nil
  }

  func delete() {
    let status = SecItemDelete(query as CFDictionary)
    #if targetEnvironment(simulator)
      UserDefaults.standard.removeObject(forKey: simulatorFallbackKey)
    #endif
    #if targetEnvironment(simulator)
      if status != errSecSuccess && status != errSecItemNotFound
        && status != errSecMissingEntitlement
      {
        Self.logFailure(operation: "delete", status: status)
      }
    #else
      if status != errSecSuccess && status != errSecItemNotFound {
        Self.logFailure(operation: "delete", status: status)
      }
    #endif
  }

  private var query: [CFString: Any] {
    [
      kSecClass: kSecClassGenericPassword,
      kSecAttrService: service,
      kSecAttrAccount: account,
    ]
  }

  #if targetEnvironment(simulator)
    private var simulatorFallbackKey: String {
      "froggybot.simulator-session.\(service).\(account)"
    }
  #endif

  private static func logFailure(operation: String, status: OSStatus) {
    let detail = SecCopyErrorMessageString(status, nil) as String? ?? "Unknown keychain error"
    logger.error(
      "Secure session \(operation, privacy: .public) failed with OSStatus \(status, privacy: .public): \(detail, privacy: .public)"
    )
  }
}
