import Foundation

public enum NemotronTranscriptionError: LocalizedError {
    case audioConversionFailed(Error?)
    case audioFormatUnavailable
    case microphoneUnavailable
    case modelFileMissing(String)
    case modelLoadFailed
    case modelResourcesMissing

    public var errorDescription: String? {
        switch self {
        case .audioConversionFailed(let error):
            return "Microphone audio conversion failed: \(error?.localizedDescription ?? "unknown error")"
        case .audioFormatUnavailable:
            return "The microphone audio format cannot be converted to 16 kHz mono."
        case .microphoneUnavailable:
            return "No usable microphone input is available."
        case .modelFileMissing(let name):
            return "The bundled Nemotron model is missing \(name)."
        case .modelLoadFailed:
            return "The bundled Nemotron model could not be loaded."
        case .modelResourcesMissing:
            return "The bundled Nemotron model resources could not be found."
        }
    }
}

struct NemotronModelFiles {
    let directory: URL

    var encoder: URL { directory.appendingPathComponent("encoder.int8.onnx") }
    var decoder: URL { directory.appendingPathComponent("decoder.int8.onnx") }
    var joiner: URL { directory.appendingPathComponent("joiner.int8.onnx") }
    var tokens: URL { directory.appendingPathComponent("tokens.txt") }

    func validate() throws {
        for file in [encoder, decoder, joiner, tokens] where !FileManager.default.fileExists(atPath: file.path) {
            throw NemotronTranscriptionError.modelFileMissing(file.lastPathComponent)
        }
    }
}

public enum NemotronModelResources {
    public static let modelName = "nemotron-3.5-asr-streaming-0.6b-1120ms"

    public static func bundledModelDirectory() throws -> URL {
        #if SWIFT_PACKAGE
        return try locate(in: Bundle.module)
        #else
        let hosts = [Bundle.main, Bundle(for: ResourceMarker.self)]
        for host in hosts {
            if let resourceBundleURL = host.url(
                forResource: "FroggyBotNemotronResources",
                withExtension: "bundle"
            ), let resourceBundle = Bundle(url: resourceBundleURL),
               let directory = try? locate(in: resourceBundle) {
                return directory
            }
            if let directory = try? locate(in: host) {
                return directory
            }
        }
        throw NemotronTranscriptionError.modelResourcesMissing
        #endif
    }

    private static func locate(in bundle: Bundle) throws -> URL {
        if let direct = bundle.resourceURL?.appendingPathComponent(modelName),
           FileManager.default.fileExists(atPath: direct.path) {
            return direct
        }
        guard let root = bundle.resourceURL,
              let enumerator = FileManager.default.enumerator(
                at: root,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
              )
        else { throw NemotronTranscriptionError.modelResourcesMissing }

        for case let file as URL in enumerator where file.lastPathComponent == "encoder.int8.onnx" {
            let directory = file.deletingLastPathComponent()
            try NemotronModelFiles(directory: directory).validate()
            return directory
        }
        throw NemotronTranscriptionError.modelResourcesMissing
    }
}

private final class ResourceMarker: NSObject {}
