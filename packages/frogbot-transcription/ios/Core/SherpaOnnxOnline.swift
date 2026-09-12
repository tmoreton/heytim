// Adapted from sherpa-onnx 1.13.8's Swift wrapper.
// Copyright 2023 Xiaomi Corporation. Licensed under Apache-2.0.

import Foundation
import SherpaOnnxC

private func cPointer(_ value: String) -> UnsafePointer<CChar>! {
    (value as NSString).utf8String
}

private func onlineTransducerConfig(
    encoder: String = "",
    decoder: String = "",
    joiner: String = ""
) -> SherpaOnnxOnlineTransducerModelConfig {
    SherpaOnnxOnlineTransducerModelConfig(
        encoder: cPointer(encoder),
        decoder: cPointer(decoder),
        joiner: cPointer(joiner)
    )
}

private func onlineParaformerConfig(
    encoder: String = "",
    decoder: String = ""
) -> SherpaOnnxOnlineParaformerModelConfig {
    SherpaOnnxOnlineParaformerModelConfig(
        encoder: cPointer(encoder),
        decoder: cPointer(decoder)
    )
}

private func onlineZipformer2CtcConfig(model: String = "")
    -> SherpaOnnxOnlineZipformer2CtcModelConfig {
    SherpaOnnxOnlineZipformer2CtcModelConfig(model: cPointer(model))
}

private func onlineNemoCtcConfig(model: String = "")
    -> SherpaOnnxOnlineNemoCtcModelConfig {
    SherpaOnnxOnlineNemoCtcModelConfig(model: cPointer(model))
}

private func onlineToneCtcConfig(model: String = "")
    -> SherpaOnnxOnlineToneCtcModelConfig {
    SherpaOnnxOnlineToneCtcModelConfig(model: cPointer(model))
}

private func onlineModelConfig(
    tokens: String,
    transducer: SherpaOnnxOnlineTransducerModelConfig,
    numThreads: Int = 2,
    provider: String = "cpu"
) -> SherpaOnnxOnlineModelConfig {
    SherpaOnnxOnlineModelConfig(
        transducer: transducer,
        paraformer: onlineParaformerConfig(),
        zipformer2_ctc: onlineZipformer2CtcConfig(),
        tokens: cPointer(tokens),
        num_threads: Int32(numThreads),
        provider: cPointer(provider),
        debug: 0,
        model_type: cPointer(""),
        modeling_unit: cPointer("cjkchar"),
        bpe_vocab: cPointer(""),
        tokens_buf: cPointer(""),
        tokens_buf_size: 0,
        nemo_ctc: onlineNemoCtcConfig(),
        t_one_ctc: onlineToneCtcConfig()
    )
}

private func featureConfig() -> SherpaOnnxFeatureConfig {
    SherpaOnnxFeatureConfig(sample_rate: 16_000, feature_dim: 80)
}

private func ctcFstConfig() -> SherpaOnnxOnlineCtcFstDecoderConfig {
    SherpaOnnxOnlineCtcFstDecoderConfig(graph: cPointer(""), max_active: 3_000)
}

private func homophoneConfig() -> SherpaOnnxHomophoneReplacerConfig {
    SherpaOnnxHomophoneReplacerConfig(
        dict_dir: cPointer(""),
        lexicon: cPointer(""),
        rule_fsts: cPointer("")
    )
}

private func onlineRecognizerConfig(
    model: SherpaOnnxOnlineModelConfig
) -> SherpaOnnxOnlineRecognizerConfig {
    SherpaOnnxOnlineRecognizerConfig(
        feat_config: featureConfig(),
        model_config: model,
        decoding_method: cPointer("greedy_search"),
        max_active_paths: 1,
        enable_endpoint: 1,
        rule1_min_trailing_silence: 2.4,
        rule2_min_trailing_silence: 1.2,
        rule3_min_utterance_length: 30,
        hotwords_file: cPointer(""),
        hotwords_score: 1.5,
        ctc_fst_decoder_config: ctcFstConfig(),
        rule_fsts: cPointer(""),
        rule_fars: cPointer(""),
        blank_penalty: 0,
        hotwords_buf: cPointer(""),
        hotwords_buf_size: 0,
        hr: homophoneConfig()
    )
}

final class SherpaOnlineRecognizer {
    private let recognizer: OpaquePointer
    private let stream: OpaquePointer

    init(modelDirectory: URL) throws {
        let files = NemotronModelFiles(directory: modelDirectory)
        try files.validate()

        let transducer = onlineTransducerConfig(
            encoder: files.encoder.path,
            decoder: files.decoder.path,
            joiner: files.joiner.path
        )
        let model = onlineModelConfig(
            tokens: files.tokens.path,
            transducer: transducer
        )
        var config = onlineRecognizerConfig(model: model)
        guard let recognizer = SherpaOnnxCreateOnlineRecognizer(&config) else {
            throw NemotronTranscriptionError.modelLoadFailed
        }
        guard let stream = SherpaOnnxCreateOnlineStream(recognizer) else {
            SherpaOnnxDestroyOnlineRecognizer(recognizer)
            throw NemotronTranscriptionError.modelLoadFailed
        }
        self.recognizer = recognizer
        self.stream = stream
        setLanguageAuto()
    }

    deinit {
        SherpaOnnxDestroyOnlineStream(stream)
        SherpaOnnxDestroyOnlineRecognizer(recognizer)
    }

    func reset() {
        SherpaOnnxOnlineStreamReset(recognizer, stream)
        setLanguageAuto()
    }

    func accept(samples: [Float]) {
        SherpaOnnxOnlineStreamAcceptWaveform(
            stream,
            16_000,
            samples,
            Int32(samples.count)
        )
        decodeAvailableFrames()
    }

    func finishInput() {
        SherpaOnnxOnlineStreamInputFinished(stream)
        decodeAvailableFrames()
    }

    var text: String {
        guard let result = SherpaOnnxGetOnlineStreamResult(recognizer, stream) else {
            return ""
        }
        defer { SherpaOnnxDestroyOnlineRecognizerResult(result) }
        guard let value = result.pointee.text else { return "" }
        return String(cString: value)
    }

    var reachedEndpoint: Bool {
        SherpaOnnxOnlineStreamIsEndpoint(recognizer, stream) != 0
    }

    private func setLanguageAuto() {
        SherpaOnnxOnlineStreamSetOption(stream, cPointer("language"), cPointer("auto"))
    }

    private func decodeAvailableFrames() {
        while SherpaOnnxIsOnlineStreamReady(recognizer, stream) != 0 {
            SherpaOnnxDecodeOnlineStream(recognizer, stream)
        }
    }
}
