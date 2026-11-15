import Foundation

struct TripVoiceClip: Codable, Equatable {
    let id: String
    let speakerId: String
    let sequence: Int
    let durationMs: Int
    var isValid: Bool {
        validTripID(id) && validTripAccountID(speakerId) && sequence > 0
            && (20...15_000).contains(durationMs) && durationMs.isMultiple(of: 20)
    }
}

struct TripVoiceClipFeed: Decodable {
    let cursor: String
    let clips: [TripVoiceClip]
}

struct TripVoiceClipContent: Decodable {
    let id: String
    let speakerId: String
    let sequence: Int
    let durationMs: Int
    let pcmBase64: String
    func decoded(for clip: TripVoiceClip) throws -> Data {
        guard TripVoiceClip(id: id, speakerId: speakerId, sequence: sequence, durationMs: durationMs) == clip,
              clip.isValid, pcmBase64.utf8.count <= 640_000,
              let pcm = Data(base64Encoded: pcmBase64), pcm.count == durationMs * 32,
              pcm.count.isMultiple(of: 640) else { throw TripVoiceFailure.protocolMismatch }
        return pcm
    }
}

struct TripVoiceClipDraft {
    let clientMessageId: String
    private(set) var pcm = Data()
    private let startedAt: ContinuousClock.Instant
    init(clientMessageId: String, startedAt: ContinuousClock.Instant = .now) {
        self.clientMessageId = clientMessageId; self.startedAt = startedAt
    }
    var isExpired: Bool { ContinuousClock.now >= startedAt.advanced(by: .seconds(60)) }
    var durationMs: Int { pcm.count / 32 }
    var isFull: Bool { pcm.count == 480_000 }
    mutating func append(_ frame: Data) throws {
        guard frame.count == 640 else { throw TripVoiceFailure.protocolMismatch }
        guard !isFull else { return }
        pcm.append(frame)
    }
    func payload() throws -> Data {
        struct Upload: Encodable { let clientMessageId: String; let pcmBase64: String }
        guard validTripID(clientMessageId), !pcm.isEmpty, !isExpired else { throw TripVoiceFailure.audio }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .withoutEscapingSlashes
        return try encoder.encode(Upload(clientMessageId: clientMessageId, pcmBase64: pcm.base64EncodedString()))
    }
}

struct TripVoiceClipInbox {
    private(set) var cursor: String?
    private var pending: [TripVoiceClip] = []
    private var lastSequence = 0
    var count: Int { pending.count }
    mutating func ingest(_ feed: TripVoiceClipFeed, excluding speakers: Set<String>) throws {
        let parts = feed.cursor.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, validTripID(String(parts[0])),
              let latest = Int(parts[1]), latest >= 0, feed.clips.count <= 20,
              feed.clips.allSatisfy(\.isValid),
              feed.clips.allSatisfy({ $0.sequence <= latest }),
              zip(feed.clips, feed.clips.dropFirst()).allSatisfy({ pair in pair.0.sequence < pair.1.sequence }),
              Set(feed.clips.map(\.id)).count == feed.clips.count else { throw TripVoiceFailure.protocolMismatch }
        let previousBoot = cursor?.split(separator: ":").first.map(String.init)
        if previousBoot != String(parts[0]) {
            guard feed.clips.isEmpty else { throw TripVoiceFailure.protocolMismatch }
            pending.removeAll(); lastSequence = latest
        } else {
            guard latest >= lastSequence else { throw TripVoiceFailure.protocolMismatch }
            for clip in feed.clips where clip.sequence > lastSequence && !speakers.contains(clip.speakerId) {
                pending.append(clip)
            }
            if pending.count > 4 { pending.removeFirst(pending.count - 4) }
            lastSequence = latest
        }
        cursor = feed.cursor
    }
    mutating func next() -> TripVoiceClip? { pending.isEmpty ? nil : pending.removeFirst() }
    mutating func discard(speaker: String) { pending.removeAll { $0.speakerId == speaker } }
    mutating func clear() { self = .init() }
}

final class TripVoiceClipCapture: @unchecked Sendable {
    private let lock = NSLock()
    private var draft: TripVoiceClipDraft?
    init(clientMessageId: String) { draft = TripVoiceClipDraft(clientMessageId: clientMessageId) }
    var durationMs: Int { lock.lock(); defer { lock.unlock() }; return draft?.durationMs ?? 0 }
    func append(_ frame: Data) throws -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard draft != nil, draft?.isFull == false else { return false }
        try draft?.append(frame)
        return draft?.isFull == true
    }
    func finish() -> TripVoiceClipDraft? {
        lock.lock(); defer { lock.unlock() }
        defer { draft = nil }
        return draft
    }
}
