@preconcurrency import AVFoundation
import Foundation

public enum NemotronTranscriptionEvent: Sendable {
    case started
    case audioLevel(Float)
    case result(transcript: String, isFinal: Bool)
    case failed(code: String, message: String)
    case ended
}

/// Reusable Apple microphone-to-Nemotron pipeline for iOS and macOS clients.
public final class NemotronTranscriber: @unchecked Sendable {
    public typealias EventHandler = @Sendable (NemotronTranscriptionEvent) -> Void

    private enum Phase: Equatable {
        case idle
        case starting(UInt)
        case running(UInt)
        case stopping(UInt)
    }

    private let eventHandler: EventHandler
    private let processingQueue = DispatchQueue(
        label: "com.heytim.nemotron.processing",
        qos: .userInitiated
    )
    private let stateLock = NSLock()
    private let captureLock = NSLock()
    private let ingressLock = NSLock()
    private var phase = Phase.idle
    private var nextGeneration: UInt = 0
    private var queuedBufferCount = 0
    private var reportedOverflow = false
    private var recognizer: NemotronStreamingRecognizer?
    private var modelUnloadWorkItem: DispatchWorkItem?
    private let converter = StreamingAudioConverter()
    private var transcriptAccumulator = ContinuousTranscriptAccumulator()
    private var previousTranscript = ""
    private var lastAudioLevelEmission: TimeInterval = 0

    private lazy var capture = AppleAudioCapture(
        bufferHandler: { [weak self] buffer, generation in
            self?.enqueue(buffer, generation: generation)
        },
        eventHandler: { [weak self] event in
            self?.handleCaptureEvent(event)
        }
    )

    public init(eventHandler: @escaping EventHandler) {
        self.eventHandler = eventHandler
    }

    public func start() {
        stateLock.lock()
        guard phase == .idle else {
            stateLock.unlock()
            return
        }
        nextGeneration &+= 1
        let generation = nextGeneration
        phase = .starting(generation)
        stateLock.unlock()

        processingQueue.async { [weak self] in
            self?.startOnProcessingQueue(generation: generation)
        }
    }

    public func stop() {
        let generation: UInt
        stateLock.lock()
        switch phase {
        case .starting:
            phase = .idle
            stateLock.unlock()
            stopCapture()
            emit(.ended)
            processingQueue.async { [weak self] in
                self?.recognizer?.discard()
                self?.scheduleModelUnload()
            }
            return
        case .running(let activeGeneration):
            generation = activeGeneration
            phase = .stopping(activeGeneration)
        case .idle, .stopping:
            stateLock.unlock()
            return
        }
        stateLock.unlock()

        stopCapture()
        processingQueue.async { [weak self] in
            self?.finishOnProcessingQueue(generation: generation)
        }
    }

    public func abort() {
        abort(emitAbortError: true)
    }

    public func shutDown() {
        abort(emitAbortError: false)
        processingQueue.async { [weak self] in
            self?.modelUnloadWorkItem?.cancel()
            self?.modelUnloadWorkItem = nil
            self?.recognizer = nil
        }
    }

    /// Releases the large ONNX graph when Apple reports memory pressure.
    public func releaseModelIfIdle() {
        processingQueue.async { [weak self] in
            self?.releaseModelIfIdleOnProcessingQueue()
        }
    }

    private func startOnProcessingQueue(generation: UInt) {
        do {
            modelUnloadWorkItem?.cancel()
            modelUnloadWorkItem = nil
            if recognizer == nil {
                let modelDirectory = try NemotronModelResources.bundledModelDirectory()
                recognizer = try NemotronStreamingRecognizer(modelDirectory: modelDirectory)
            }
            guard isStarting(generation), let recognizer else { return }
            converter.reset()
            transcriptAccumulator.reset()
            previousTranscript = ""
            lastAudioLevelEmission = 0
            resetIngressState()
            recognizer.begin()

            captureLock.lock()
            defer { captureLock.unlock() }
            guard isStarting(generation) else {
                recognizer.discard()
                return
            }
            try capture.start(generation: generation)
            guard transitionToRunning(generation) else {
                capture.stop()
                recognizer.discard()
                return
            }
            emit(.started)
        } catch {
            failStart(generation: generation, error: error)
        }
    }

    private func process(_ buffer: AVAudioPCMBuffer, generation: UInt) {
        guard isProcessing(generation), let recognizer else { return }
        do {
            let samples = try converter.convert(buffer)
            guard !samples.isEmpty else { return }
            emitAudioLevelIfDue(samples)
            let update = recognizer.accept(samples)
            let transcript = transcriptAccumulator.rendering(update.transcript)
            if transcript != previousTranscript {
                previousTranscript = transcript
                emit(.result(transcript: transcript, isFinal: false))
            }
            if update.reachedEndpoint {
                let finalizedTranscript = transcriptAccumulator.commit(update.transcript)
                if !finalizedTranscript.isEmpty {
                    previousTranscript = finalizedTranscript
                    emit(.result(transcript: finalizedTranscript, isFinal: true))
                }
                // Endpointing separates phrases; only an explicit Stop ends
                // microphone capture and the overall dictation session.
                recognizer.begin()
            }
        } catch {
            failActiveSession(generation: generation, error: error)
        }
    }

    private func emitAudioLevelIfDue(_ samples: [Float]) {
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastAudioLevelEmission >= 0.07 else { return }
        lastAudioLevelEmission = now

        var energy: Double = 0
        var sampleCount = 0
        for index in stride(from: 0, to: samples.count, by: 16) {
            let sample = Double(samples[index])
            energy += sample * sample
            sampleCount += 1
        }
        let rms = sqrt(energy / Double(max(1, sampleCount)))
        let decibels = 20 * log10(max(rms, 0.000_001))
        let level = Float(min(1, max(0, (decibels + 55) / 45)))
        emit(.audioLevel(level))
    }

    private func enqueue(_ buffer: AVAudioPCMBuffer, generation: UInt) {
        ingressLock.lock()
        guard queuedBufferCount < 128 else {
            let shouldReport = !reportedOverflow
            reportedOverflow = true
            ingressLock.unlock()
            if shouldReport {
                DispatchQueue.main.async { [weak self] in
                    self?.failCurrentCapture(
                        message: "On-device transcription could not keep up with the microphone."
                    )
                }
            }
            return
        }
        queuedBufferCount += 1
        ingressLock.unlock()

        processingQueue.async { [weak self] in
            defer { self?.decrementQueuedBufferCount() }
            self?.process(buffer, generation: generation)
        }
    }

    private func decrementQueuedBufferCount() {
        ingressLock.lock()
        queuedBufferCount = max(0, queuedBufferCount - 1)
        ingressLock.unlock()
    }

    private func resetIngressState() {
        ingressLock.lock()
        queuedBufferCount = 0
        reportedOverflow = false
        ingressLock.unlock()
    }

    private func finishOnProcessingQueue(generation: UInt) {
        guard isStopping(generation), let recognizer else { return }
        let transcript = transcriptAccumulator.commit(recognizer.finish())
        if !transcript.isEmpty {
            emit(.result(transcript: transcript, isFinal: true))
        }
        transcriptAccumulator.reset()
        previousTranscript = ""
        stateLock.lock()
        if phase == .stopping(generation) {
            phase = .idle
        }
        stateLock.unlock()
        emit(.ended)
        scheduleModelUnload()
    }

    private func abort(emitAbortError: Bool) {
        stateLock.lock()
        guard phase != .idle else {
            stateLock.unlock()
            return
        }
        phase = .idle
        stateLock.unlock()
        stopCapture()
        processingQueue.async { [weak self] in
            guard let self else { return }
            self.recognizer?.discard()
            self.transcriptAccumulator.reset()
            self.previousTranscript = ""
            if emitAbortError {
                self.emit(.failed(code: "aborted", message: "Dictation was cancelled."))
            }
            self.emit(.ended)
            self.scheduleModelUnload()
        }
    }

    private func failStart(generation: UInt, error: Error) {
        stateLock.lock()
        guard phase == .starting(generation) || phase == .running(generation) else {
            stateLock.unlock()
            return
        }
        phase = .idle
        stateLock.unlock()
        stopCapture()
        recognizer?.discard()
        transcriptAccumulator.reset()
        previousTranscript = ""
        emitFailure(error)
        emit(.ended)
        scheduleModelUnload()
    }

    private func failActiveSession(generation: UInt, error: Error) {
        guard isProcessing(generation) else { return }
        stateLock.lock()
        phase = .idle
        stateLock.unlock()
        stopCapture()
        recognizer?.discard()
        transcriptAccumulator.reset()
        previousTranscript = ""
        emitFailure(error)
        emit(.ended)
        scheduleModelUnload()
    }

    private func emitFailure(_ error: Error) {
        let code: String
        switch error {
        case NemotronTranscriptionError.modelFileMissing,
             NemotronTranscriptionError.modelLoadFailed,
             NemotronTranscriptionError.modelResourcesMissing:
            code = "model-unavailable"
        case NemotronTranscriptionError.microphoneUnavailable:
            code = "audio-capture"
        default:
            code = "processing"
        }
        emit(.failed(code: code, message: error.localizedDescription))
    }

    private func handleCaptureEvent(_ event: AppleAudioCaptureEvent) {
        switch event {
        case .interrupted:
            failCurrentCapture(message: "Microphone capture was interrupted.")
        case .routeChanged:
            failCurrentCapture(message: "The microphone route changed.")
        case .servicesReset:
            failCurrentCapture(message: "Audio services restarted.")
        }
    }

    private func failCurrentCapture(message: String) {
        stateLock.lock()
        guard case .running = phase else {
            stateLock.unlock()
            return
        }
        phase = .idle
        stateLock.unlock()
        stopCapture()
        processingQueue.async { [weak self] in
            guard let self else { return }
            self.recognizer?.discard()
            self.transcriptAccumulator.reset()
            self.previousTranscript = ""
            self.emit(.failed(code: "audio-capture", message: message))
            self.emit(.ended)
            self.scheduleModelUnload()
        }
    }

    private func scheduleModelUnload() {
        modelUnloadWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.releaseModelIfIdleOnProcessingQueue()
        }
        modelUnloadWorkItem = workItem
        processingQueue.asyncAfter(deadline: .now() + 5 * 60, execute: workItem)
    }

    private func releaseModelIfIdleOnProcessingQueue() {
        stateLock.lock()
        let idle = phase == .idle
        stateLock.unlock()
        guard idle else { return }
        modelUnloadWorkItem?.cancel()
        modelUnloadWorkItem = nil
        recognizer = nil
        converter.reset()
        transcriptAccumulator.reset()
        previousTranscript = ""
    }

    private func stopCapture() {
        captureLock.lock()
        capture.stop()
        captureLock.unlock()
    }

    private func isStarting(_ generation: UInt) -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return phase == .starting(generation)
    }

    private func transitionToRunning(_ generation: UInt) -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        guard phase == .starting(generation) else { return false }
        phase = .running(generation)
        return true
    }

    private func isProcessing(_ generation: UInt) -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return phase == .running(generation) || phase == .stopping(generation)
    }

    private func isStopping(_ generation: UInt) -> Bool {
        stateLock.lock()
        defer { stateLock.unlock() }
        return phase == .stopping(generation)
    }

    private func emit(_ event: NemotronTranscriptionEvent) {
        DispatchQueue.main.async { [eventHandler] in eventHandler(event) }
    }
}
