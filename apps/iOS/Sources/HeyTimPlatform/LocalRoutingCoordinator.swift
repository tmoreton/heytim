#if os(macOS)
import Foundation
import Observation

@MainActor @Observable
final class LocalRoutingCoordinator {
  private static let enabledKey = "heytim.local-routing.enabled"
  private static let deviceKey = "heytim.local-routing.device-id"
  private(set) var enabled: Bool
  private(set) var modelInstalled = false
  private(set) var isPreparing = false
  private(set) var isConnected = false
  private(set) var activity = "Download the model to route incoming messages on this Mac."
  private(set) var lastError: String?
  let deviceID: String

  @ObservationIgnored private let helper: any LocalDeciderServing
  @ObservationIgnored private let defaults: UserDefaults
  @ObservationIgnored private var api: HeyTimAPI?
  @ObservationIgnored private var task: Task<Void, Never>?
  @ObservationIgnored private var setupTask: Task<Void, Never>?
  @ObservationIgnored private var unregisterTask: Task<Void, Never>?
  @ObservationIgnored private var generation = UUID()
  @ObservationIgnored private var cachedResults: [String: LocalDeciderResult] = [:]

  init(defaults: UserDefaults = .standard, helper: any LocalDeciderServing = LocalDeciderProcess()) {
    self.defaults = defaults
    self.helper = helper
    enabled = defaults.bool(forKey: Self.enabledKey)
    if let stored = defaults.string(forKey: Self.deviceKey), UUID(uuidString: stored) != nil {
      deviceID = stored
    } else {
      deviceID = UUID().uuidString.lowercased()
      defaults.set(deviceID, forKey: Self.deviceKey)
    }
  }

  var isSupported: Bool {
    #if arch(arm64)
      true
    #else
      false
    #endif
  }

  func connect(api: HeyTimAPI) {
    disconnect()
    self.api = api
    if enabled { start() }
    else { Task { await checkModel() } }
  }

  func disconnect() {
    generation = UUID()
    task?.cancel()
    task = nil
    setupTask?.cancel()
    setupTask = nil
    if let api {
      let deviceID = deviceID
      let previous = unregisterTask
      unregisterTask = Task {
        await previous?.value
        try? await api.unregisterLocalRouter(deviceId: deviceID)
      }
    }
    api = nil
    isConnected = false
    cachedResults.removeAll()
    Task { await helper.stop() }
  }

  func setEnabled(_ value: Bool) {
    enabled = value && isSupported
    defaults.set(enabled, forKey: Self.enabledKey)
    if enabled { start() }
    else {
      generation = UUID()
      task?.cancel()
      task = nil
      isConnected = false
      if let api {
        let previous = unregisterTask
        let deviceID = deviceID
        unregisterTask = Task {
          await previous?.value
          try? await api.unregisterLocalRouter(deviceId: deviceID)
        }
      }
      Task { await helper.stop() }
      activity = "Local routing is off. Incoming messages wait for an available router."
    }
  }

  func prepareModel() {
    guard isSupported, !isPreparing else { return }
    generation = UUID()
    task?.cancel()
    task = nil
    isConnected = false
    isPreparing = true
    lastError = nil
    activity = "Preparing the model download…"
    setupTask = Task { [weak self] in
      guard let self else { return }
      defer { isPreparing = false; setupTask = nil }
      do {
        try await helper.prepare { [weak self] message in
          Task { @MainActor in self?.activity = message }
        }
        modelInstalled = true
        activity = "Model installed. Ready to route messages locally."
        isPreparing = false
        if enabled { start() }
      } catch is CancellationError {
        activity = "Model setup cancelled."
      } catch {
        lastError = error.localizedDescription
      }
    }
  }

  func cancelSetup() { setupTask?.cancel() }

  func checkModel() async {
    guard isSupported, !isPreparing else { return }
    do {
      let health = try await helper.health()
      guard health.modelId == LocalDeciderIdentity.modelID,
        health.modelRevision == LocalDeciderIdentity.revision else {
        throw LocalDeciderError.invalidOutput
      }
      modelInstalled = health.modelInstalled ?? health.ready
      if !modelInstalled { activity = "Download the model to route incoming messages on this Mac." }
    } catch { lastError = error.localizedDescription }
  }

  private func start() {
    guard task == nil, let api, enabled, isSupported, !isPreparing else { return }
    generation = UUID()
    let current = generation
    let pendingUnregister = unregisterTask
    task = Task { [weak self] in
      await pendingUnregister?.value
      await self?.run(api: api, generation: current)
    }
  }

  private func run(api: HeyTimAPI, generation current: UUID) async {
    defer { if generation == current { task = nil; isConnected = false } }
    await checkModel()
    guard modelInstalled else { return }
    var registeredAt = Date.distantPast
    while !Task.isCancelled, generation == current, enabled {
      do {
        if Date().timeIntervalSince(registeredAt) >= 60 {
          try await api.registerLocalRouter(deviceId: deviceID)
          registeredAt = Date()
        }
        isConnected = true
        lastError = nil
        activity = "Ready for incoming messages. Keep Hey Tim running on this Mac."
        for request in try await api.localRoutingRequests(deviceId: deviceID) {
          guard !Task.isCancelled, generation == current else { return }
          activity = "Choosing a bot and reasoning level…"
          let result: LocalDeciderResult
          if let saved = cachedResults[request.requestDigest] { result = saved }
          else {
            do { result = try await helper.decide(request) }
            catch {
              guard !Task.isCancelled, generation == current else { return }
              // A rejected/overflowing input must not repeatedly occupy the first
              // lease and starve other messages. Keep it visible for manual review.
              var probabilities = Dictionary(uniqueKeysWithValues: request.bots.map { ($0.id, 0.0) })
              probabilities["clarify"] = 1
              result = LocalDeciderResult(
                modelId: request.modelId, modelRevision: request.modelRevision,
                botId: nil, reasoningEffort: "high", confidence: 1,
                probabilities: probabilities, reasoningConfidence: 0, reasoningDeferred: true,
                needsReview: true,
                reason: "local_router_error")
              lastError = error.localizedDescription
            }
            cachedResults[request.requestDigest] = result
            if cachedResults.count > 32 { cachedResults = [request.requestDigest: result] }
          }
          guard !Task.isCancelled, generation == current else { return }
          try await api.submitRoutingResult(result, request: request, deviceId: deviceID)
          cachedResults.removeValue(forKey: request.requestDigest)
        }
      } catch is CancellationError { return }
      catch {
        isConnected = false
        lastError = error.localizedDescription
        registeredAt = .distantPast
      }
      try? await Task.sleep(for: .seconds(isConnected ? 3 : 15))
    }
  }
}
#endif
