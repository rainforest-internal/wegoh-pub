import XCTest
@testable import WegoH

final class TripVoiceProtocolTests: XCTestCase {
    private let lease = String(repeating: "a", count: 32)
    private let speaker = "team-" + String(repeating: "a", count: 40)
    func testPCMHasLittleEndianSequenceAndExactTwentyMillisecondPayload() throws {
        let pcm = Data(repeating: 127, count: 640)
        let frame = try TripVoiceWire.frame(sequence: 0x01020304, pcm: pcm)
        XCTAssertEqual(Array(frame.prefix(4)), [4, 3, 2, 1])
        let decoded = try TripVoiceWire.pcm(frame, after: nil)
        XCTAssertEqual(decoded.0, 0x01020304); XCTAssertEqual(decoded.1, pcm)
    }
    func testMalformedOrOutOfSequenceAudioIsRejected() throws {
        XCTAssertThrowsError(try TripVoiceWire.frame(sequence: 0, pcm: Data(count: 639)))
        XCTAssertThrowsError(try TripVoiceWire.pcm(Data(count: 645), after: nil))
        let frame = try TripVoiceWire.frame(sequence: 7, pcm: Data(count: 640))
        XCTAssertThrowsError(try TripVoiceWire.pcm(frame, after: 7))
        XCTAssertThrowsError(try TripVoiceWire.pcm(frame, after: 5))
        XCTAssertNoThrow(try TripVoiceWire.pcm(frame, after: 6))
    }
    func testOnlyHeldGrantedFloorCanStartCapture() {
        var state = TripVoiceFloorState()
        XCTAssertTrue(state.request())
        XCTAssertFalse(state.speaking)
        XCTAssertTrue(state.granted(.init(leaseId: lease, speakerId: speaker)))
        XCTAssertTrue(state.speaking)
        XCTAssertTrue(state.release())
        XCTAssertFalse(state.speaking)
        state.ended(lease)
        XCTAssertNil(state.floor)
        XCTAssertTrue(state.request())
    }
    func testReleaseBeforeDelayedGrantNeverStartsCapture() {
        var state = TripVoiceFloorState()
        XCTAssertTrue(state.request()); XCTAssertTrue(state.release())
        XCTAssertFalse(state.granted(.init(leaseId: lease, speakerId: speaker)))
        XCTAssertFalse(state.speaking); XCTAssertTrue(state.stopping)
        XCTAssertFalse(state.request())
        state.ended(lease)
        XCTAssertTrue(state.request())
    }
    func testObservedOtherSpeakerRequiresFreshPress() {
        var state = TripVoiceFloorState()
        XCTAssertTrue(state.request())
        state.started(.init(leaseId: lease, speakerId: speaker))
        XCTAssertFalse(state.held); XCTAssertFalse(state.speaking)
        XCTAssertFalse(state.request())
        XCTAssertFalse(state.granted(.init(leaseId: String(repeating: "b", count: 32), speakerId: speaker)))
    }
    func testBusyReplyKeepsObservedSpeakerAndReleaseIsIdempotent() {
        var state = TripVoiceFloorState()
        XCTAssertTrue(state.request())
        state.started(.init(leaseId: lease, speakerId: speaker))
        state.denied()
        XCTAssertEqual(state.floor?.leaseId, lease)
        XCTAssertFalse(state.requested)
        XCTAssertFalse(state.request())
        state.ended(lease)
        XCTAssertTrue(state.request())
        XCTAssertTrue(state.release())
        XCTAssertFalse(state.release())
    }
    func testEndingOldLeaseCannotClearCurrentSpeaker() {
        var state = TripVoiceFloorState()
        state.started(.init(leaseId: lease, speakerId: speaker))
        state.ended(String(repeating: "b", count: 32))
        XCTAssertEqual(state.floor?.leaseId, lease)
        state.reset(); XCTAssertNil(state.floor); XCTAssertFalse(state.requested)
    }
    func testControlFormatAndIdentityAreValidated() throws {
        let json = """
        {"type":"ready","leaseSeconds":15,"automaticTransmit":false,"floor":null,"format":{"encoding":"pcm_s16le","sampleRate":16000,"channels":1,"samplesPerFrame":320,"frameBytes":644,"sequence":"uint32-le-first0"}}
        """
        XCTAssertTrue(try TripVoiceWire.control(json).format?.isValid == true)
        XCTAssertFalse(try TripVoiceWire.control(json.replacingOccurrences(of: "16000", with: "48000")).format?.isValid == true)
        XCTAssertThrowsError(try TripVoiceWire.control(String(repeating: "x", count: 2049)))
        let grant = try TripVoiceWire.control("{\"type\":\"floor-granted\",\"leaseId\":\"\(lease)\",\"speakerId\":\"\(speaker)\",\"leaseSeconds\":15}")
        XCTAssertEqual(try grant.validatedFloor(members: [speaker]).speakerId, speaker)
        XCTAssertThrowsError(try grant.validatedFloor(members: []))
    }
    func testParticipationRequiresMembershipRevisionAndCurrentTripID() {
        let state = TripVoiceParticipation(tripId: String(repeating: "a", count: 32), participating: true,
                                           memberJoinedAt: "2026-11-14T00:00:00Z", revision: 1)
        XCTAssertTrue(state.isValid)
        var fractional = state; fractional.memberJoinedAt = "2026-11-14T00:00:00.123456+00:00"; XCTAssertTrue(fractional.isValid)
        var invalid = state; invalid.revision = 0; XCTAssertFalse(invalid.isValid)
        invalid = state; invalid.memberJoinedAt = "yesterday"; XCTAssertFalse(invalid.isValid)
    }
}
