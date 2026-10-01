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
  func allowAISharing() async {
    guard !isUpdatingAISharingConsent, let api else { return }
    isUpdatingAISharingConsent = true
    errorMessage = nil
    defer { isUpdatingAISharingConsent = false }
    do {
      let consent = try await api.allowAISharing()
      guard self.api === api else { return }
      bootstrap?.aiSharingConsent = consent
    } catch {
      if self.api === api { present(error) }
    }
  }

  func revokeAISharing() async {
    guard !isUpdatingAISharingConsent, let api else { return }
    isUpdatingAISharingConsent = true
    errorMessage = nil
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
