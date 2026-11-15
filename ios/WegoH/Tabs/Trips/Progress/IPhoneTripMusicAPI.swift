import Foundation

struct IPhoneTripMusicPage: Codable, Equatable {
    struct Item: Codable, Identifiable, Equatable {
        struct Person: Codable, Equatable { var id: String; var name: String }
        var id: String
        var title: String
        var url: String
        var addedBy: Person
        var reviewState: String
        var platform: MusicPlatform { URL(string: url).map(MusicPlatform.detected(for:)) ?? .other }
        var visibilityLabel: String {
            switch reviewState {
            case "approved": "일행에게 공유 중"
            case "quarantined": "공유 검토 중 · 나에게만 표시"
            case "rejected": "공유 검토 보류 · 나에게만 표시"
            default: "나에게만 표시"
            }
        }
    }
    /// The trip playlist item a member's car opened most recently. Not the external app's live playback state.
    struct Playback: Codable, Equatable {
        var itemId: String
        var startedBy: Item.Person
        var startedAt: String
    }
    var tripId: String
    var musicSharing: Bool
    var items: [Item]
    var limit: Int
    var canAdd: Bool
    var canReorder: Bool
    var nowPlaying: [Playback]
    func permitsDisplay(to accountID: String) -> Bool {
        items.allSatisfy { $0.reviewState == "approved" || $0.addedBy.id == accountID }
    }
    func item(_ id: String) -> Item? { items.first { $0.id == id } }
    func isPlaying(_ item: Item) -> Bool { nowPlaying.contains { $0.itemId == item.id } }
    var isValid: Bool {
        let ids = Set(items.map(\.id))
        return validTripID(tripId) && limit == 200 && items.count <= limit
            && ids.count == items.count && items.allSatisfy {
                validTripID($0.id) && validTripText($0.title, max: 120)
                    && MusicPreviewStore.validatedURL($0.url) != nil
                    && validTripAccountID($0.addedBy.id) && validTripText($0.addedBy.name, max: 80)
                    && ["private", "quarantined", "approved", "rejected"].contains($0.reviewState)
            }
            && nowPlaying.count <= 20 && Set(nowPlaying.map(\.startedBy.id)).count == nowPlaying.count
            && nowPlaying.allSatisfy {
                ids.contains($0.itemId) && validTripAccountID($0.startedBy.id)
                    && validTripText($0.startedBy.name, max: 80) && validTripText($0.startedAt, max: 40)
            }
    }
}

struct TripMusicDraft: Equatable {
    var title = ""
    var url = ""
    var platform = MusicPlatform.other
    var rightsConfirmed = false
    var reviewConsent = false
    var isValid: Bool {
        guard validTripText(title.trimmingCharacters(in: .whitespacesAndNewlines), max: 120),
              let value = MusicPreviewStore.validatedURL(url), rightsConfirmed else { return false }
        return platform == .other || platform == MusicPlatform.detected(for: value)
    }
}

/// 계정의 내 플레이리스트에 저장된 곡 하나. 서버가 저장본에서 제목과 링크를 읽으므로 다시 입력하지 않는다.
struct TripMusicSavedSelection: Hashable {
    var playlistId: String
    var playlistRevision: Int
    var trackId: String
}

protocol IPhoneTripMusicServing {
    func load(_ tripID: String, token: String) async throws -> IPhoneTripMusicPage
    func sharing(_ tripID: String, enabled: Bool, token: String) async throws -> IPhoneTripMusicPage
    func add(_ tripID: String, draft: TripMusicDraft, token: String) async throws -> IPhoneTripMusicPage
    /// Places `itemID` right after `afterID`, or first when `afterID` is nil. DJ and trip owner only.
    func move(_ tripID: String, itemID: String, after afterID: String?, token: String) async throws -> IPhoneTripMusicPage
    func library(token: String) async throws -> [AccountMusicPlaylist]
    func addSaved(_ tripID: String, selection: TripMusicSavedSelection, rightsConfirmed: Bool, token: String) async throws -> IPhoneTripMusicPage
}

struct IPhoneTripMusicAPI: IPhoneTripMusicServing {
    private let http: IPhoneSessionAPI
    private let account: IPhoneMusicAPI
    init(configuration: URLSessionConfiguration? = nil) {
        http = .init(configuration: configuration); account = .init(configuration: configuration)
    }
    private func request(_ tripID: String, suffix: String = "", method: String = "GET", payload: Data? = nil,
                         status: Int? = nil, token: String) async throws -> IPhoneTripMusicPage {
        guard validTripID(tripID) else { throw IPhoneResourceError.invalidInput }
        let data = try await http.resource("trips/" + tripID + "/music" + suffix, method: method, payload: payload,
                                          token: token, status: status ?? (method == "POST" ? 201 : 200))
        let value: IPhoneTripMusicPage
        do { value = try JSONDecoder().decode(IPhoneTripMusicPage.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
        guard value.tripId == tripID, value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }
    func load(_ tripID: String, token: String) async throws -> IPhoneTripMusicPage {
        try await request(tripID, token: token)
    }
    func sharing(_ tripID: String, enabled: Bool, token: String) async throws -> IPhoneTripMusicPage {
        try await request(tripID, suffix: "/sharing", method: "PATCH", payload: JSONEncoder().encode(["enabled": enabled]), token: token)
    }
    func add(_ tripID: String, draft: TripMusicDraft, token: String) async throws -> IPhoneTripMusicPage {
        guard draft.isValid else { throw IPhoneResourceError.invalidInput }
        struct Payload: Encodable { var title: String; var url: String; var rightsConfirmed: Bool; var reviewConsent: Bool }
        let value = Payload(title: draft.title.trimmingCharacters(in: .whitespacesAndNewlines),
                            url: draft.url.trimmingCharacters(in: .whitespacesAndNewlines),
                            rightsConfirmed: draft.rightsConfirmed, reviewConsent: draft.reviewConsent)
        return try await request(tripID, suffix: "/playlist", method: "POST", payload: JSONEncoder().encode(value), token: token)
    }
    func move(_ tripID: String, itemID: String, after afterID: String?, token: String) async throws -> IPhoneTripMusicPage {
        guard validTripID(itemID), afterID.map({ validTripID($0) && $0 != itemID }) ?? true else {
            throw IPhoneResourceError.invalidInput
        }
        // afterId must be present even when null, so encode it explicitly instead of letting Codable omit nil.
        let payload = try JSONSerialization.data(withJSONObject: ["afterId": afterID.map { $0 as Any } ?? NSNull()])
        return try await request(tripID, suffix: "/playlist/" + itemID + "/position", method: "PATCH", payload: payload, token: token)
    }
    func library(token: String) async throws -> [AccountMusicPlaylist] {
        try await account.list(token: token)
    }
    func addSaved(_ tripID: String, selection: TripMusicSavedSelection, rightsConfirmed: Bool, token: String) async throws -> IPhoneTripMusicPage {
        guard rightsConfirmed, validTripID(selection.playlistId), validTripID(selection.trackId),
              (1...Int(Int32.max)).contains(selection.playlistRevision) else { throw IPhoneResourceError.invalidInput }
        // 저장한 곡은 일행과 함께 듣기 위한 추가라 항상 공유 검토를 요청한다. 같은 곡은 서버가 한 항목으로 유지한다.
        struct Payload: Encodable { var playlistId: String; var playlistRevision: Int; var trackId: String; var rightsConfirmed: Bool; var reviewConsent: Bool }
        let value = Payload(playlistId: selection.playlistId, playlistRevision: selection.playlistRevision,
                            trackId: selection.trackId, rightsConfirmed: rightsConfirmed, reviewConsent: true)
        return try await request(tripID, suffix: "/saved-playlists", method: "POST", payload: JSONEncoder().encode(value),
                                 status: 200, token: token)
    }
}

func tripMusicFailureIsDefinitive(_ error: Error) -> Bool {
    if let error = error as? IPhoneResourceError {
        if case .unavailable = error { return false }
        return true
    }
    if let error = error as? IPhoneSessionError {
        switch error {
        case .invalidSession, .forbidden, .expired, .rateLimited: return true
        default: return false
        }
    }
    return false
}
