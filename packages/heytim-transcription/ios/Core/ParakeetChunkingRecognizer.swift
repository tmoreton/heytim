import Foundation

public struct ParakeetRecognitionUpdate: Sendable {
    public let transcript: String
    public let reachedEndpoint: Bool
}

/// Makes an offline Parakeet model practical for live and hour-plus capture.
/// Audio is decoded once at natural pauses, with a bounded fallback for speech
/// that contains no detectable pause. The full meeting is never retained here.
public final class ParakeetChunkingRecognizer {
    public static let sampleRate = 16_000

    static let endpointSilenceSamples = sampleRate * 4 / 5
    static let preRollSamples = sampleRate * 3 / 10
    static let minimumVoicedSamples = sampleRate / 4
    static let maximumSegmentSamples = sampleRate * 30

    private let decode: ([Float]) throws -> String
    private var pendingSamples: [Float] = []
    private var voicedSamples = 0
    private var trailingSilenceSamples = 0
    private var accepting = false

    public convenience init(modelDirectory: URL) throws {
        let backend = try SherpaOfflineRecognizer(modelDirectory: modelDirectory)
        self.init(decode: backend.decode(samples:))
    }

    init(decode: @escaping ([Float]) throws -> String) {
        self.decode = decode
    }

    public func begin() {
        reset(keepingCapacity: true)
        accepting = true
    }

    public func accept(_ samples: [Float]) throws -> ParakeetRecognitionUpdate {
        guard accepting, !samples.isEmpty else {
            return ParakeetRecognitionUpdate(transcript: "", reachedEndpoint: false)
        }

        let speech = Self.containsSpeech(samples)
        pendingSamples.append(contentsOf: samples)
        if speech {
            voicedSamples += samples.count
            trailingSilenceSamples = 0
        } else if voicedSamples > 0 {
            trailingSilenceSamples += samples.count
        } else if pendingSamples.count > Self.preRollSamples {
            pendingSamples.removeFirst(pendingSamples.count - Self.preRollSamples)
        }

        let reachedPause = voicedSamples >= Self.minimumVoicedSamples
            && trailingSilenceSamples >= Self.endpointSilenceSamples
        let reachedMaximum = pendingSamples.count >= Self.maximumSegmentSamples
        guard reachedPause || reachedMaximum else {
            return ParakeetRecognitionUpdate(transcript: "", reachedEndpoint: false)
        }

        return ParakeetRecognitionUpdate(
            transcript: try decodePendingSegment(),
            reachedEndpoint: true
        )
    }

    public func finish() throws -> String {
        guard accepting else { return "" }
        accepting = false
        guard voicedSamples >= Self.minimumVoicedSamples else {
            reset(keepingCapacity: true)
            return ""
        }
        return try decodePendingSegment()
    }

    public func discard() {
        accepting = false
        reset(keepingCapacity: false)
    }

    private func decodePendingSegment() throws -> String {
        let segment = pendingSamples
        reset(keepingCapacity: true)
        guard !segment.isEmpty else { return "" }
        return try decode(segment)
    }

    private func reset(keepingCapacity: Bool) {
        pendingSamples.removeAll(keepingCapacity: keepingCapacity)
        voicedSamples = 0
        trailingSilenceSamples = 0
    }

    private static func containsSpeech(_ samples: [Float]) -> Bool {
        var energy: Double = 0
        var peak: Float = 0
        var count = 0
        for index in stride(from: 0, to: samples.count, by: 8) {
            let sample = abs(samples[index])
            peak = max(peak, sample)
            energy += Double(sample * sample)
            count += 1
        }
        let rms = sqrt(energy / Double(max(1, count)))
        // Bias toward retaining quiet speech. False positives cost compute, while
        // false negatives lose words and cannot be repaired by meeting summary.
        return peak >= 0.015 || rms >= 0.004
    }
}
