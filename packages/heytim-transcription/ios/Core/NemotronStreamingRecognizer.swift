import Foundation

public struct NemotronRecognitionUpdate: Sendable {
    public let transcript: String
    public let reachedEndpoint: Bool
}

/// Stateful streaming decoder. Callers must serialize access to an instance.
public final class NemotronStreamingRecognizer {
    public static let sampleRate = 16_000
    public static let modelChunkSamples = 5_120
    public static let finalizationTailSamples = 20_800

    private let recognizer: SherpaOnlineRecognizer
    private var pendingSamples: [Float] = []
    private var accepting = false

    public init(modelDirectory: URL) throws {
        recognizer = try SherpaOnlineRecognizer(modelDirectory: modelDirectory)
    }

    public func begin() {
        recognizer.reset()
        pendingSamples.removeAll(keepingCapacity: true)
        accepting = true
    }

    public func accept(_ samples: [Float]) -> NemotronRecognitionUpdate {
        guard accepting, !samples.isEmpty else {
            return NemotronRecognitionUpdate(transcript: currentText, reachedEndpoint: false)
        }

        pendingSamples.append(contentsOf: samples)
        while pendingSamples.count >= Self.modelChunkSamples {
            let chunk = Array(pendingSamples.prefix(Self.modelChunkSamples))
            pendingSamples.removeFirst(Self.modelChunkSamples)
            recognizer.accept(samples: chunk)
        }
        return NemotronRecognitionUpdate(
            transcript: currentText,
            reachedEndpoint: recognizer.reachedEndpoint
        )
    }

    public func finish() -> String {
        guard accepting else { return "" }
        if !pendingSamples.isEmpty {
            recognizer.accept(samples: pendingSamples)
            pendingSamples.removeAll(keepingCapacity: true)
        }
        recognizer.accept(samples: [Float](
            repeating: 0,
            count: Self.finalizationTailSamples
        ))
        recognizer.finishInput()
        accepting = false
        return currentText
    }

    public func discard() {
        pendingSamples.removeAll(keepingCapacity: false)
        accepting = false
    }

    private var currentText: String {
        recognizer.text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
