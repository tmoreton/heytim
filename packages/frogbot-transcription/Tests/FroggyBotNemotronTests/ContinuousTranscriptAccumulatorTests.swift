import XCTest
@testable import FroggyBotNemotron

final class ContinuousTranscriptAccumulatorTests: XCTestCase {
    func testKeepsCommittedSpeechAcrossNaturalPauses() {
        var transcript = ContinuousTranscriptAccumulator()

        XCTAssertEqual(transcript.rendering("hello world"), "Hello world")
        XCTAssertEqual(transcript.commit("hello world"), "Hello world")
        XCTAssertEqual(
            transcript.rendering("we are talking again"),
            "Hello world we are talking again"
        )
        XCTAssertEqual(
            transcript.commit("we are talking again"),
            "Hello world we are talking again"
        )
    }

    func testEmptyEndpointDoesNotEraseCommittedSpeech() {
        var transcript = ContinuousTranscriptAccumulator()

        transcript.commit("keep this phrase")
        XCTAssertEqual(transcript.commit("   "), "Keep this phrase")
    }

    func testResetStartsANewDictationSession() {
        var transcript = ContinuousTranscriptAccumulator()

        transcript.commit("old session")
        transcript.reset()

        XCTAssertEqual(transcript.rendering("new session"), "New session")
    }
}
