import Foundation
import Observation

enum TripSignalReason: String, CaseIterable, Identifiable {
    case restroom, coffee, hungry, rest, drowsy, fuel, charging, nursing, smoking
    var id: Self { self }
    var title: String {
        switch self {
        case .restroom: "화장실"; case .coffee: "카페"; case .hungry: "배고파요"
        case .rest: "쉬어 가요"; case .drowsy: "졸려요"; case .fuel: "주유"
        case .charging: "전기차 충전"; case .nursing: "수유"; case .smoking: "흡연"
        }
    }
    var serverKind: String { switch self { case .coffee: "cafe"; case .charging: "ev_charge"; default: rawValue } }
    var symbol: String {
        switch self {
        case .restroom: "figure.stand"; case .coffee: "cup.and.saucer"; case .hungry: "fork.knife"
        case .rest: "bed.double"; case .drowsy: "moon.zzz"; case .fuel: "fuelpump"
        case .charging: "bolt"; case .nursing: "waterbottle"; case .smoking: "smoke"
        }
    }
}

struct TripSignalPlace: Identifiable, Equatable {
    let id: String
    let name: String
    let ahead: String
    let detail: String
    let facilities: Set<TripSignalFacility>
    static let samples = [
        Self(id: "gujeong", name: "서산휴게소", ahead: "8.4km 앞", detail: "서해안선 · 목포 방향 · 들르면 +2분",
             facilities: Set(TripSignalFacility.allCases)),
        Self(id: "okgye", name: "홍성휴게소", ahead: "21km 앞", detail: "서해안선 · 목포 방향 · 들르면 +4분",
             facilities: Set(TripSignalFacility.allCases)),
        Self(id: "gangneung", name: "대천휴게소", ahead: "34km 앞", detail: "서해안선 · 목포 방향",
             facilities: Set(TripSignalFacility.allCases))
    ]
}

enum TripSignalFacility: String, CaseIterable, Identifiable {
    case restroom, nursing, charging, fuel, lpg, restSpace
    var id: Self { self }
    var serverID: String { switch self { case .restroom: "toilet"; case .charging: "evCharger"; case .fuel: "gasStation"; default: rawValue } }
    var title: String {
        switch self { case .restroom: "화장실"; case .nursing: "수유실"; case .charging: "전기차 충전"; case .fuel: "주유소"; case .lpg: "LPG"; case .restSpace: "쉼터" }
    }
}

@MainActor @Observable
final class TripSignalPreviewStore {
    enum Phase: Equatable { case reason, place, waiting, received, agreed, declined, completed, cancelled }
    var reason: TripSignalReason = .restroom
    var facilities: Set<TripSignalFacility> = [.restroom]
    var placeID: String? = TripSignalPlace.samples.first?.id
    private(set) var phase = Phase.reason
    private(set) var received = false
    private(set) var insertedPlaceName: String?
    var selectedPlace: TripSignalPlace? { candidates.first { $0.id == placeID } }
    var candidates: [TripSignalPlace] { TripSignalPlace.samples.filter { facilities.isSubset(of: $0.facilities) } }
    var canSend: Bool { phase == .place && (placeID == nil || selectedPlace != nil) }
    var isOpen: Bool { [.waiting, .received, .agreed].contains(phase) }

    func begin() {
        guard !isOpen else { return }
        received = false
        phase = .reason
    }
    func chooseReason(_ value: TripSignalReason) { guard phase == .reason else { return }; reason = value }
    func next() { guard phase == .reason else { return }; phase = .place }
    func back() { guard phase == .place else { return }; phase = .reason }
    func send() { guard canSend else { return }; phase = .waiting }
    func showReceived() {
        guard !isOpen else { return }
        received = true
        reason = .restroom
        placeID = TripSignalPlace.samples.first?.id
        phase = .received
    }
    func vote(agree: Bool) { guard phase == .received else { return }; phase = agree ? .waiting : .declined }
    func resolveSample(agreed: Bool) {
        guard phase == .waiting else { return }
        phase = agreed ? .agreed : .declined
        if agreed { insertedPlaceName = selectedPlace?.name }
    }
    func finish() { guard phase == .agreed, !received else { return }; phase = .completed }
    func cancel() { guard [.waiting, .agreed].contains(phase), !received else { return }; phase = .cancelled }
}
