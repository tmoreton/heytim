// Adapted from sherpa-onnx 1.13.8's Swift wrapper.
// Copyright 2023 Xiaomi Corporation. Licensed under Apache-2.0.

import Foundation
import SherpaOnnxC

private func cPointer(_ value: String) -> UnsafePointer<CChar>! {
    (value as NSString).utf8String
}

/// Thin owner for sherpa-onnx's offline recognizer. Parakeet TDT v3 is an
/// offline NeMo transducer, so each bounded speech segment gets its own stream.
final class SherpaOfflineRecognizer {
    private let recognizer: OpaquePointer

    init(modelDirectory: URL) throws {
        let files = ParakeetModelFiles(directory: modelDirectory)
        try files.validate()

        var model = SherpaOnnxOfflineModelConfig()
        model.transducer = SherpaOnnxOfflineTransducerModelConfig(
            encoder: cPointer(files.encoder.path),
            decoder: cPointer(files.decoder.path),
            joiner: cPointer(files.joiner.path)
        )
        model.tokens = cPointer(files.tokens.path)
        model.num_threads = 4
        model.provider = cPointer("cpu")
        model.model_type = cPointer("nemo_transducer")

        var config = SherpaOnnxOfflineRecognizerConfig()
        config.feat_config = SherpaOnnxFeatureConfig(sample_rate: 16_000, feature_dim: 80)
        config.model_config = model
        // Greedy search is the stable sherpa-onnx path for Parakeet TDT.
        config.decoding_method = cPointer("greedy_search")
        config.max_active_paths = 1

        guard let recognizer = SherpaOnnxCreateOfflineRecognizer(&config) else {
            throw ParakeetTranscriptionError.modelLoadFailed
        }
        self.recognizer = recognizer
    }

    deinit {
        SherpaOnnxDestroyOfflineRecognizer(recognizer)
    }

    func decode(samples: [Float]) throws -> String {
        guard !samples.isEmpty,
              let stream = SherpaOnnxCreateOfflineStream(recognizer)
        else { return "" }
        defer { SherpaOnnxDestroyOfflineStream(stream) }

        SherpaOnnxAcceptWaveformOffline(
            stream,
            Int32(ParakeetChunkingRecognizer.sampleRate),
            samples,
            Int32(samples.count)
        )
        SherpaOnnxDecodeOfflineStream(recognizer, stream)
        guard let result = SherpaOnnxGetOfflineStreamResult(stream) else {
            throw ParakeetTranscriptionError.modelLoadFailed
        }
        defer { SherpaOnnxDestroyOfflineRecognizerResult(result) }
        guard let text = result.pointee.text else { return "" }
        return String(cString: text).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
