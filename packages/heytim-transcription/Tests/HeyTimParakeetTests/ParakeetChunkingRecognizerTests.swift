import XCTest
@testable import HeyTimParakeet

final class ParakeetChunkingRecognizerTests: XCTestCase {
    func testSilenceDoesNotDecode() throws {
        var decodeCount = 0
        let recognizer = ParakeetChunkingRecognizer { _ in
            decodeCount += 1
            return "unexpected"
        }
        recognizer.begin()

        for _ in 0..<20 {
            let update = try recognizer.accept(samples(level: 0, count: 1_600))
            XCTAssertFalse(update.reachedEndpoint)
        }

        XCTAssertEqual(try recognizer.finish(), "")
        XCTAssertEqual(decodeCount, 0)
    }

    func testNaturalPauseFinalizesOneBoundedSegmentAndContinues() throws {
        var decodedSampleCounts: [Int] = []
        let recognizer = ParakeetChunkingRecognizer { samples in
            decodedSampleCounts.append(samples.count)
            return decodedSampleCounts.count == 1 ? "First thought." : "Second thought."
        }
        recognizer.begin()

        _ = try recognizer.accept(samples(level: 0.08, count: 8_000))
        let first = try recognizer.accept(
            samples(level: 0, count: ParakeetChunkingRecognizer.endpointSilenceSamples)
        )
        XCTAssertTrue(first.reachedEndpoint)
        XCTAssertEqual(first.transcript, "First thought.")

        _ = try recognizer.accept(samples(level: 0.08, count: 8_000))
        XCTAssertEqual(try recognizer.finish(), "Second thought.")
        XCTAssertEqual(decodedSampleCounts.count, 2)
        XCTAssertTrue(decodedSampleCounts.allSatisfy {
            $0 <= ParakeetChunkingRecognizer.maximumSegmentSamples
        })
    }

    func testUninterruptedSpeechIsCapped() throws {
        var decodedSampleCount = 0
        let recognizer = ParakeetChunkingRecognizer { samples in
            decodedSampleCount = samples.count
            return "Bounded segment."
        }
        recognizer.begin()

        let update = try recognizer.accept(samples(
            level: 0.08,
            count: ParakeetChunkingRecognizer.maximumSegmentSamples
        ))

        XCTAssertTrue(update.reachedEndpoint)
        XCTAssertEqual(update.transcript, "Bounded segment.")
        XCTAssertEqual(decodedSampleCount, ParakeetChunkingRecognizer.maximumSegmentSamples)
    }

    private func samples(level: Float, count: Int) -> [Float] {
        [Float](repeating: level, count: count)
    }
}
