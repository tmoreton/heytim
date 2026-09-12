import Foundation
import FroggyBotNemotron

@main
enum FroggyBotNemotronSmoke {
    static func main() throws {
        let modelDirectory = try NemotronModelResources.bundledModelDirectory()
        let recognizer = try NemotronStreamingRecognizer(modelDirectory: modelDirectory)
        recognizer.begin()
        _ = recognizer.accept([Float](
            repeating: 0,
            count: NemotronStreamingRecognizer.sampleRate * 2
        ))
        let transcript = recognizer.finish()
        guard transcript.isEmpty else {
            throw SmokeError.silenceProducedText(transcript)
        }
        print("Nemotron loaded and decoded silence locally on macOS.")
    }
}

private enum SmokeError: LocalizedError {
    case silenceProducedText(String)

    var errorDescription: String? {
        switch self {
        case .silenceProducedText(let text):
            return "The silence smoke test unexpectedly produced text: \(text)"
        }
    }
}
