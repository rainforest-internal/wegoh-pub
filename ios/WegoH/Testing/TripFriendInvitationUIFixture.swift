#if DEBUG
import SwiftUI

struct TripFriendInvitationUIFixture: View {
    nonisolated static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-trip-multi-invite-ui-testing") }
    static func configuration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TripFriendInvitationFixtureProtocol.self]
        return configuration
    }
    @MainActor static func sessionIfRequested() -> SessionManager? {
        requested ? SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: FriendsUIFixture.Credential()) : nil
    }
    @Environment(SessionManager.self) private var session
    @State private var store: TripPreparationStore?
    var body: some View {
        NavigationStack {
            Group {
                if let store {
                    TripPreparationView(store: store, versusAPI: .init(configuration: Self.configuration()),
                                        placeSearchAPI: IPhoneCourseAPI(configuration: Self.configuration()),
                                        friendsAPI: IPhoneFriendsAPI(configuration: Self.configuration()))
                } else { WegoLoadingView("초대 테스트 샘플 준비 중") }
            }
            .safeAreaInset(edge: .top) {
                Text("초대 테스트 샘플 · 실제 계정에 요청하지 않아요")
                    .font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                    .frame(maxWidth: .infinity).background(WegoTokens.Palette.accentSoft)
            }
        }
        .task(id: session.current?.accountID) {
            guard session.current != nil else { return }
            let value = TripPreparationStore(tripID: TripFriendInvitationFixtureProtocol.tripID, session: session,
                                            api: IPhoneTripAPI(configuration: Self.configuration()))
            store = value
            await value.load()
        }
    }
}

private final class TripFriendInvitationFixtureProtocol: URLProtocol {
    static let tripID = String(repeating: "a", count: 32)
    private static let lock = NSLock()
    private static var sent: Set<String> = []
    private static var failedDetail = false
    private static let names = ["샘플 방장", "초대한 친구", "참여한 친구", "초대할 친구", "정원 초과 친구", "다음 친구"]
    private static func account(_ number: Int) -> String { "team-" + String(repeating: String(number), count: 40) }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, value) = try Self.lock.withLock { try response() }
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func response() throws -> (Int, [String: Any]) {
        guard let url = request.url, url.host == "ios-api-wegoh.devforest.io" else { return (404, [:]) }
        let path = url.path
        if path.hasSuffix("/session") {
            return (200, ["user": ["id": Self.account(1), "displayName": Self.names[0]],
                          "scopes": ["account:read", "trips:read", "trips:manage", "friends:read"],
                          "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600])
        }
        if path.hasSuffix("/friends") {
            return (200, ["friends": (2...6).map { ["id": Self.account($0), "name": Self.names[$0 - 1], "handle": "sample\($0)"] },
                          "requests": [], "blocks": []])
        }
        if path.hasSuffix("/members"), request.httpMethod == "POST" {
            let data = request.httpBody ?? request.httpBodyStream.map { stream in
                stream.open(); defer { stream.close() }
                var result = Data(), buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; result.append(contentsOf: buffer.prefix(count)) }
                return result
            } ?? Data()
            let body = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard let target = body?["accountId"] as? String else { return (400, [:]) }
            if target == Self.account(5) { return (409, ["detail": "Trip is full"]) }
            Self.sent.insert(target)
            return (201, ["status": "pending"])
        }
        if path.hasSuffix("/trips/" + Self.tripID) {
            if ProcessInfo.processInfo.arguments.contains("-trip-multi-invite-refresh-fails"), !Self.sent.isEmpty, !Self.failedDetail {
                Self.failedDetail = true
                return (503, ["detail": "UNAVAILABLE"])
            }
            let numbers = [1, 2, 3] + (4...6).filter { Self.sent.contains(Self.account($0)) }
            let members: [[String: Any]] = numbers.map { number in
                ["id": Self.account(number), "name": Self.names[number - 1], "state": [1, 3].contains(number) ? "accepted" : "pending",
                 "isMe": number == 1, "isOwner": number == 1, "hasVehicle": false, "carId": NSNull(),
                 "readiness": [1, 3].contains(number) ? "needsCar" : "invited"]
            }
            return (200, ["id": Self.tripID, "title": "친구 초대 샘플", "description": "합성 여행", "state": "planned", "revision": 1,
                          "isOwner": true, "ownerId": Self.account(1), "myPermissions": ["invite": true, "edit": true],
                          "members": members, "cars": [], "unassigned": [["id": Self.account(1), "name": Self.names[0]], ["id": Self.account(3), "name": Self.names[2]]],
                          "courses": [], "locationConsent": false])
        }
        return (404, ["detail": "FIXTURE_ROUTE_UNAVAILABLE"])
    }
}
#endif
