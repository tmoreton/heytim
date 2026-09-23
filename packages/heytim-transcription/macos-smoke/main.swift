@preconcurrency import AVFoundation
import Foundation
import HeyTimParakeet

@main
enum HeyTimParakeetSmoke {
    static func main() throws {
        let modelDirectory = try ParakeetModelResources.bundledModelDirectory()
        let recognizer = try ParakeetChunkingRecognizer(modelDirectory: modelDirectory)
        recognizer.begin()
        if let path = CommandLine.arguments.dropFirst().first {
            let samples = try readSamples(from: URL(fileURLWithPath: path))
            _ = try recognizer.accept(samples)
            let transcript = try recognizer.finish()
            guard !transcript.isEmpty else { throw SmokeError.speechProducedNoText }
            print(transcript)
            return
        }
        _ = try recognizer.accept([Float](
            repeating: 0,
            count: ParakeetChunkingRecognizer.sampleRate * 2
        ))
        let transcript = try recognizer.finish()
        guard transcript.isEmpty else {
            throw SmokeError.silenceProducedText(transcript)
        }
        print("Parakeet loaded and decoded silence locally on macOS.")
    }

    private static func readSamples(from url: URL) throws -> [Float] {
        let file = try AVAudioFile(forReading: url)
        guard file.processingFormat.channelCount == 1,
              let source = AVAudioPCMBuffer(
                pcmFormat: file.processingFormat,
                frameCapacity: AVAudioFrameCount(file.length)
              ),
              let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: 16_000,
                channels: 1,
                interleaved: false
              )
        else { throw SmokeError.unsupportedAudio }
        try file.read(into: source)

        let buffer: AVAudioPCMBuffer
        if source.format == targetFormat {
            buffer = source
        } else {
            guard let converter = AVAudioConverter(
                from: source.format, to: targetFormat
            ), let converted = AVAudioPCMBuffer(
                pcmFormat: targetFormat,
                frameCapacity: AVAudioFrameCount(
                    ceil(Double(source.frameLength) * 16_000 / source.format.sampleRate) + 256
                )
            ) else { throw SmokeError.unsupportedAudio }
            var supplied = false
            var conversionError: NSError?
            let status = converter.convert(to: converted, error: &conversionError) {
                _, inputStatus in
                guard !supplied else {
                    inputStatus.pointee = .noDataNow
                    return nil
                }
                supplied = true
                inputStatus.pointee = .haveData
                return source
            }
            guard status != .error else {
                throw conversionError ?? SmokeError.unsupportedAudio
            }
            buffer = converted
        }
        guard let channel = buffer.floatChannelData?[0] else {
            throw SmokeError.unsupportedAudio
        }
        return Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
    }
}

private enum SmokeError: LocalizedError {
    case silenceProducedText(String)
    case speechProducedNoText
    case unsupportedAudio

    var errorDescription: String? {
        switch self {
        case .silenceProducedText(let text):
            return "The silence smoke test unexpectedly produced text: \(text)"
        case .speechProducedNoText:
            return "The speech smoke test unexpectedly produced no text."
        case .unsupportedAudio:
            return "The speech smoke test requires readable mono PCM audio."
        }
    }
}
