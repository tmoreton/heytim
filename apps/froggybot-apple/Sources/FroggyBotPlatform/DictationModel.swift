import AVFoundation
import FroggyBotNemotron
import Observation

@MainActor @Observable
public final class DictationModel {
  public private(set) var isRecording = false
  public private(set) var isStarting = false
  public var transcript = ""
  public var errorMessage: String?
  @ObservationIgnored private var transcriber: NemotronTranscriber?

  public init() {}

  public func toggle() {
    if isRecording || isStarting {
      transcriber?.stop()
      return
    }
    isStarting = true
    errorMessage = nil
    AVCaptureDevice.requestAccess(for: .audio) { [weak self] allowed in
      Task { @MainActor in
        guard let self else { return }
        guard allowed else {
          self.isStarting = false
          self.errorMessage = "Microphone access is required for on-device dictation."
          return
        }
        let transcriber = NemotronTranscriber { [weak self] event in
          Task { @MainActor in self?.receive(event) }
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

  public func shutDown() {
    transcriber?.shutDown()
    transcriber = nil
  }

  private func receive(_ event: NemotronTranscriptionEvent) {
    switch event {
    case .started:
      isStarting = false
      isRecording = true
    case .result(let value, _): transcript = value
    case .failed(_, let message): errorMessage = message
    case .ended:
      isStarting = false
      isRecording = false
    }
  }
}
