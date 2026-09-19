import AVFoundation
import Foundation

enum AppleAudioCaptureEvent {
    case interrupted
    case routeChanged
    case servicesReset
}

/// AVAudioEngine capture shared by the Expo iOS bridge and future native macOS clients.
final class AppleAudioCapture: @unchecked Sendable {
    typealias BufferHandler = @Sendable (AVAudioPCMBuffer, UInt) -> Void
    typealias EventHandler = @Sendable (AppleAudioCaptureEvent) -> Void

    private var engine = AVAudioEngine()
    private let bufferHandler: BufferHandler
    private let eventHandler: EventHandler
    private let callbackCondition = NSCondition()
    private var callbacksInFlight = 0
    private var acceptsCallbacks = false
    private var tapInstalled = false
    private var running = false
    private var notificationTokens: [NSObjectProtocol] = []

    init(
        bufferHandler: @escaping BufferHandler,
        eventHandler: @escaping EventHandler
    ) {
        self.bufferHandler = bufferHandler
        self.eventHandler = eventHandler
        #if os(iOS)
        installIOSObservers()
        #endif
    }

    deinit {
        notificationTokens.forEach(NotificationCenter.default.removeObserver)
    }

    func start(generation: UInt) throws {
        guard !running else { return }
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(
            .playAndRecord,
            mode: .measurement,
            options: [.defaultToSpeaker, .allowBluetoothHFP, .mixWithOthers]
        )
        try session.setActive(true)
        #endif

        do {
            let input = engine.inputNode
            let format = input.inputFormat(forBus: 0)
            guard Self.isUsable(format) else {
                throw NemotronTranscriptionError.microphoneUnavailable
            }

            callbackCondition.lock()
            acceptsCallbacks = true
            callbackCondition.unlock()
            input.installTap(onBus: 0, bufferSize: 4_096, format: format) {
                [weak self] buffer, _ in
                guard let self, self.beginCallback() else { return }
                defer { self.endCallback() }
                guard let copy = Self.copy(buffer) else { return }
                self.bufferHandler(copy, generation)
            }
            tapInstalled = true
            engine.prepare()
            try engine.start()
            running = true
        } catch {
            stop()
            throw error
        }
    }

    /// Removes the tap and waits for any callback already in flight.
    func stop() {
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        if running || engine.isRunning {
            engine.stop()
        }
        running = false

        callbackCondition.lock()
        acceptsCallbacks = false
        while callbacksInFlight > 0 {
            callbackCondition.wait()
        }
        callbackCondition.unlock()
        engine.reset()

        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: [.notifyOthersOnDeactivation]
        )
        #endif
    }

    private func beginCallback() -> Bool {
        callbackCondition.lock()
        defer { callbackCondition.unlock() }
        guard acceptsCallbacks else { return false }
        callbacksInFlight += 1
        return true
    }

    private func endCallback() {
        callbackCondition.lock()
        callbacksInFlight -= 1
        if callbacksInFlight == 0 {
            callbackCondition.broadcast()
        }
        callbackCondition.unlock()
    }

    #if os(iOS)
    private func installIOSObservers() {
        let center = NotificationCenter.default
        let session = AVAudioSession.sharedInstance()
        notificationTokens.append(center.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: session,
            queue: .main
        ) { [weak self] notification in
            guard let rawValue = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  AVAudioSession.InterruptionType(rawValue: rawValue) == .began
            else { return }
            self?.eventHandler(.interrupted)
        })
        notificationTokens.append(center.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: session,
            queue: .main
        ) { [weak self] notification in
            guard let rawValue = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  let reason = AVAudioSession.RouteChangeReason(rawValue: rawValue)
            else { return }

            // Configuring our own recording session emits `.categoryChange`.
            // Only restart for changes that can invalidate the input format.
            switch reason {
            case .newDeviceAvailable,
                 .oldDeviceUnavailable,
                 .noSuitableRouteForCategory,
                 .routeConfigurationChange:
                self?.eventHandler(.routeChanged)
            default:
                break
            }
        })
        notificationTokens.append(center.addObserver(
            forName: AVAudioSession.mediaServicesWereResetNotification,
            object: session,
            queue: .main
        ) { [weak self] _ in
            guard let self else { return }
            self.stop()
            self.engine = AVAudioEngine()
            self.eventHandler(.servicesReset)
        })
    }
    #endif

    private static func isUsable(_ format: AVAudioFormat) -> Bool {
        format.sampleRate.isFinite
            && format.sampleRate > 0
            && format.channelCount > 0
            && format.channelCount <= 8
            && !format.isInterleaved
            && (format.commonFormat == .pcmFormatFloat32 || format.commonFormat == .pcmFormatInt16)
    }

    private static func copy(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard buffer.frameLength > 0,
              let copy = AVAudioPCMBuffer(
                pcmFormat: buffer.format,
                frameCapacity: buffer.frameLength
              )
        else { return nil }
        copy.frameLength = buffer.frameLength
        let channelCount = Int(buffer.format.channelCount)
        let frameCount = Int(buffer.frameLength)
        if let source = buffer.floatChannelData, let destination = copy.floatChannelData {
            for channel in 0..<channelCount {
                destination[channel].update(from: source[channel], count: frameCount)
            }
            return copy
        }
        if let source = buffer.int16ChannelData, let destination = copy.int16ChannelData {
            for channel in 0..<channelCount {
                destination[channel].update(from: source[channel], count: frameCount)
            }
            return copy
        }
        return nil
    }
}
