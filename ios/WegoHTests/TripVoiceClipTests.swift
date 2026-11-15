import XCTest
@testable import WegoH

final class TripVoiceClipTests: XCTestCase {
    private let boot = String(repeating: "a", count: 32)
    private let speaker = "team-" + String(repeating: "b", count: 40)
    private func clip(_ sequence: Int) -> TripVoiceClip {
        TripVoiceClip(id: String(format: "%032x", sequence), speakerId: speaker, sequence: sequence, durationMs: 20)
    }
    func testRecordingAccumulatesPCMAndEncodesOneCompletePayload() throws {
        var draft = TripVoiceClipDraft(clientMessageId: boot)
        XCTAssertThrowsError(try draft.payload())
        for value in 0..<25 { try draft.append(Data(repeating: UInt8(value), count: 640)) }
        XCTAssertEqual(draft.durationMs, 500)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: draft.payload()) as? [String: String])
        XCTAssertEqual(body["clientMessageId"], boot)
        XCTAssertEqual(Data(base64Encoded: try XCTUnwrap(body["pcmBase64"])), draft.pcm)
        XCTAssertEqual(try draft.payload(), try draft.payload())
    }
    func testRecordingStopsAtFifteenSecondsWithoutGrowing() throws {
        var draft = TripVoiceClipDraft(clientMessageId: boot)
        for _ in 0..<900 { try draft.append(Data(repeating: 0, count: 640)) }
        XCTAssertEqual(draft.pcm.count, 480_000)
        XCTAssertEqual(draft.durationMs, 15_000)
        XCTAssertTrue(draft.isFull)
        XCTAssertThrowsError(try draft.append(Data(repeating: 0, count: 639)))
    }
    func testFullRecordingPayloadKeepsBase64SlashesLiteralWithinServerBodyLimit() throws {
        var draft = TripVoiceClipDraft(clientMessageId: boot)
        for _ in 0..<750 { try draft.append(Data(repeating: 0xFF, count: 640)) }
        XCTAssertTrue(draft.isFull)
        XCTAssertEqual(draft.pcm.base64EncodedString(), String(repeating: "/", count: 640_000))
        let payload = try draft.payload()
        XCTAssertLessThanOrEqual(payload.count, 700_000)
        XCTAssertNil(payload.range(of: Data(#"\/"#.utf8)))
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: payload) as? [String: String])
        XCTAssertEqual(Data(base64Encoded: try XCTUnwrap(body["pcmBase64"])), draft.pcm)
    }
    func testExpiredDraftCannotBeRetriedAfterServerDedupWindow() throws {
        var draft = TripVoiceClipDraft(clientMessageId: boot, startedAt: .now.advanced(by: .seconds(-61)))
        try draft.append(Data(repeating: 0, count: 640))
        XCTAssertTrue(draft.isExpired)
        XCTAssertThrowsError(try draft.payload())
    }
    func testCaptureFinishIsAtomicAndLateAudioIsDiscarded() throws {
        let recorder = TripVoiceClipCapture(clientMessageId: boot)
        for _ in 0..<25 { XCTAssertFalse(try recorder.append(Data(repeating: 0, count: 640))) }
        let draft = try XCTUnwrap(recorder.finish())
        XCTAssertEqual(draft.durationMs, 500)
        XCTAssertFalse(try recorder.append(Data(repeating: 0, count: 640)))
        XCTAssertNil(recorder.finish())
    }
    func testConcurrentCaptureCannotExceedTheLimit() {
        let recorder = TripVoiceClipCapture(clientMessageId: boot)
        DispatchQueue.concurrentPerform(iterations: 1000) { _ in _ = try? recorder.append(Data(repeating: 0, count: 640)) }
        XCTAssertEqual(recorder.finish()?.pcm.count, 480_000)
    }
    func testInboxStartsAtCurrentCursorAndDoesNotReplayDuplicates() throws {
        var inbox = TripVoiceClipInbox()
        try inbox.ingest(.init(cursor: boot + ":4", clips: []), excluding: [])
        try inbox.ingest(.init(cursor: boot + ":6", clips: [clip(5), clip(6)]), excluding: [])
        try inbox.ingest(.init(cursor: boot + ":6", clips: [clip(5), clip(6)]), excluding: [])
        XCTAssertEqual(inbox.next(), clip(5))
        XCTAssertEqual(inbox.next(), clip(6))
        XCTAssertNil(inbox.next())
    }
    func testInboxExcludesMutedSpeakersAndLimitsPendingMessages() throws {
        var inbox = TripVoiceClipInbox()
        try inbox.ingest(.init(cursor: boot + ":0", clips: []), excluding: [])
        try inbox.ingest(.init(cursor: boot + ":1", clips: [clip(1)]), excluding: [speaker])
        XCTAssertNil(inbox.next())
        try inbox.ingest(.init(cursor: boot + ":10", clips: (2...10).map(clip)), excluding: [])
        XCTAssertEqual(inbox.count, 4)
        XCTAssertEqual(inbox.next(), clip(7))
        inbox.discard(speaker: speaker)
        XCTAssertNil(inbox.next())
    }
    func testRestartClearsPendingAndCannotInjectOldHistory() throws {
        var inbox = TripVoiceClipInbox()
        try inbox.ingest(.init(cursor: boot + ":0", clips: []), excluding: [])
        try inbox.ingest(.init(cursor: boot + ":1", clips: [clip(1)]), excluding: [])
        let newBoot = String(repeating: "c", count: 32)
        try inbox.ingest(.init(cursor: newBoot + ":3", clips: []), excluding: [])
        XCTAssertNil(inbox.next())
        XCTAssertThrowsError(try inbox.ingest(.init(cursor: newBoot + ":2", clips: []), excluding: []))
        var fresh = TripVoiceClipInbox()
        XCTAssertThrowsError(try fresh.ingest(.init(cursor: boot + ":1", clips: [clip(1)]), excluding: []))
    }
    func testInboxRejectsUnorderedOrForgedMetadata() throws {
        var inbox = TripVoiceClipInbox()
        try inbox.ingest(.init(cursor: boot + ":0", clips: []), excluding: [])
        XCTAssertThrowsError(try inbox.ingest(.init(cursor: boot + ":2", clips: [clip(2), clip(1)]), excluding: []))
        XCTAssertThrowsError(try inbox.ingest(.init(cursor: boot + ":2", clips: [clip(1), clip(1)]), excluding: []))
        XCTAssertThrowsError(try inbox.ingest(.init(cursor: "invalid", clips: []), excluding: []))
        XCTAssertThrowsError(try inbox.ingest(.init(cursor: boot + ":1", clips: [clip(2)]), excluding: []))
    }
    func testWholeClipContentMustMatchAuthorizedMetadata() throws {
        let metadata = clip(1)
        let pcm = Data(repeating: 0, count: 640)
        let body = TripVoiceClipContent(id: metadata.id, speakerId: metadata.speakerId, sequence: 1, durationMs: 20, pcmBase64: pcm.base64EncodedString())
        XCTAssertEqual(try body.decoded(for: metadata), pcm)
        XCTAssertThrowsError(try body.decoded(for: clip(2)))
        let short = TripVoiceClipContent(id: metadata.id, speakerId: metadata.speakerId, sequence: 1, durationMs: 20, pcmBase64: Data(repeating: 0, count: 638).base64EncodedString())
        XCTAssertThrowsError(try short.decoded(for: metadata))
    }
}

@MainActor
final class TripVoiceClipAudioTests: XCTestCase {
    func testEntireClipPlaysAsOneBufferAndCanBeCancelled() throws {
        let audio = TripVoiceAudio()
        defer { audio.stop() }
        try audio.listen()
        try audio.playClip(Data(repeating: 0, count: 16_000))
        XCTAssertTrue(audio.clipPlaying)
        audio.clearPlayback()
        XCTAssertFalse(audio.clipPlaying)
    }
    func testOldCompletionCannotResumeAfterClear() async throws {
        let audio = TripVoiceAudio()
        defer { audio.stop() }
        try audio.listen()
        try audio.playClip(Data(repeating: 0, count: 16_000))
        audio.clearPlayback()
        let played = audio.playedFrames
        try await Task.sleep(for: .milliseconds(200))
        XCTAssertEqual(audio.playedFrames, played)
        XCTAssertFalse(audio.clipPlaying)
        XCTAssertThrowsError(try audio.playClip(Data(repeating: 0, count: 639)))
    }
}
