import AVFoundation
import ExpoModulesCore
import UIKit

public final class FroggyBotTranscriptionModule: Module {
    private var memoryWarningObserver: NSObjectProtocol?
    private lazy var transcriber = NemotronTranscriber { [weak self] event in
        self?.handle(event)
    }

    public func definition() -> ModuleDefinition {
        Name("FroggyBotTranscription")

        Events("start", "result", "error", "end")

        Constant("isAvailable") { true }
        Constant("modelName") { NemotronModelResources.modelName }

        OnCreate { [weak self] in
            self?.memoryWarningObserver = NotificationCenter.default.addObserver(
                forName: UIApplication.didReceiveMemoryWarningNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                self?.transcriber.releaseModelIfIdle()
            }
        }

        AsyncFunction("requestMicrophonePermission") { (promise: Promise) in
            AVAudioApplication.requestRecordPermission { granted in
                promise.resolve(granted)
            }
        }

        Function("start") { [weak self] in
            self?.transcriber.start()
        }

        Function("stop") { [weak self] in
            self?.transcriber.stop()
        }

        Function("abort") { [weak self] in
            self?.transcriber.abort()
        }

        OnDestroy { [weak self] in
            if let observer = self?.memoryWarningObserver {
                NotificationCenter.default.removeObserver(observer)
            }
            self?.memoryWarningObserver = nil
            self?.transcriber.shutDown()
        }
    }

    private func handle(_ event: NemotronTranscriptionEvent) {
        switch event {
        case .started:
            sendEvent("start")
        case .result(let transcript, let isFinal):
            sendEvent("result", [
                "transcript": transcript,
                "isFinal": isFinal,
            ])
        case .failed(let code, let message):
            sendEvent("error", [
                "code": code,
                "message": message,
            ])
        case .ended:
            sendEvent("end")
        }
    }
}
