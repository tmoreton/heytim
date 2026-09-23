import AVFoundation
import HeyTimParakeet
import Observation

@MainActor @Observable
public final class DictationModel {
  public private(set) var isRecording = false
  public private(set) var isStarting = false
  public private(set) var audioLevels: [Float] = []
  public var transcript = ""
  public var errorMessage: String?
  @ObservationIgnored private var transcriber: ParakeetTranscriber?
  @ObservationIgnored private var sessionID: UUID?

  public init() {}

  public func toggle() {
    if isStarting {
      cancel()
      return
    }
    if isRecording {
      transcriber?.stop()
      return
    }
    let requestedSessionID = UUID()
    sessionID = requestedSessionID
    isStarting = true
    audioLevels = []
    errorMessage = nil
    AVCaptureDevice.requestAccess(for: .audio) { [weak self] allowed in
      Task { @MainActor in
        guard let self, self.sessionID == requestedSessionID else { return }
        guard allowed else {
          self.isStarting = false
          self.sessionID = nil
          self.errorMessage = "Microphone access is required for on-device dictation."
          return
        }
        let transcriber = ParakeetTranscriber { [weak self] event in
          Task { @MainActor in self?.receive(event, sessionID: requestedSessionID) }
        }
        self.transcriber = transcriber
        transcriber.start()
      }
    }
  }

  public func consumeTranscript() -> String {
    defer { transcript = "" }
    return transcript
  }

  public func cancel() {
    sessionID = nil
    transcriber?.shutDown()
    transcriber = nil
    isStarting = false
    isRecording = false
    audioLevels = []
    transcript = ""
  }

  public func shutDown() { cancel() }

  private func receive(_ event: ParakeetTranscriptionEvent, sessionID: UUID) {
    guard self.sessionID == sessionID else { return }
    switch event {
    case .started:
      isStarting = false
      isRecording = true
    case .audioLevel(let level):
      audioLevels.append(level)
      if audioLevels.count > 96 { audioLevels.removeFirst(audioLevels.count - 96) }
    case .result(let value, _): transcript = value
    case .failed(_, let message): errorMessage = message
    case .ended:
      isStarting = false
      isRecording = false
      audioLevels = []
      self.sessionID = nil
      transcriber = nil
    }
  }
}
