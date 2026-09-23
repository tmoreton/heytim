import AVFoundation
import Foundation

/// Converts microphone buffers to the 16 kHz mono float samples Parakeet expects.
final class StreamingAudioConverter {
    private struct FormatKey: Equatable {
        let sampleRate: Double
        let formatID: AudioFormatID
        let formatFlags: AudioFormatFlags
        let bytesPerFrame: UInt32
        let channelsPerFrame: UInt32

        init(_ format: AVAudioFormat) {
            let description = format.streamDescription.pointee
            sampleRate = description.mSampleRate
            formatID = description.mFormatID
            formatFlags = description.mFormatFlags
            bytesPerFrame = description.mBytesPerFrame
            channelsPerFrame = description.mChannelsPerFrame
        }
    }

    private final class InputFeeder: @unchecked Sendable {
        private let lock = NSLock()
        private let buffer: AVAudioPCMBuffer
        private var supplied = false

        init(buffer: AVAudioPCMBuffer) {
            self.buffer = buffer
        }

        func next(status: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
            lock.lock()
            defer { lock.unlock() }
            guard !supplied else {
                status.pointee = .noDataNow
                return nil
            }
            supplied = true
            status.pointee = .haveData
            return buffer
        }
    }

    private let targetFormat: AVAudioFormat
    private var sourceKey: FormatKey?
    private var converter: AVAudioConverter?

    init() {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Double(ParakeetChunkingRecognizer.sampleRate),
            channels: 1,
            interleaved: false
        ) else { preconditionFailure("Unable to create the Parakeet audio format") }
        targetFormat = format
    }

    func reset() {
        converter?.reset()
    }

    func convert(_ buffer: AVAudioPCMBuffer) throws -> [Float] {
        guard buffer.frameLength > 0 else { return [] }
        if matchesTarget(buffer.format) {
            return samples(from: buffer)
        }

        let key = FormatKey(buffer.format)
        if converter == nil || sourceKey != key {
            guard let replacement = AVAudioConverter(from: buffer.format, to: targetFormat) else {
                throw ParakeetTranscriptionError.audioFormatUnavailable
            }
            replacement.sampleRateConverterAlgorithm = AVSampleRateConverterAlgorithm_MinimumPhase
            replacement.sampleRateConverterQuality = AVAudioQuality.max.rawValue
            converter = replacement
            sourceKey = key
        }
        guard let converter else {
            throw ParakeetTranscriptionError.audioFormatUnavailable
        }

        let ratio = targetFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(max(1, ceil(Double(buffer.frameLength) * ratio) + 256))
        guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
            throw ParakeetTranscriptionError.audioFormatUnavailable
        }
        let feeder = InputFeeder(buffer: buffer)
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, inputStatus in
            feeder.next(status: inputStatus)
        }
        if status == .error {
            throw ParakeetTranscriptionError.audioConversionFailed(error)
        }
        return samples(from: output)
    }

    private func matchesTarget(_ format: AVAudioFormat) -> Bool {
        format.sampleRate == targetFormat.sampleRate
            && format.channelCount == 1
            && format.commonFormat == .pcmFormatFloat32
            && !format.isInterleaved
    }

    private func samples(from buffer: AVAudioPCMBuffer) -> [Float] {
        guard let channel = buffer.floatChannelData?[0] else { return [] }
        return Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
    }
}
