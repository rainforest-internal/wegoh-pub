import Foundation

struct TripVoiceParticipation: Codable, Equatable {
    var tripId: String
    var participating: Bool
    var memberJoinedAt: String
    var revision: Int
    var isValid: Bool {
        validTripID(tripId) && (1...Int(Int32.max)).contains(revision)
            && !memberJoinedAt.isEmpty && memberJoinedAt.utf8.count <= 64
            && validJoinedAt
    }
    private var validJoinedAt: Bool {
        let parser = ISO8601DateFormatter()
        if parser.date(from: memberJoinedAt) != nil { return true }
        parser.formatOptions.insert(.withFractionalSeconds)
        return parser.date(from: memberJoinedAt) != nil
    }
}

enum TripVoiceFailure: Error, LocalizedError {
    case connection, protocolMismatch, microphone, audio, pressure
    var errorDescription: String? {
        switch self {
        case .connection: "워키토키에 연결하지 못했어요. 다시 눌러 주세요."
        case .protocolMismatch: "음성 연결 정보를 확인할 수 없어요. 다시 연결해 주세요."
        case .microphone: "마이크를 허용한 뒤 다시 눌러 주세요."
        case .audio: "마이크나 스피커를 사용할 수 없어요. 연결을 확인해 주세요."
        case .pressure: "음성 전달이 지연돼 멈췄어요. 다시 눌러 주세요."
        }
    }
}

struct TripVoiceWire {
    struct Floor: Decodable, Equatable { var leaseId: String; var speakerId: String }
    struct Format: Decodable {
        var encoding: String; var sampleRate: Int; var channels: Int
        var samplesPerFrame: Int; var frameBytes: Int; var sequence: String
        var isValid: Bool {
            encoding == "pcm_s16le" && sampleRate == 16_000 && channels == 1
                && samplesPerFrame == 320 && frameBytes == 644 && sequence == "uint32-le-first0"
        }
    }
    struct Control: Decodable {
        var type: String
        var leaseId: String?
        var speakerId: String?
        var leaseSeconds: Int?
        var automaticTransmit: Bool?
        var format: Format?
        var floor: Floor?
        func validatedFloor(members: Set<String>) throws -> Floor {
            guard let leaseId, validTripID(leaseId), let speakerId, members.contains(speakerId)
            else { throw TripVoiceFailure.protocolMismatch }
            return Floor(leaseId: leaseId, speakerId: speakerId)
        }
    }
    static func control(_ text: String) throws -> Control {
        guard let data = text.data(using: .utf8), data.count <= 2048 else { throw TripVoiceFailure.protocolMismatch }
        return try JSONDecoder().decode(Control.self, from: data)
    }
    static func frame(sequence: UInt32, pcm: Data) throws -> Data {
        guard pcm.count == 640 else { throw TripVoiceFailure.protocolMismatch }
        var value = sequence.littleEndian
        return withUnsafeBytes(of: &value) { Data($0) } + pcm
    }
    static func pcm(_ frame: Data, after sequence: UInt32?) throws -> (UInt32, Data) {
        guard frame.count == 644 else { throw TripVoiceFailure.protocolMismatch }
        let next = frame.prefix(4).enumerated().reduce(UInt32(0)) { $0 | UInt32($1.element) << ($1.offset * 8) }
        if let sequence, sequence == .max || next != sequence + 1 { throw TripVoiceFailure.protocolMismatch }
        return (next, Data(frame.dropFirst(4)))
    }
}

struct TripVoiceFloorState {
    private(set) var floor: TripVoiceWire.Floor?
    private(set) var requested = false
    private(set) var held = false
    private(set) var speaking = false
    private(set) var stopping = false
    mutating func request() -> Bool {
        guard floor == nil, !requested, !stopping else { return false }
        requested = true; held = true
        return true
    }
    mutating func release() -> Bool {
        let notify = requested && !stopping
        held = false; speaking = false
        if requested { stopping = true }
        return notify
    }
    mutating func granted(_ floor: TripVoiceWire.Floor) -> Bool {
        self.floor = floor
        guard requested, held, !stopping else { stopping = true; return false }
        speaking = true
        return true
    }
    mutating func started(_ floor: TripVoiceWire.Floor) {
        self.floor = floor; held = false; speaking = false
    }
    mutating func ended(_ lease: String) {
        guard floor?.leaseId == lease else { return }
        self = .init()
    }
    mutating func denied() {
        requested = false; held = false; speaking = false; stopping = false
    }
    mutating func reset() { self = .init() }
}
