import Foundation

/// Keeps endpoint-delimited phrases as one transcript while the microphone
/// remains active across natural pauses.
struct ContinuousTranscriptAccumulator {
    private(set) var committedTranscript = ""

    func rendering(_ currentPhrase: String) -> String {
        Self.join(committedTranscript, currentPhrase)
    }

    @discardableResult
    mutating func commit(_ currentPhrase: String) -> String {
        committedTranscript = rendering(currentPhrase)
        return committedTranscript
    }

    mutating func reset() {
        committedTranscript = ""
    }

    private static func join(_ committed: String, _ current: String) -> String {
        let transcript = [committed, current]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        guard let first = transcript.first else { return transcript }
        return first.uppercased() + transcript.dropFirst()
    }
}
