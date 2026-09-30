import Foundation

public extension HeyTimAPI {
  func allowAISharing() async throws -> AISharingConsent {
    try await request(
      .aiSharingConsentGrant,
      body: AISharingConsent(version: 1, granted: true))
  }

  func revokeAISharing() async throws -> AISharingConsent {
    try await request(.aiSharingConsentRevoke)
  }
}

@MainActor public extension AppModel {
  func allowAISharing(sendPendingMessage: Bool = false) async {
    guard !isUpdatingAISharingConsent, let api else { return }
    isUpdatingAISharingConsent = true
    defer { isUpdatingAISharingConsent = false }
    do {
      let consent = try await api.allowAISharing()
      guard self.api === api else { return }
      bootstrap?.aiSharingConsent = consent
      showAISharingConsent = false
      if sendPendingMessage { await send() }
    } catch {
      if self.api === api { present(error) }
    }
  }

  func revokeAISharing() async {
    guard !isUpdatingAISharingConsent, let api else { return }
    isUpdatingAISharingConsent = true
    defer { isUpdatingAISharingConsent = false }
    do {
      let consent = try await api.revokeAISharing()
      guard self.api === api else { return }
      bootstrap?.aiSharingConsent = consent
    } catch {
      if self.api === api { present(error) }
    }
  }
}
