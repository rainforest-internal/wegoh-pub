#if DEBUG
import Foundation

@MainActor
enum FriendsUIFixture {
    static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-friends-ui-testing") }
    static func configuration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FriendsFixtureProtocol.self]
        return configuration
    }
    static func sessionIfRequested() -> SessionManager? {
        guard requested else { return nil }
        return SessionManager(api: IPhoneSessionAPI(configuration: configuration()), credentials: Credential())
    }
    final class Credential: IPhoneCredentialStoring {
        private var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
        func load() throws -> StoredIPhoneCredential? { value }
        func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
        func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
        func clearToken() throws { value = nil }
    }
}

private final class FriendsFixtureProtocol: URLProtocol {
    private static let lock = NSLock()
    private static let names = ["사용자A", "사용자C", "사용자B", "사용자E", "사용자A", "사용자B", "사용자C", "사용자E"]
    private static let handles = ["hajn2048", "mins2048", "jiwo2048", "doyn2048", "seoy2048", "junh2048", "yujn2048", "nara2048"]
    private static var relations = ProcessInfo.processInfo.arguments.contains("-friends-ui-empty")
        ? Array(repeating: "none", count: names.count)
        : ProcessInfo.processInfo.arguments.contains("-friends-ui-short-list")
            ? ["friend"] + Array(repeating: "none", count: names.count - 1)
            : ["friend", "friend", "friend", "incoming", "none", "none", "blocked", "none"]
    private static var failedSearch = false
    private static var overviewReads = 0
    private static func identifier(_ index: Int) -> String { "team-" + String(repeating: String(index + 1), count: 40) }
    private static func person(_ index: Int) -> [String: Any] {
        ["id": identifier(index), "name": names[index], "handle": handles[index]]
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        Self.lock.lock(); defer { Self.lock.unlock() }
        do {
            let (status, value) = try response()
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                            headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if status != 204 {
                client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value))
            }
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    private func response() throws -> (Int, [String: Any]) {
        let path = request.url!.path, method = request.httpMethod ?? "GET"
        if path.hasSuffix("/session") {
            if request.httpMethod == "DELETE" { return (204, [:]) }
            return (200, ["user": ["id": "team-" + String(repeating: "0", count: 40), "displayName": "사용자D"],
                "scopes": ["account:read", "friends:read", "friends:manage"], "expiresAt": Int(Date.now.timeIntervalSince1970) + 3600])
        }
        if path.hasSuffix("/friends/search") {
            if ProcessInfo.processInfo.arguments.contains("-friends-ui-search-retry"), !Self.failedSearch {
                Self.failedSearch = true
                return (503, ["detail": "UNAVAILABLE"])
            }
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value
            guard let index = Self.handles.firstIndex(where: { $0 == query }), Self.relations[index] != "blocked" else {
                return (200, ["person": NSNull()])
            }
            return (200, ["person": Self.person(index).merging(["relationship": Self.relations[index]]) { _, new in new }])
        }
        if path.hasSuffix("/friends"), method == "GET" {
            Self.overviewReads += 1
            if ProcessInfo.processInfo.arguments.contains("-friends-ui-cache-fail-refresh"), Self.overviewReads > 1 {
                return (503, ["detail": "UNAVAILABLE"])
            }
            if ProcessInfo.processInfo.arguments.contains("-friends-ui-list-failure") {
                return (503, ["detail": "UNAVAILABLE"])
            }
            var friends: [[String: Any]] = [], requests: [[String: Any]] = [], blocks: [[String: Any]] = []
            for index in Self.names.indices {
                let person = Self.person(index)
                switch Self.relations[index] {
                case "friend": friends.append(person)
                case "incoming", "outgoing": requests.append(person.merging(["direction": Self.relations[index]]) { _, new in new })
                case "blocked": blocks.append(person)
                default: break
                }
            }
            return (200, ["friends": friends, "requests": requests, "blocks": blocks])
        }
        let payload = try body()
        let target = payload["targetId"] as? String ?? path.split(separator: "/").map(String.init).first(where: { $0.hasPrefix("team-") })
        guard let index = Self.names.indices.first(where: { Self.identifier($0) == target }) else { return (404, [:]) }
        if path.hasSuffix("/profile") {
            return (200, ["name": Self.names[index], "plateNumbers": index == 0 ? ["12가3456"] : []])
        }
        let relation: String, status: String
        if path.hasSuffix("/requests") { (relation, status) = ("outgoing", "pending") }
        else if path.hasSuffix("/respond") { (relation, status) = payload["accept"] as? Bool == true ? ("friend", "accepted") : ("none", "declined") }
        else if path.hasSuffix("/blocks") { (relation, status) = ("blocked", "blocked") }
        else { (relation, status) = ("none", path.contains("/blocks/") ? "unblocked" : "removed") }
        Self.relations[index] = relation
        return (200, ["status": status])
    }
    private func body() throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 2048)
            while stream.hasBytesAvailable {
                let count = stream.read(&bytes, maxLength: bytes.count)
                guard count > 0 else { break }
                data.append(contentsOf: bytes.prefix(count))
            }
        }
        return data.isEmpty ? [:] : try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
}
#endif
