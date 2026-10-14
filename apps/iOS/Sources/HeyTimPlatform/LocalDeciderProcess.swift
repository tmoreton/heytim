#if os(macOS)
import Foundation

enum LocalDeciderError: LocalizedError {
  case unavailable, setupRequired, stopped, timedOut, invalidOutput, helper(String)
  var errorDescription: String? {
    switch self {
    case .unavailable: "Local routing requires the Apple silicon edition of Hey Tim."
    case .setupRequired: "Download the routing model on this Mac first."
    case .stopped: "The local router stopped. Pending messages will be retried."
    case .timedOut: "The local router took too long. Pending messages will be retried."
    case .invalidOutput: "The local router returned an unreadable response."
    case .helper(let message): message
    }
  }
}

/// One app-owned helper, one loaded model, and bounded NDJSON over private pipes.
protocol LocalDeciderServing: Sendable {
  func health() async throws -> LocalDeciderHealth
  func decide(_ request: LocalRoutingRequest) async throws -> LocalDeciderResult
  func prepare(progress: @escaping @Sendable (String) -> Void) async throws
  func stop() async
}

actor LocalDeciderProcess: LocalDeciderServing {
  private struct Request<Parameters: Encodable & Sendable>: Encodable {
    var id: String
    var method: String
    var params: Parameters
  }
  private struct Reply<Value: Decodable & Sendable>: Decodable {
    struct Failure: Decodable { var message: String }
    var result: Value?
    var error: Failure?
  }
  private struct DecisionInput: Encodable, Sendable {
    var text: String
    var bots: [RoutingBot]
  }

  private let executable: URL?
  private let modelRoot: URL
  private var process: Process?
  private var input: FileHandle?
  private var output: FileHandle?
  private var buffer = Data()
  private var generation = UUID()
  private var pending: [String: CheckedContinuation<Data, Error>] = [:]
  private var preparation: CheckedContinuation<Void, Error>?
  private var progress: (@Sendable (String) -> Void)?

  init(bundle: Bundle = .main, modelRoot: URL? = nil) {
    #if arch(arm64)
      executable = bundle.bundleURL.appendingPathComponent("Contents/Helpers/HeyTimDecider/bin/heytim-decider")
    #else
      executable = nil
    #endif
    self.modelRoot = modelRoot ?? FileManager.default.urls(
      for: .applicationSupportDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("HeyTim/Decider/models", isDirectory: true)
  }

  func health() async throws -> LocalDeciderHealth {
    try await request(method: "health", parameters: EmptyResponse())
  }

  func decide(_ routingRequest: LocalRoutingRequest) async throws -> LocalDeciderResult {
    guard routingRequest.text.utf8.count <= 16_384,
      !routingRequest.bots.isEmpty, routingRequest.bots.count <= 32
    else { throw LocalDeciderError.helper("This message is too large for local routing. Choose a bot in Webhooks.") }
    let result: LocalDeciderResult = try await request(
      method: "decide", parameters: DecisionInput(text: routingRequest.text, bots: routingRequest.bots))
    return try result.validated(for: routingRequest)
  }

  func prepare(progress: @escaping @Sendable (String) -> Void) async throws {
    guard preparation == nil else { throw LocalDeciderError.helper("Model setup is already running.") }
    stop()
    try start(prepare: true)
    self.progress = progress
    try await withTaskCancellationHandler {
      try await withCheckedThrowingContinuation { continuation in
        preparation = continuation
      }
    } onCancel: {
      Task { await self.stop() }
    }
  }

  func stop() {
    generation = UUID()
    output?.readabilityHandler = nil
    try? input?.close()
    input = nil
    output = nil
    if process?.isRunning == true { process?.terminate() }
    process = nil
    buffer.removeAll()
    let waiting = pending.values
    pending.removeAll()
    for continuation in waiting { continuation.resume(throwing: LocalDeciderError.stopped) }
    preparation?.resume(throwing: LocalDeciderError.stopped)
    preparation = nil
    progress = nil
  }

  private func request<Parameters: Encodable & Sendable, Value: Decodable & Sendable>(
    method: String, parameters: Parameters
  ) async throws -> Value {
    guard preparation == nil else { throw LocalDeciderError.setupRequired }
    if process?.isRunning != true { try start(prepare: false) }
    let id = UUID().uuidString
    var line = try JSONEncoder().encode(Request(id: id, method: method, params: parameters))
    guard line.count <= 131_072 else { throw LocalDeciderError.invalidOutput }
    line.append(10)
    let data: Data = try await withTaskCancellationHandler {
      try await withCheckedThrowingContinuation { continuation in
        pending[id] = continuation
        do {
          try input?.write(contentsOf: line)
        } catch {
          pending.removeValue(forKey: id)?.resume(throwing: error)
        }
        Task { [weak self] in
          try? await Task.sleep(for: .seconds(120))
          await self?.expire(id)
        }
      }
    } onCancel: {
      Task { await self.cancel(id) }
    }
    let reply = try JSONDecoder().decode(Reply<Value>.self, from: data)
    if let error = reply.error { throw LocalDeciderError.helper(error.message) }
    guard let result = reply.result else { throw LocalDeciderError.invalidOutput }
    return result
  }

  private func start(prepare: Bool) throws {
    guard let executable, FileManager.default.isExecutableFile(atPath: executable.path)
    else { throw LocalDeciderError.unavailable }
    try FileManager.default.createDirectory(at: modelRoot, withIntermediateDirectories: true)
    let child = Process()
    child.executableURL = executable
    child.arguments = ["--model-root", modelRoot.path] + (prepare ? ["--prepare"] : [])
    // The helper needs only its bundled runtime and model directory, never cloud credentials.
    child.environment = [
      "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
      "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
      "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1",
      "HF_HUB_DISABLE_TELEMETRY": "1",
    ]
    let stdin = Pipe()
    let stdout = Pipe()
    child.standardInput = stdin
    child.standardOutput = stdout
    child.standardError = FileHandle.nullDevice
    generation = UUID()
    let current = generation
    buffer.removeAll()
    stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
      let data = handle.availableData
      Task { await self?.receive(data, generation: current) }
    }
    process = child
    input = stdin.fileHandleForWriting
    output = stdout.fileHandleForReading
    do { try child.run() } catch {
      stop()
      throw error
    }
  }

  private func receive(_ data: Data, generation current: UUID) {
    guard current == generation else { return }
    guard !data.isEmpty else {
      terminated(generation: current)
      return
    }
    buffer.append(data)
    guard buffer.count <= 262_144 else {
      stop()
      return
    }
    while let newline = buffer.firstIndex(of: 10) {
      let line = Data(buffer[..<newline])
      buffer.removeSubrange(...newline)
      guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
        stop()
        return
      }
      if let id = object["id"] as? String {
        pending.removeValue(forKey: id)?.resume(returning: line)
      } else if let type = object["type"] as? String {
        switch type {
        case "progress": progress?(object["message"] as? String ?? "Preparing model…")
        case "ready":
          preparation?.resume()
          preparation = nil
          progress = nil
        case "error":
          preparation?.resume(throwing: LocalDeciderError.helper(object["message"] as? String ?? "Model setup failed."))
          preparation = nil
          progress = nil
        default: break
        }
      }
    }
  }

  private func expire(_ id: String) {
    guard let continuation = pending.removeValue(forKey: id) else { return }
    continuation.resume(throwing: LocalDeciderError.timedOut)
    stop()
  }

  private func cancel(_ id: String) {
    pending.removeValue(forKey: id)?.resume(throwing: CancellationError())
  }

  private func terminated(generation current: UUID) {
    guard current == generation else { return }
    stop()
  }
}
#endif
