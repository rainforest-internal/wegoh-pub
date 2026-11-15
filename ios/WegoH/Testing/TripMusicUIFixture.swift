#if DEBUG
import SwiftUI

struct TripMusicUIFixture: View {
    nonisolated static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-trip-music-ui-testing") }
    static func configuration() -> URLSessionConfiguration {
        let value = URLSessionConfiguration.ephemeral; value.protocolClasses = [TripMusicFixtureProtocol.self]; return value
    }
    @MainActor static func sessionIfRequested() -> SessionManager? {
        requested ? SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: FriendsUIFixture.Credential()) : nil
    }
    @Environment(SessionManager.self) private var session
    @State private var preparation: TripPreparationStore?
    var body: some View {
        NavigationStack {
            Group {
                if let preparation, let detail = preparation.detail {
                    ScrollView {
                        TripProgressView(detail: detail, isPreview: false, courseStops: [:], preparation: preparation,
                                         musicAPI: IPhoneTripMusicAPI(configuration: Self.configuration()), remotePreferences: .constant(.init()))
                            .padding(WegoTokens.Space.screen)
                    }
                } else { WegoLoadingView("음악 테스트 샘플 준비 중") }
            }.safeAreaInset(edge: .top) {
                VStack(spacing: WegoTokens.Space.xSmall) {
                    Text("음악 테스트 샘플 · 실제 계정·음악 앱을 사용하지 않아요")
                    TimelineView(.periodic(from: .now, by: 0.2)) { _ in
                        Text("추가 요청 \(TripMusicFixtureProtocol.postCount)").accessibilityIdentifier("tripMusicFixturePosts")
                    }
                }.font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                    .frame(maxWidth: .infinity).background(WegoTokens.Palette.accentSoft)
            }
        }.task(id: session.current?.accountID) {
            guard session.current != nil else { return }
            let value = TripPreparationStore(tripID: TripMusicFixtureProtocol.trip, session: session,
                                            api: IPhoneTripAPI(configuration: Self.configuration()))
            preparation = value; await value.load()
        }
    }
}

private final class TripMusicFixtureProtocol: URLProtocol {
    static let trip = String(repeating: "a", count: 32)
    private static let actor = "team-" + String(repeating: "1", count: 40)
    private static let lock = NSLock()
    private static var enabled = false
    private static var items: [[String: Any]] = []
    private static var posts = 0
    private static let library: [[String: Any]] = [
        ["id": String(repeating: "d", count: 32), "title": "합성 저장 곡", "url": "https://open.spotify.com/track/sample"],
    ]
    static var postCount: Int { lock.withLock { posts } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, value) = try Self.lock.withLock { try reply() }
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value)); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private static func page() -> [String: Any] {
        ["tripId": trip, "musicSharing": enabled, "items": items, "limit": 200, "canAdd": true, "canReorder": true, "nowPlaying": []]
    }
    private func payload() throws -> [String: Any] {
        let data = request.httpBody ?? request.httpBodyStream.map { stream in
            stream.open(); defer { stream.close() }
            var result = Data(), buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; result.append(contentsOf: buffer.prefix(n)) }
            return result
        } ?? Data()
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }
    private func reply() throws -> (Int, [String: Any]) {
        guard request.url?.host == "ios-api-wegoh.devforest.io" else { return (404, [:]) }
        let path = request.url!.path
        if path.hasSuffix("/session") {
            return (200, ["user": ["id": Self.actor, "displayName": "음악 샘플"], "scopes": ["account:read", "trips:read", "trips:manage"], "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600])
        }
        if path.hasSuffix("/music/sharing") {
            Self.enabled = try payload()["enabled"] as? Bool ?? false
            if !Self.enabled { Self.items = [] }
            return (200, Self.page())
        }
        if path.hasSuffix("/music/saved-playlists") {
            let value = try payload()
            guard value["rightsConfirmed"] as? Bool == true, value["reviewConsent"] as? Bool == true,
                  let track = Self.library.first(where: { $0["id"] as? String == value["trackId"] as? String }) else { return (400, [:]) }
            Self.posts += 1
            Self.items.append(["id": String(format: "%032x", Self.posts), "title": track["title"] ?? "음악", "url": track["url"] ?? "https://example.invalid/song",
                               "addedBy": ["id": Self.actor, "name": "음악 샘플"], "reviewState": "quarantined"])
            return (200, Self.page())
        }
        if path.hasSuffix("/v1/iphone/playlists") {
            let tracks = ProcessInfo.processInfo.arguments.contains("-trip-music-library") ? Self.library : []
            return (200, ["playlists": tracks.isEmpty ? [] : [["id": String(repeating: "c", count: 32), "name": "드라이브 모음", "tracks": tracks, "revision": 1]]])
        }
        if path.hasSuffix("/music/playlist") {
            let value = try payload()
            guard Self.enabled, value["rightsConfirmed"] as? Bool == true else { return (403, [:]) }
            Self.posts += 1
            Self.items.append(["id": String(format: "%032x", Self.posts), "title": value["title"] ?? "음악", "url": value["url"] ?? "https://example.invalid/song",
                               "addedBy": ["id": Self.actor, "name": "음악 샘플"], "reviewState": value["reviewConsent"] as? Bool == true ? "quarantined" : "private"])
            if ProcessInfo.processInfo.arguments.contains("-trip-music-post-lost"), Self.posts == 1 { throw URLError(.networkConnectionLost) }
            return (201, Self.page())
        }
        if path.hasSuffix("/music") { return (200, Self.page()) }
        if path.hasSuffix("/trips/" + Self.trip) {
            return (200, ["id": Self.trip, "title": "음악 샘플 여행", "description": "합성 여행", "state": "active", "revision": 1,
                          "isOwner": true, "ownerId": Self.actor, "myPermissions": ["invite": true, "edit": true],
                          "members": [["id": Self.actor, "name": "음악 샘플", "state": "accepted", "isMe": true, "isOwner": true, "hasVehicle": false, "carId": NSNull(), "readiness": "needsCar"]],
                          "cars": [], "unassigned": [["id": Self.actor, "name": "음악 샘플"]], "courses": [], "locationConsent": false])
        }
        return (404, [:])
    }
}
#endif
