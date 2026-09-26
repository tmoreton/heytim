import Foundation
import Observation

@MainActor @Observable
final class AppleDeviceToolCoordinator {
  typealias RegistrationProvider = @MainActor @Sendable () -> DeviceCapabilityRegistration
  typealias Executor = @MainActor @Sendable (DeviceCall) async -> DeviceCallOutcome

  private struct CachedOutcome: Codable {
    var result: JSONValue?
    var error: String?
    var expiresAt: String

    var outcome: DeviceCallOutcome {
      if let result { return .success(result) }
      return .failure(error ?? "The device action could not be completed.")
    }

    init(outcome: DeviceCallOutcome, expiresAt: String) {
      self.expiresAt = expiresAt
      switch outcome {
      case .success(let result): self.result = result
      case .failure(let error): self.error = error
      }
    }
  }

  private static let deviceIDKey = "heytim.device-tools.device-id"
  private static let resultCacheKey = "heytim.device-tools.completed-results"
  private static let heartbeatSeconds: TimeInterval = 60
  private static let pollDelay = Duration.seconds(2)

  let deviceID: String
  private(set) var isConnected = false
  private(set) var lastError: String?

  @ObservationIgnored private var api: HeyTimAPI?
  @ObservationIgnored private var registrationProvider: RegistrationProvider?
  @ObservationIgnored private var executor: Executor?
  @ObservationIgnored private var pollTask: Task<Void, Never>?
  @ObservationIgnored private var unregisterTask: Task<Void, Never>?
  @ObservationIgnored private var pollGeneration = 0
  @ObservationIgnored private var isActive = true
  @ObservationIgnored private var shouldRefresh = true
  @ObservationIgnored private var outcomes: [String: CachedOutcome]
  @ObservationIgnored private let defaults: UserDefaults

  init(defaults: UserDefaults = .standard) {
    self.defaults = defaults
    if let existing = defaults.string(forKey: Self.deviceIDKey),
      UUID(uuidString: existing)?.uuidString.lowercased() == existing
    {
      deviceID = existing
    } else {
      let value = UUID().uuidString.lowercased()
      defaults.set(value, forKey: Self.deviceIDKey)
      deviceID = value
    }
    if let data = defaults.data(forKey: Self.resultCacheKey),
      let saved = try? JSONDecoder().decode([String: CachedOutcome].self, from: data)
    {
      outcomes = saved.filter { !Self.isExpired($0.value.expiresAt) }
    } else {
      outcomes = [:]
    }
    if let cleaned = try? JSONEncoder().encode(outcomes) {
      defaults.set(cleaned, forKey: Self.resultCacheKey)
    }
  }

  deinit {
    pollTask?.cancel()
    unregisterTask?.cancel()
  }

  func connect(
    api: HeyTimAPI,
    registration: @escaping RegistrationProvider,
    execute: @escaping Executor
  ) {
    self.api = api
    registrationProvider = registration
    executor = execute
    shouldRefresh = true
    startIfNeeded()
  }

  func setActive(_ active: Bool) {
    guard isActive != active else { return }
    isActive = active
    if active {
      shouldRefresh = true
      startIfNeeded()
    } else {
      stop(unregister: true)
    }
  }

  func refreshNow() {
    shouldRefresh = true
    startIfNeeded()
  }

  func disconnect() {
    stop(unregister: true)
    api = nil
    registrationProvider = nil
    executor = nil
    lastError = nil
  }

  private func startIfNeeded() {
    guard isActive, api != nil, registrationProvider != nil, executor != nil,
      pollTask == nil
    else { return }
    pollGeneration += 1
    let generation = pollGeneration
    let pendingUnregister = unregisterTask
    pollTask = Task { [weak self] in
      await pendingUnregister?.value
      await self?.run(generation: generation)
    }
  }

  private func stop(unregister: Bool) {
    pollGeneration += 1
    pollTask?.cancel()
    pollTask = nil
    isConnected = false
    guard unregister, let api else { return }
    let deviceID = deviceID
    let previous = unregisterTask
    unregisterTask = Task {
      await previous?.value
      try? await api.unregisterDeviceCapabilities(deviceId: deviceID)
    }
  }

  private func run(generation: Int) async {
    var lastRegistration = Date.distantPast
    defer {
      if pollGeneration == generation {
        isConnected = false
        pollTask = nil
      }
    }
    while !Task.isCancelled, pollGeneration == generation, isActive,
      let api, let registrationProvider, let executor
    {
      do {
        pruneExpiredOutcomes()
        if shouldRefresh
          || Date().timeIntervalSince(lastRegistration) >= Self.heartbeatSeconds
        {
          _ = try await api.registerDeviceCapabilities(
            deviceId: deviceID, registration: registrationProvider())
          lastRegistration = Date()
          shouldRefresh = false
          isConnected = true
          lastError = nil
        }
        for call in try await api.deviceCalls(deviceId: deviceID) {
          guard !Task.isCancelled else { return }
          let outcome: DeviceCallOutcome
          if let cached = outcomes[call.id] {
            outcome = cached.outcome
          } else if Self.isExpired(call.expiresAt) {
            outcome = .failure("This device request expired before it could run.")
            _ = remember(outcome, for: call)
          } else {
            let uncertain = DeviceCallOutcome.failure(
              "A previous attempt may have been interrupted, so Hey Tim did not replay this device action."
            )
            // Claim the execution locally before calling an adapter. A crash can
            // therefore produce an explicit uncertain outcome, but never an
            // automatic replay of a Mac action.
            if remember(uncertain, for: call) {
              let executed = await executor(call)
              outcome = remember(executed, for: call) ? executed : uncertain
            } else {
              outcome = .failure(
                "Hey Tim could not save safe retry state, so it did not run this device action.")
            }
          }
          _ = try await api.submitDeviceCall(call, deviceId: deviceID, outcome: outcome)
          outcomes.removeValue(forKey: call.id)
          _ = saveOutcomes()
        }
      } catch is CancellationError {
        return
      } catch {
        isConnected = false
        lastError = error.localizedDescription
        shouldRefresh = true
      }
      try? await Task.sleep(for: Self.pollDelay)
    }
  }

  @discardableResult
  private func remember(_ outcome: DeviceCallOutcome, for call: DeviceCall) -> Bool {
    outcomes[call.id] = CachedOutcome(outcome: outcome, expiresAt: call.expiresAt)
    outcomes = Dictionary(
      uniqueKeysWithValues: outcomes
        .filter { !Self.isExpired($0.value.expiresAt) }
        .sorted { $0.value.expiresAt > $1.value.expiresAt }
        .prefix(32)
        .map { ($0.key, $0.value) })
    return saveOutcomes()
  }

  @discardableResult
  private func saveOutcomes() -> Bool {
    guard let data = try? JSONEncoder().encode(outcomes) else { return false }
    defaults.set(data, forKey: Self.resultCacheKey)
    return true
  }

  private func pruneExpiredOutcomes() {
    let retained = outcomes.filter { !Self.isExpired($0.value.expiresAt) }
    guard retained.count != outcomes.count else { return }
    outcomes = retained
    _ = saveOutcomes()
  }

  private static func isExpired(_ value: String) -> Bool {
    guard let date = ISO8601DateFormatter().date(from: value) else { return true }
    return date <= Date()
  }
}
